# 把 2-D 大气截面引入单点评分链路 — 设计 (#62 plumbing / 解锁 #57 P1 余项)

Parent: Epic #54（单点物理拟真）+ #62（坐标→本地精细产品）。
依据：`research/theory/single-point-fidelity-audit.md`（FA-G5 第二刀 / FA-A2 / FA-T1 都需要 2-D 截面进评分）。
权威：手册 §4.1.1-2（操作流程在**大气截面**上做光线追踪 + 逐列气溶胶 + 边界平移）。
Branch: `codex/62-sunward-section-plumbing`（off main）。

## 为什么（审计发现）

P1 余项 **FA-G5 第二刀（光追接评分）/ FA-A2（逐列路径气溶胶）/ FA-T1（边界平移到日落）** 都卡在同一处缺失基础设施：
**评分链路里只有 1-D `sunward_profile`（沿程三档云量+AOD+风），没有 2-D `SunwardCrossSection`**（距离×高度场 + 逐列诊断云层）。
`build_cross_section`（cross_section.py）能装配 2-D 截面，但只被绘图消费、从不进评分；
`trace_ray_clearance`（ray_path.py, FA-G5）已能在截面上追踪光线，但拿不到截面。

## 现有积木（全部已存在，只缺编排 + 接线）

```
(lat, lon, time)
  → build_sunward_path(...)                      # spatial.py：沿日落方位的采样路径(含格点/高程)
  → fetch_cube(bbox 覆盖整条路径, valid_time)     # gfs.py：一次读，裁到 bbox
  → 每个采样点：cube.profile_at → normalize → diagnose_clouds   # profiles/normalize/clouds
  → build_cross_section(path, profiles, layers)  # cross_section.py：装配 2-D 截面
  → trace_ray_clearance(xsec, h_eff)             # ray_path.py (FA-G5)：光追挡光判定
```

## 设计决定（请 Nick 过目）

1. **编排与 I/O 分离**（与 cloud_motion/cross_section 同范式）：
   - **新 `predictor/sunward_section.py`** 的 `assemble_sunward_cross_section(path, cube, *, heights_m=None) -> SunwardCrossSection`：
     **纯函数**，吃一个**已取得的 `AtmosphericCube`**（注入，无网络），逐采样 `profile_at→normalize→diagnose_clouds`，调 `build_cross_section`。→ 可用合成 cube 离线 TDD。
   - **薄 I/O 编排** `sunward_cross_section_for_point(source, lat, lon, time, ...)`：算 path 的 bbox、`source.fetch_cube` 一次、调 assemble。**标 `@pytest.mark.integration`**（真实 GFS），离线不跑。
2. **两刀切分**（保持每个 PR 聚焦、可独立审）：
   - **本 PR（第一刀）**：只交付**离线可测的装配** `assemble_sunward_cross_section` + 集成编排 `sunward_cross_section_for_point`。**不改评分**。
   - **第二刀（紧随 PR）= FA-G5 第二刀**：`Features` 加可选 `ray_clearance`（或截面句柄）；`SunwardIlluminationGate` 在有截面时用 `trace_ray_clearance` 出分（clear→1.0；blocked→按首遮挡位置/到达比例分级），**无截面时回退现标量**（overview 不受影响）。详细单点路径负责建截面→trace→喂进 `derive/score_snapshot`。
3. **bbox 约定**：`fetch_cube` 用 `(lat_min,lat_max,lon_min,lon_max)`（见 .agent-progress GOTCHA，勿与 CN_BBOX 的 (S,W,N,E) 混）。path 采样点经纬度取 min/max + 余量得 bbox。
4. **高度轴**：默认 `even_heights()`（0–15km, 31 层, 500m）；与 `diagnose_clouds` 的层诊断独立（截面场用于绘图/插值，光追用每列 `cloud_layers`）。

## 测试（TDD：先红后绿；离线合成 cube）

`test_sunward_section.py`（新）：
- **装配**：构造合成 `AtmosphericCube`（已知温湿廓线 + 一处液态云）+ 一条 `SunwardPath` → `assemble_sunward_cross_section` → 返回 `SunwardCrossSection`，`distances_km` 与 path 对齐、`cloud_layers` 每列由 `diagnose_clouds` 得到、含云列非空、晴列空。
- **域外采样**：path 含 `in_domain=False` 的点 → 该列 profile=None、被 mask（复用 build_cross_section 的既有语义）。
- **端到端（离线）**：合成 cube 里沿光路低空植一层不透明云 → 装配出的截面喂 `trace_ray_clearance` → `clear=False`；移除 → `clear=True`。（证明 plumbing 真的把 FA-G5 串起来了。）
- **集成（手动）**：`sunward_cross_section_for_point` 用真实 GFS 标 integration，`-m integration` 手动验。
- **回归**：全量 `pytest -m "not integration"` 全绿；本 PR 不碰评分 → grid 1e-9 / metamorphic / 现有 gate 全不受影响。

## 后续（本 plumbing 解锁）

- **FA-G5 第二刀**：gate 用 `trace_ray_clearance`（决定 2）。
- **FA-A2**：在 `trace_ray_clearance` 里逐列用该列 AOD 经 P0 `equivalent_*` 算逐列等效地表（抬高 graze），替全程 AOD 均值——截面已带每列数据。
- **FA-T1**：用 path 的逐层风把截面/边界平移 `Δt=日落−valid_time`；valid_time 来自 cube。
- 这也正是 #62「坐标→本地精细产品 = 跑完整单点物理」的核心：本地按完整单点物理（含截面光追）出图，而非加密插值。

## 限制

- 每点一条廓线 = GFS 0.25°（~25km）水平分辨率；截面采样距离网格（`DEFAULT_SUNWARD_DISTANCES_KM`）较粗，顶点附近低空可加密 `even_distances`。
- 单截面、单日落方位（手册典型云况，中低纬适用）。
- 真实 GFS cube 读取较重；bbox 覆盖 800km 路径 → 一次 cube 读，按需缓存（复用 gfs.py 既有缓存）。
