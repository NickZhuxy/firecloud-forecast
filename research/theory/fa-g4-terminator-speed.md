---
stage: claude-draft
factor: FA-G4
parent: single-point-fidelity-audit.md (§3.A FA-G4)
authority: 人工火烧云预报速成（长三角适用）.pdf 附录 v 表
decision: owner (Nick) 2026-06-27 — 时长精度不重要，取两边统计中点出大致时长
---

# FA-G4 — 日落终结线线速度 v（统计折中，非精确定义）

> Owner 决策（2026-06-27）：**时长预报精度不重要**；不逆向手册确切公式、不切 astral，
> 取两个候选定义的**统计中点**给一个"大致时长"。本笔记记录依据与折中。

## 1. v 用在哪、影响什么

火烧云时长 ≈ `2L/v`（`L=√(2R·h_eff)`，v=日落终结线沿日落方向扫地速度，km/min）。
v 进 `characteristic_duration_min` → `LayerContribution.duration_min`（每层"亮多久"，
`illumination.py`）。**关键边界：v 与时长不进概率/条件指数**——`rules.py` 只用
`equivalent_cloud_base_from_aod_m` 与 `max_penetration_km`，九条规则无一用 v 或时长。
故 FA-G4 只影响**次要的、信息性的时长输出**，不影响"会不会出火烧云"的主判断
（审计据此定 P1 / 影响=中 / 成本=低）。

## 2. 三方实测：手册 v 比两个几何候选都低，且无法复现

| 城市 | 手册附录 | 现 cos-lat（`R·0.25°/min·cos lat`）| astral 实算 `v=R·dα/dt` |
|---|---|---|---|
| 深圳 22.5°N | **21** | 25.7 | 30–33 |
| 上海 31°N | **20** | 23.8 | 28–31 |
| 伊春 47.7°N | **18** | 18.7 | 22–26 |

- 手册值**三者最低**，且比纯几何终结线地面速度低 ~15–35%——其定义（是否带方位/轨迹倾角投影、
  云高处速度、抑或经验值）手册未给闭式，本项目**无法从第一性原理复现**。
- 审计原建议"改 astral dα/dt"**反而最高、离手册最远**（会更差）。
- cos-lat 在高纬（伊春）几乎正好，仅低纬（深圳）偏高 ~22%。
- 注：手册 v 随纬度**比 cos-lat 平**（18–21 全国窄带，中心 ~20）。

## 3. 决策：统计中点（不追精度）

`v_repr(lat) = ½·(sunset_speed_km_min(lat) + 20)`：

- `sunset_speed_km_min(lat)` = cos-lat 物理终结线速度（~18–26，低纬偏高端）。
- `20 km/min` = 手册附录全国中心代表值（18–21）。
- 取均值：低纬把 cos-lat 偏高的值拉回手册附近（深圳 22.9 / 上海 21.9，对手册 21/20），
  高纬两者本就吻合（伊春 19.4，对 18）。即 cos-lat 与 astral 物理高端、手册低端之间的**统计中点**
  （巧的是现 cos-lat 本就≈两候选中点）。
- 适用域：中低纬（中国主体 <54°N）。极高纬 cos-lat→0 时 flat-20 会偏高，但超出适用域且
  时长非主输出，不处理。

**不确定带（保留给将来需要精度时）**：手册低端 ~20 ↔ 物理高端 ~25–33；真定义待读手册附录推导
或经验校准（owner 当前不需要）。

## 4. 验证设计

1. `representative_terminator_speed_km_min(lat) == ½(sunset_speed_km_min(lat)+20)`（闭式）。
2. 低纬（cos-lat>20）：`20 < v_repr < sunset_speed_km_min`（夹在手册与物理之间）。
3. 随 |lat| 单调不增（终结线越高纬越慢 → 时长越长）。
4. `characteristic_duration_min` 改用 v_repr：时长 = `2L/v_repr`；既有 sqrt 标度/高基更久/
   高纬更久不变量保持。
5. 回归：全量 `-m "not integration"` 绿；概率/gate/grid 不受影响（v 不进打分）。

## 5. 对预测规则的启示

- [geometry.py](../../predictor/geometry.py)：新增 `representative_terminator_speed_km_min`；
  `characteristic_duration_min` 改用之。`sunset_speed_km_min`（纯 cos-lat 物理）保留（被
  `compute_geometry`/`overhead_firecloud_window` 引用，未接产品）。
- 概率链路不变。

参考：手册附录 v 表；[solar-geometry.md](solar-geometry.md) §太阳运动速率（dα/dt 随纬度/季节/
方位）；[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.A FA-G4。
