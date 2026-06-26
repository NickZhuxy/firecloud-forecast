# 单点物理拟真增强 — P0 批：火烧云三角时长 + 视线高度角 + 气溶胶 H 扫描 — 设计 (#57 P0)

Parent epic: #54 — 单点物理拟真 → 智能全国化
依据：[`research/theory/single-point-fidelity-audit.md`](../../research/theory/single-point-fidelity-audit.md)（Spike #56）的 owner 定稿优先级。
权威目标模型：`research/人工火烧云预报速成（长三角适用）.pdf`（手册），引用记作「手册 §x.y」。
Branch: `codex/57-singlepoint-p0-geometry-aerosol`

## 范围（P0 首批）

本 PR 只做审计 backlog 里 owner 定稿的 **P0 首批四项**，全部落在 `predictor/geometry.py`（纯解析、无 I/O）+ 其消费方：

- **FA-A1** 气溶胶高度衰减常数 `H` 扫描 → 等效云底**区间**（替代单一固定 `H=2000m` 点估计）。
- **FA-G1** 用**火烧云三角**（手册 §1.2.2）+ 观察者位置算**本地头顶持续时间**，替代 `2L/v` 三角总宽度。
- **FA-G2** 视线 **5° 天空时长延伸**（手册 §1.2.4 / §4.1.1）。
- **FA-G3** 日落方向云边界的**视线高度角**输出（手册 §1.2.4）。

**不在本 PR**（按审计的依赖与优先级）：FA-G4（日落线速度改 astral 实算——签名牵连大，P1 单独做；本 PR 把 `v` 作为**显式参数**传入，与速度模型解耦）；FA-G5 光追、FA-A2 路径积分等 P1+。

## 关键设计决定

1. **全部新增、不改既有**。`max_penetration_km`、`equivalent_cloud_base_m`、`equivalent_cloud_base_from_aod_m`、`characteristic_duration_min`、`sunset_speed_km_min` 的现有签名与数值**保持不变**——`grid_score` 的 `1e-9` 标量等价与现有 30 条 geometry 测试不受影响（见 `.agent-progress.md` GOTCHAS）。新功能是新函数 + `compute_geometry`/`GeometryResult` 的**附加**字段。
2. **`v` 作为参数**。新的时长函数都接收 `sunset_speed_km_min: float`（km/min）作为显式入参，使 FA-G1/G2/G3 可独立用手册算例做 golden test，并把"`v` 怎么算得准"留给 FA-G4（P1）。`compute_geometry` 暂用现有 `sunset_speed_km_min(lat)`（cos-lat）填入。
3. **等效云底 vs 原始云底分工**（来自手册算例）：
   - **头顶时长** 用**等效云底** `h_eff`（气溶胶等效地表修正后）——因为它关乎"光能否照到云底"。
   - **5° 视线延伸** 与 **边界高度角** 用**原始云底** `h_CB`——因为它们关乎"云在观察者天空中的真实仰角"。
   - 手册伊春算例正是如此：头顶用 `h_eff∈[4.65,5.9]km`，5° 延伸用原始 `7.291km`。
4. **H 非单调**：`h_x(H)` 对 `H` 非单调（手册明示"最好多算几个数字"），所以 FA-A1 在 `H∈[0.5,4]km` 上**采样取 min/max**，不能只看端点。

## 物理与公式（手册 §1.2.2 / §1.2.4 / §1.3.3，已对算例验证）

记 `R = 6371 km`，`h` 用 km，`v` 用 km/min，`D` = 观察者到日落方向云边界的水平距离 km。

### 火烧云三角（§1.2.2）—— 远/近边界
```
h_f(l,t) = (l − vt)² / (2R)                          # 远边界（地球遮挡，掠地）
h_n(l,t) = (l − vt)² / (2R) + h_CB − (vt)² / (2R)     # 近边界（云边界遮挡）
代入 h = h_CB：
  l_f(t) = −√(2R·h_CB) + v t
  l_n(t) = 2 v t (t≤0); 0 (t>0)
时间域： −√(2R·h_CB)/v ≤ t ≤ √(2R·h_CB)/v   （原点 = 云边界地面点，t=0 = 云边界处日落）
```

