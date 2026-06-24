# 全国评分改为 GRIB 栅格批量计算 — 设计 (#19)

Parent epic: #3 · Branch: `codex/19-national-grib-grid`

## 目标

消除逐点 API 瓶颈:全国地图直接用同一份 GFS 0.25° 原始网格,一次读取 → 整区
向量化评分,把概览从 ~190 个粗点(4° ≈ 400km)升级到 ~3.7 万格点(~25km)的
精细场——这就是把"玩具"图变成 SunsetWx 那种连续精细场的根因(#40)。

## 设计(自底向上,逐层测试)

- **`predictor/grid_score.py`**:`score_grid(GridInputs) -> ndarray`,把
  `predictor.rules` 的概览子集(presence/obstruction/clean-air gate + humidity/
  altitude/sweet-spot modifier,gate×modifier)**向量化**。概览各格按各自日落
  评估,故 solar gate ≡ 1。`test_grid_score` 把结果**钉到标量 `RuleBasedPredictor`
  容差 1e-9**,保证两者不漂移。
- **`predictor/gfs.py`**:`SurfaceGrid` + `fetch_surface_grid(bbox, valid_time)`
  ——一次读取 GFS 地面场(LCDC/MCDC/HCDC 云量、2m RH `r2`、能见度 `vis`),
  按 bbox 裁剪。`_load_surface` 复用 cycle 选择/回退 + 独立缓存。
- **`predictor/national_field.py`**:`build_national_field(gfs_source, bbox,
  valid_time)` 串起来:一次读取 → NaN 安全映射 → `score_grid` → 返回 ascending
  lats/lons/probability + **数据量/运行时间/峰值内存**指标。
- **`app/overlay.py`**:`_build` 改用 `build_national_field`(模块级 `_GFS`),
  valid time = 域中心日落;turbo 渲染只需 2× 上采样(原 4° 网格要 6×);打印
  perf 指标,响应附 `n_points`/`valid_utc`。

## 验收标准映射

- [x] 单次读取所需变量后向量化计算整个目标区域(`fetch_surface_grid` + `score_grid`)
- [x] 不再为每个网格点重复下载或解码(一次读取 + 缓存)
- [x] 支持区域裁剪(bbox);多时间步:`fetch_surface_grid` 接受任意 valid_time,
      概览 v1 用单时次(与 SunsetWx 单预报时次一致);逐格日落选时为后续细化。
- [x] 结果与等价点预测在容差内一致(`test_grid_score` 1e-9 vs 标量 predictor)
- [x] 记录数据量、运行时间、峰值内存(`NationalField` 指标 + overlay 打印)

## 实测(合成 0.25° 全国场)

37,697 格点,score_grid **0.002s**、峰值 **5.4MB**;渲染为精细 turbo 场(对比旧
4° 色块),目视确认。真实 GFS 端到端由 `test_gfs_surface_integration`(live)验证
`r2`/`vis`/`lcc/mcc/hcc` shortname。

## 已知取舍

- 单时次概览:东西部并非各自精确日落时刻的大气态(GFS 同一 valid time)。逐格
  日落的多时次选时是 follow-up。
- 分辨率 ~25km(GFS 0.25°),非 SunsetWx 的 3km(NAM 仅北美);中国区无现成免费
  3km 模型,GFS 是最实际的免费高分选择。
