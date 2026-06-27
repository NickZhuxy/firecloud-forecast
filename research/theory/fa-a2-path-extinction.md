---
stage: claude-draft
factor: FA-A2
parent: single-point-fidelity-audit.md (§3.C FA-A2)
authority: 人工火烧云预报速成（长三角适用）.pdf §1.3.1–4 / §4.1.1 / §2.4.2
---

# FA-A2 — 沿光线逐列路径消光（替代沿程 AOD 均值）

> 事实层与推导 Claude 起草；判断层（默认参数、退化阈值）待 Nick 复核。
> 承 FA-G5（[ray_path.py](../../predictor/ray_path.py) 抛物线-截面光追）这一公共载体落地。

## 1. 问题：均值掩盖上游近地浓气溶胶

当前实现把整条日落路径的柱 AOD 取**简单平均** `sunward_aod_mean`
（[features.py](../../predictor/features.py) `analyze_sunward_profile`），再用这一个标量经
`equivalent_cloud_base_from_aod_m` 压低观察者云底、定一个等效地表
（[features.py](../../predictor/features.py) 2-D 光追入口、[rules.py](../../predictor/rules.py)
`SunwardIlluminationGate` 1-D 几何入口都如此）。

手册 §1.3.4 / §4.1.1 的物理要求是另一回事：

> "气溶胶要少在**阳光传播路径上**，光在本地或者地面附近少是不够的。"

翻车清单又点名：

> "光线上游大气中层/近地气溶胶消光系数比预计的高。"

掠射光线的几何（FA-G5）决定了它**最贴近地面的一段恰在抛物线顶点附近**——往往在观察者上游
数百公里处。如果那里有一团近地浓气溶胶（沙尘、霾、生物质燃烧烟羽），柱 AOD 在那一列很高，
但被沿程几百公里的洁净列**平均稀释**后，均值看不出问题。均值是错误的聚合算子：消光是
**沿程路径上的逐点门槛**，不是路径平均。

## 2. 物理模型：指数廓线 → 逐列等效不透明地表

沿用项目既有、与手册 §1.3.3 一致的气溶胶垂直廓线（[geometry.py](../../predictor/geometry.py)
`equivalent_cloud_base_from_aod_m`）：

- 消光系数随高度指数衰减：`β(z) = β₀·exp(−z/H)`，`H` 为气溶胶标高（默认 2 km）。
- 柱光学厚度即廓线积分：`AOD = ∫₀^∞ β dz = β₀·H` ⟹ `β₀ = AOD/H`。
- "等效不透明地表"取消光降到能见度阈值 `β_x = 0.02 km⁻¹`（2% 对比度，Vis = −ln0.02/β）
  的高度：

  ```
  h_x(AOD) = H · ln(β₀ / β_x) = H · ln(AOD / (H·β_x))   (β₀ > β_x 时；否则 0)
  ```

  `z < h_x` 的近地层对掠射阳光"有效不透光"。

FA-A2 的关键改动：**把这套等效地表从"全程一个"改成"逐列一个"，且以观察者列为基准判
上游超出量**。第 `j` 列有自己的柱 AOD `AODⱼ`、自己的等效地表 `h_x(AODⱼ)`。

