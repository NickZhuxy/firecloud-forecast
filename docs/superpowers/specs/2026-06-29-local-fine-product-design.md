# #62 — 坐标局部精细产品（局部跑完整单点物理）— 设计

Epic #55。依赖 #57（好的单点物理，已落地 FA-G5/A2/T1）+ #61（CLI，已落地，已占位 `--lat/--lon`）。
Owner 默认（2026-06-29）：半径 ~150 km、局部 0.1° 网格、出 JSON。
Branch: `codex/62-local-fine-product`（off main）。

## 目标与核心难点

`--lat/--lon` 时在坐标周边小区域跑**完整单点物理**（FA-G5 截面光追 + 云诊断 + AOD）——
国家级 `grid_score` 省掉的真保真，而非密插值。

**难点**：单点详细物理每点要一个 GFS cube；局部网格几百点不能每点取一次 cube。
**解法**：取**一次**覆盖整个局部区域 + 所有格点日落路径的 cube，所有格点**共享**它跑分。

## 改动（PR-A 算法核心，可离线测）

1. **抽出共享-cube 跑分核心** [sunward_section.py](../../../predictor/sunward_section.py)
   - 新 `score_point_with_cube(predictor, cube, snapshot, lat, lon, time, *, …)`：对**预取的 cube +
     snapshot** 跑 `assemble_sunward_cross_section` + `score_snapshot`（即现
     `score_point_with_sunward_section` 的尾段）。
   - `score_point_with_sunward_section` 重构为：取 snapshot + 取 cube（本点路径 bbox）+ 调核心。
     行为不变（既有测试保绿）。
2. **局部网格 + 场** 新 `predictor/local_field.py`
   - `local_grid(center_lat, center_lon, *, radius_km=150, resolution_deg=0.1, max_points=900)`：
     等经纬步长网格，半径换算到度（lat: km/111；lon: km/(111·cosφ)）；**上限封顶**（超则报错
     提示调小半径/调大步长，控时延）。
   - `LocalField(lats, lons, probability, center, radius_km, solar_event, valid_time, …)`。
   - `build_local_field(predictor, cube_source, center_lat, center_lon, time, *, radius_km,
     resolution_deg, max_points, config, aod_fn, …)`：建网格 → 算覆盖所有点日落路径的 union bbox →
     **取一次 cube** → 逐点 `predictor.source.fetch` + `score_point_with_cube` → 概率场。

## 验收不变量（离线，合成数据）

**格点分 == 独立单点分**：同 predictor/同 cube_source（FakeCubeSource 固定 cube）/同 FakeSource
snapshot 下，`build_local_field` 在格点 (la,lo) 的概率 == `score_point_with_sunward_section(
predictor, cube_source, la, lo, time).probability`。证明局部图物理判据与单点一致（#62 验收）。
另：网格构造（半径/步长/封顶）、union bbox 覆盖、空网格/越界退化。

## 不在 PR-A（PR-B 跟进）

- 渲染局部放大图（复用 national_product 绘图风格，裁到局部 bbox）+ JSON →
  `output/{date}/point-{lat}_{lon}-{event}.png`。
- CLI `--lat/--lon` 接 `build_local_field`（现占位打印"未实现"）。
- 生产 snapshot 批量化（Open-Meteo `fetch_many` 280/请求，替逐点 fetch 控时延）——
  PR-A 用逐点 `source.fetch`（离线 FakeSource 无碍），批量留 PR-B/后续。

## 安全

`score_point_with_cube` 抽取为重构（`score_point_with_sunward_section` 行为/签名不变，既有测试绿）。
`local_field` 全新、不碰国家级/grid。默认 `solar_event` 经 `time`（事件时刻）驱动，与 #60 一致。