### FA-G1 本地头顶时长（相对**观察者本地日落**）
观察者位于离云边界 `D` 处（`l₀=−D`）。由 `l_f(t) ≤ l₀ ≤ l_n(t)` 解得，换算到观察者本地日落为 0：
```
start_min    = D / (2v)
end_min      = √(2R·h_eff) / v
duration_min = end − start = √(2R·h_eff)/v − D/(2v) = (2√(2R·h_eff) − D) / (2v)
存在条件： D < 2√(2R·h_eff) = max_penetration_km(h_eff)   （否则无头顶火烧云 → None）
```
**Golden（深圳 §4.1.1）**：`h_eff=2km, D=200, v=21` → start=4.76, end=7.60, **duration=2.84 min**（手册 2.8 / 起 4.8 / 终 7.6）。

### FA-G3 视线高度角（§1.2.4，含曲率）
```
θ(l, h) = h/l − l/(2R)        # 弧度；正=地平线上，负=地平线下不可见
```
**Golden**：深圳 `D=200,h=2` → −0.327°（手册 −0.32°）；伊春 `D=166,h=7.219` → 1.745°（1.75°）；青岛 `D=200,h=9.2` → 1.736°（1.74°）。

### FA-G2 5° 天空视线延伸（§1.2.4 / §4.1.1）
手册取"5° 高度角天空火烧云结束"为视野内彻底结束，延伸距离按**忽略曲率**的简式（与手册算例一致），用**原始云底**：
```
ext_distance_km = h_CB / tan(θ_min),  θ_min = 5°
ext_min         = ext_distance_km / v
total_duration  = overhead_duration(h_eff) + ext_min(h_CB)
```
**Golden**：深圳 `h=2km` → 2/tan5°=22.86km, ext=1.09min, **total=3.93 min**（手册 3.9）；伊春 `h=7.291km` → 83.3km, ext=4.63min, total≈13.5–15.2 min（手册 13.5–15.2）。

### FA-A1 气溶胶等效云底区间（§1.3.3 / §4.1.1 表 4.1）
```
β₀(H) = AOD / H            # H = 气溶胶消光系数高度衰减常数 (km)
h_x(H) = H · ln(β₀/βx),  βx = 0.02 km⁻¹   （β₀ ≤ βx 时 h_x=0）
h_eff(H) = max(0, h_CB − h_x(H))
在 H ∈ [0.5, 4.0] km 上采样 → 取 h_eff 的 (min, max) 与 h_x 的 (min, max)；h_x 对 H 非单调。
```
**Golden（表 4.1，AOD=0.15）**：`h_x(H)` 在 `H={0.5,1,1.5,2,2.5,3,3.5,4}` = `{1.35,2.01,2.41,2.64,2.74,2.75,2.66,2.51}` km；峰值 ≈2.75km 落在 `H≈3`（**非单调**）。现有 `equivalent_cloud_base_from_aod_m`（固定 H=2km）= 2.64km 行，与表一致——本项只是把它扩成扫描区间。

## 模块与数据模型

### `predictor/geometry.py`（新增，纯函数）
```python
def viewing_elevation_deg(distance_km: float, height_m: float) -> float:
    """目标视线高度角(度)，含地球曲率： θ = h/l − l/(2R)。手册 §1.2.4。"""

@dataclass
class OverheadWindow:
    start_min: float       # 相对观察者本地日落（晚霞为正=日落后）
    end_min: float
    duration_min: float

def overhead_firecloud_window(
    boundary_km: float, cloud_base_eff_m: float, sunset_speed_km_min: float,
) -> OverheadWindow | None:
    """火烧云三角给出的本地头顶时段；D ≥ 最大深入距离 → None。手册 §1.2.2。"""

def viewing_extension_min(
    cloud_base_m: float, sunset_speed_km_min: float, min_elev_deg: float = 5.0,
) -> float:
    """视野内火烧云延伸到 min_elev_deg 天空的额外时长 (h/tanθ)/v。手册 §1.2.4。"""

def total_observed_duration_min(
    boundary_km: float, cloud_base_eff_m: float, cloud_base_raw_m: float,
    sunset_speed_km_min: float, min_elev_deg: float = 5.0,
) -> float | None:
    """头顶时长(用 h_eff) + 5° 视线延伸(用 h_raw)。手册 §4.1.1。"""

@dataclass
class AerosolGroundRange:
    h_x_min_m: float; h_x_max_m: float            # 等效地表高度区间
    eff_base_min_m: float; eff_base_max_m: float  # 等效云底区间 (floored 0)
    scale_height_at_max_h_x_km: float             # 取到 h_x 峰值的 H（非单调峰）

def equivalent_cloud_base_range_from_aod_m(
    cloud_base_m: float, aerosol_optical_depth: float | None,
    scale_heights_km: tuple[float, ...] = (0.5,1.0,1.5,2.0,2.5,3.0,3.5,4.0),
) -> AerosolGroundRange | None:
    """在 H 网格上扫描等效地表高度(非单调)，返回等效云底区间。手册 §1.3.3 / 表 4.1。"""
```

