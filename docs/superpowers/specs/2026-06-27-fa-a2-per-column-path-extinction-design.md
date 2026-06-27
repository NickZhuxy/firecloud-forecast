# FA-A2 — 逐列路径消光接入截面光追 — 设计

Parent: Epic #54 / #57（单点物理拟真）。承 FA-G5 光追载体（PR #66/#69/#71）。
物理推导：[research/theory/fa-a2-path-extinction.md](../../../research/theory/fa-a2-path-extinction.md)。
权威：手册 §1.3.1–4 / §4.1.1 / §2.4.2。
Branch: `codex/57-fa-a2-path-extinction`（off main）。

## 目标

把 2-D 详细单点光追里的"全程 AOD 均值 → 单个等效底"换成**逐列路径消光**：每列按其柱 AOD
算等效不透明地表 `h_x(AODⱼ)`，抛物线在该列若 `h_ray(lⱼ) ≤ h_x` 则消光否决；观察者列 AOD
单独定顶点。化解均值掩盖上游近地浓气溶胶的翻车点（手册 §1.3.4）。

## 改动面（自下而上，先载体后消费 = 与目标"先给 cross-section 加 per-column AOD"一致）

1. **载体** [cross_section.py](../../../predictor/cross_section.py)
   - `SunwardCrossSection` 增字段 `aerosol_optical_depth_per_column: list[float | None] | None = None`
     （每列一个柱 AOD，与 `distances_km` 对齐；`None` = 未提供）。
   - `build_cross_section(..., *, aod_per_column: list[float | None] | None = None)`：长度须与
     samples 对齐（否则 `ValueError`），原样挂到截面；缺省 `None`。
2. **装配** [sunward_section.py](../../../predictor/sunward_section.py)
   - `assemble_sunward_cross_section(..., *, aod_fn=None)`：注入式 `aod_fn(lat, lon)->float|None`
     （无网络，类比 `elevation_fn`）；对每个 in-domain 采样取 `aod_fn(lat,lon)`，域外列 `None`，
     传入 `build_cross_section(aod_per_column=…)`。`aod_fn=None` ⟹ 不填（全 None）。
3. **物理（消费）** [ray_path.py](../../../predictor/ray_path.py)
   - 新纯函数 `aerosol_ground_height_m(aod, scale_height_m=2000) -> float`：`h_x=H·ln(β₀/β_x)`，
     `β₀=AOD/H`；`β₀≤β_x` 或 AOD 缺/≤0 ⟹ 0。`equivalent_cloud_base_from_aod_m` 重构为复用它。
   - `trace_ray_clearance` 读 `cross_section.aerosol_optical_depth_per_column`：先取观察者列
     （`distance<min_path_distance_km`）的 `h_x(AOD₀)` 作掠射基准；对每列在既有云层遮挡判定**之外**
     判气溶胶**超出量** `Δ=h_x(AODⱼ)−h_x(AOD₀)`——`Δ>0 且 h_ray≤Δ` ⟹ `clear=False`、
     `blocked_layer=None`、`blocked_height_m=h_ray`。**不用绝对地板**（否则均匀薄霾在顶点必否决，
     见 theory §2/§4）。云块/气溶胶块取沿程**先**遇到者。
4. **接线** [features.py](../../../predictor/features.py) 2-D 光追入口（仅 `sunward_cross_section`
   分支，~L305）：顶点等效底改用**观察者列**（截面第 0 列）AOD；该 AOD 缺失时回退现
   `sunward_aod_mean`，再缺回退 None（= 原始云底）。`trace_ray_clearance` 拿到逐列 AOD 后自动
   做上游消光。**不动** 1-D `SunwardIlluminationGate`（rules.py:216 几何入口）与国家级路径。

## 不在本 PR

- FA-A1 的 `H` 扫描与本因子合流（此处 `H=2km` 点估计）。
- FA-A3 本地观感气溶胶进亮度通道。
- 把 `aod_fn` 真正接 Open-Meteo air-quality 的生产编排出图（属 #62 产品线；本 PR 编排函数加
  `aod_fn` 形参并标 integration，离线不跑真实网络）。

## 测试（TDD：先红后绿；离线合成截面）

新增/扩充：
- `test_ray_path.py`：`aerosol_ground_height_m` 单元（洁净→0、浓→正、单调、AOD None/0→0）；
  逐列气溶胶否决存在性、移除→clear、单调性、洁净均匀退化、云块 vs 气溶胶块先到者、
  逐列 AOD 缺省（None）→与现状逐位一致（回归锁）。
- `test_cross_section.py`：`build_cross_section(aod_per_column=…)` 填充 + 长度校验 + 缺省 None。
- `test_sunward_section.py`：`assemble_sunward_cross_section(aod_fn=…)` 逐列填充、域外列 None、
  `aod_fn=None` 缺省。
- `test_metamorphic_physics.py`：上游路径 AOD 上升 → `sunward_illumination` 单调不增（composite）。
- `test_geometry`/回归：全量 `-m "not integration"` 绿；grid 1e-9 / 现有 gate / 标量回退不变。

## 安全 / 兼容

纯增量：新字段默认 `None`、新形参默认 None/不填。逐列 AOD 缺省时 `trace_ray_clearance`
与 features 接线逐位回退到现行为（既有 ray_path/section 测试不改语义）。`_xsec` 测试 helper
因新字段有默认值无需改构造。