**为什么不能用绝对地板。** 抛物线在顶点降到 `h_ray=0`（顶点处掠地）。若判据是"`h_ray(lⱼ)
≤ h_x(AODⱼ)` 即否决"（绝对地板），则只要顶点附近那一列 `h_x>0`（即 `AODⱼ > H·β_x ≈ 0.04`，
极洁净空气！）就否决——一条均匀薄霾（AOD~0.1，长三角常态）的路径会被几乎确定性地否决，
gate 失去区分力。这是把**垂直**能见度阈值 `β_x` 当成**掠射**路径地板的几何错配。

**正确判据：以观察者列为掠射基准，判上游超出量。** 观察者自身的近地霾 `h_x(AOD₀)` 已通过
等效底（`equivalent_cloud_base_from_aod_m`）压低 `h_eff`、把顶点拉近——所以 `h_ray` 是**相对
观察者等效地表测量的**（顶点 `z=0` ↔ 真实高度 `h_x(AOD₀)`）。上游第 `j` 列的近地不透明层
`[0, h_x(AODⱼ)]` 在抛物线坐标系里是 `[−h_x(AOD₀), h_x(AODⱼ)−h_x(AOD₀)]`。故判据：

> 设超出量 `Δⱼ = h_x(AODⱼ) − h_x(AOD₀)`。若 `Δⱼ > 0 且 h_ray(lⱼ) ≤ Δⱼ`，光线在第 `j` 列穿过
> **比观察者更高的**近地不透明气溶胶 → 该列消光否决。

这正是手册翻车清单的措辞——"光线上游近地气溶胶消光**比预计的高**"（比本地高）。与逐列云层
遮挡判据同构（云挡 `[base, top]`，气溶胶挡观察者基准之上的超出层），并入同一光追循环 OR 叠加。

## 3. 两种气溶胶角色的分离（本地 vs 上游）

手册区分两条物理通道（亦见 FA-A3）：

1. **本地近地气溶胶** → 压低观察者**自身**画布的等效云底（光要先穿过观察者头顶的近地霾才能
   照亮画布）。这进入抛物线**顶点位置 + 掠射基准**：用观察者那一列（截面第 0 列）的 AOD 算
   等效底 `h_x(AOD₀)`，而非全程均值。
2. **上游路径气溶胶** → 沿抛物线判**超出观察者基准**的消光否决（§2 的 `Δⱼ`）。观察者自身列
   在光追里本就被 `min_path_distance_km` 跳过（画布不自遮），所以两条通道**不重复计数**：
   顶点/基准只吃第 0 列，逐列否决只吃第 1…n 列且只看相对第 0 列的超出量。

这恰好替换掉"全程均值同时进顶点和逐列"的混淆——均值被彻底退役（在 2-D 详细路径里）。
**均匀气溶胶不自我否决**（`Δⱼ=0`），它的影响完整体现在顶点（等效底缩短到达距离）；
只有上游**比本地更浓**的羽才另外否决。1-D 国家级/overview 路径无逐列截面，保留
`sunward_aod_mean` 均值近似不变（见 §6）。

## 4. 化解"平地板挡掉一切光"的担忧

[ray_path.py](../../predictor/ray_path.py) docstring 明确警告：抛物线在顶点降到 0，
若设一个**固定/绝对**高度的不透明地板（`h_ray ≤ h_x(AODⱼ)`），则只要顶点附近一列
`h_x>0`（即 `AODⱼ>0.04`）就否决——一条均匀薄霾路径会被几乎确定性否决（错误）。
**绝对地板版本是早期写法，已被否决**（见 §2"为什么不能用绝对地板"）。

**超出量判据 `Δⱼ = h_x(AODⱼ) − h_x(AOD₀)` 天然化解**：

- **均匀气溶胶**（含均匀浓霾）：`h_x(AODⱼ)=h_x(AOD₀)` ⟹ `Δⱼ=0` ⟹ **不否决**。它的减光已
  完整计入观察者等效底（到达距离缩短），不重复在光追里再否决一次。
- **上游比本地更浓**：`Δⱼ>0`，且抛物线在该列压低（接近顶点）时被挡——正是手册物理：
  掠射光最长近地段撞进**比本地更浓**的上游气溶胶就该熄灭。
- **上游比本地更洁净**：`Δⱼ<0` ⟹ 不否决（光线已掠过该列更低的等效地表之上）。

即否决只在**上游气溶胶超出本地基准**时触发，均匀场永不自我否决，故不会一刀切。

## 5. 假设与适用域

- 指数廓线 `β(z)=β₀e^{−z/H}`、单一标高 `H`：与手册 §1.3.3 / 既有 P0 一致；真实廓线分层
  （边界层 vs 自由对流层）时偏保守。`H` 仍是首要不确定性（FA-A1 已用 H 扫描出区间；FA-A2
  此处取点估计 `H=2km`，扫描留待与 FA-A1 合流）。
- 柱 AOD 作为该列消光的代理：忽略波长依赖（全程 550nm，FA-S2 未做）；忽略 RH 吸湿增长
  （FA-A4）。
- `β_x = 0.02 km⁻¹` 沿用 §5.4 能见度-消光阈值约定，与 `equivalent_cloud_base_*` 同源。
  **判断层（待 Nick 复核）**：`β_x` 原为**垂直**能见度对比度阈值；此处用作掠射路径判据。
  超出量形式（相对观察者 `h_x`）已规避"绝对地板把均匀薄霾全否决"的几何错配，使阈值只决定
  "上游比本地浓多少才算挡光"。更严格的做法是沿抛物线**积分** `τ=∫β dl`（均匀场 `τ≈141·AOD`，
  掠射切向气柱 ~140× 垂直柱）按透过率阈值判——是 FA-A2 的可选升级，留待与 FA-A1 的 `H` 扫描
  及 FA-A3 的颜色通道合流时一并标定。
- 水平分辨率受逐列采样网格限制（GFS 0.25°，`DETAIL_SUNWARD_DISTANCES_KM` 25km）；
  比顶点宽度细，能分辨数十公里尺度的气溶胶羽。
- **退化行为**：逐列 AOD 全缺（无气溶胶数据源注入）⟹ 全列 `h_x` 无定义 ⟹ 不产生任何气溶胶
  否决，顶点退回原 `equivalent_cloud_base_from_aod_m(观察者AOD or None)` ⟹ 与现状逐位一致，
  **纯增量、可优雅退化**。

## 6. 数据来源（逐列 AOD 从哪来）

GFS `AtmosphericCube` 不含气溶胶（`PROFILE_VARS` 无 AOD）。逐列柱 AOD 由**注入式可调用**
`aod_fn(lat, lon) -> float | None` 提供（与 `elevation_fn` 同范式，几何/装配保持无网络、可离线
TDD）。生产编排（`sunward_cross_section_for_point` / `score_point_with_sunward_section`，标
`integration`）把它接到 Open-Meteo air-quality 的逐坐标 AOD（已是 1-D 路径的数据源，
[fetch.py](../../predictor/fetch.py)）。离线测试注入合成 `aod_fn`。

## 7. 验证设计（先写失败测试；metamorphic / 性质不变量）

无解析地面真值，按项目惯例钉**方向性物理律**（见 [test_metamorphic_physics.py](../../predictor/tests/test_metamorphic_physics.py)）：

1. **上游超出否决存在性**：晴空截面（无云）+ 观察者列洁净 + 上游一列植入浓 AOD（`Δⱼ>h_ray`）
   ⟹ `trace_ray_clearance.clear == False`、`blocked_layer is None`（气溶胶块）；移除 ⟹ `clear`。
   （`test_ray_path.py::test_dense_upstream_aerosol_blocks_clear_sky_ray` 等）
2. **均匀场不否决（核心修正不变量）**：全列同浓 AOD（含 `h_x>0` 的浓霾）⟹ `Δⱼ=0` ⟹ `clear`。
   防止绝对地板的顶点过度否决。（`test_uniform_aerosol_does_not_block`）
3. **上游更洁净不否决**：观察者浓、上游更洁净 ⟹ `Δⱼ<0` ⟹ `clear`。
   （`test_upstream_cleaner_than_hazy_observer_does_not_block`）
4. **本地 vs 上游分离 + 不重复计数**：观察者列浓 AOD 压低等效底（改变顶点/到达，
   `test_derive_observer_column_aod_lowers_effective_base_and_blocks`）但不自遮；上游超出量另判否决。
5. **单调性**：增大上游列 AOD，光线清晰度非增；composite `sunward_illumination`/概率随上游 AOD
   上升单调不增（端到端真链路 `test_more_upstream_aerosol_never_raises_composite_probability`）。
6. **载体管线**：`build_cross_section(aod_per_column=…)`、`assemble_sunward_cross_section(aod_fn=…)`
   正确填充 `aerosol_optical_depth_per_column`；缺省全 None ⟹ 与现状逐位一致（回归锁）。
7. **回归**：全量 `pytest -m "not integration"` 全绿；不碰 1-D/国家级/标量 gate 与 grid 1e-9。

## 8. 对预测规则的启示

- [ray_path.py](../../predictor/ray_path.py) `trace_ray_clearance` 增逐列气溶胶否决
  （读截面 `aerosol_optical_depth_per_column`，以观察者列为基准按 §2 超出量判据 OR 进既有云层遮挡）。
- [cross_section.py](../../predictor/cross_section.py) `SunwardCrossSection` 增
  `aerosol_optical_depth_per_column`，`build_cross_section` 增可选 `aod_per_column`。
- [sunward_section.py](../../predictor/sunward_section.py) `assemble_sunward_cross_section`
  增注入式 `aod_fn`。
- [features.py](../../predictor/features.py) 2-D 光追入口：顶点等效底改用**观察者列** AOD
  （截面第 0 列）而非全程均值；上游消光交给逐列光追。1-D `SunwardIlluminationGate`
  几何入口与国家级路径不变。

参考：手册 §1.3.1–4（消光积分）、§4.1.1（操作流程逐列气溶胶）、§2.4.2（气溶胶时空分布）；
[geometry.py](../../predictor/geometry.py) 等效地表；[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.C FA-A2。