### `compute_geometry` / `GeometryResult`（附加字段，向后兼容）
新增可选入参 `boundary_km`、`cloud_base_raw_m`；`GeometryResult` 增 `overhead_window`、`total_duration_min`、`boundary_elevation_deg`、`aerosol_ground_range`（无相应输入时为 None）。既有字段与默认行为不变。

## 测试（TDD：先红后绿；离线、纯解析）

每项先写失败测试、`pytest` 看其按预期失败、再写最小实现。新增到 `predictor/tests/test_geometry.py`。

- **FA-G1**：深圳 `overhead_firecloud_window(200, 2000, 21)` → duration≈2.84、start≈4.76、end≈7.60（tol 0.05）；伊春 `(166, 4650, 18)`→8.91、`(166, 5900, 18)`→10.62；`D ≥ 2√(2Rh)` → None；metamorphic：`D` 越大 duration 越短、`h_eff` 越大 duration 越长。
- **FA-G3**：`viewing_elevation_deg(200, 2000)`≈−0.327；`(166, 7219)`≈1.745；`(200, 9200)`≈1.736；性质：远→角小、高→角大；曲率项使大 `D` 角可为负。
- **FA-G2**：深圳 `viewing_extension_min(2000, 21)`≈1.09；`total_observed_duration_min(200, 2000, 2000, 21)`≈3.93；伊春 `total(166, 4650, 7291, 18)`≈13.5、`(166, 5900, 7291, 18)`≈15.2。
- **FA-A1**：`equivalent_cloud_base_range_from_aod_m(9200, 0.15)` → `h_x_max≈2750m`（tol 30m）、`scale_height_at_max_h_x_km≈3.0`、`h_x_min≈1350m`、`eff_base_*` = 9200−h_x；非单调（峰在内部不在端点）；`AOD=None`→None；与现有固定-H 函数在 H=2km 行一致。
- **compute_geometry**：传 `boundary_km`/`cloud_base_raw_m`/`aerosol_optical_depth` → 新字段被填充且数值与上面一致；不传 → 新字段 None、旧字段不变。
- **回归**：全量 `pytest -m "not integration"` 全绿；`test_grid_score`（1e-9 等价）与 `test_metamorphic_physics` 不受影响。

## 限制 / 后续

- `v` 仍由现有 cos-lat `sunset_speed_km_min(lat)` 提供 → **FA-G4（P1）** 改 astral 实算后，深圳/伊春的 `v` 才会自动接近手册附录值（21/18）；本 PR 的 golden test 直接传手册 `v`，与速度模型解耦。
- 5° 延伸用忽略曲率的 `h/tanθ`（匹配手册算例）；曲率修正版留作可选精化。
- 头顶时段假设单层、平坦地形、单一日落方位（手册典型云况）；地形遮蔽 FA-G6、路径光追 FA-G5、边界平移 FA-T1 为后续 story。
- 本 PR 暂不改 `SunwardIlluminationGate` 的通过/不通过语义；等效云底**区间**先作为诊断 enrichment 输出，"用区间表达有/无火烧云的不确定带"接入评分留作紧随的 follow-up。
