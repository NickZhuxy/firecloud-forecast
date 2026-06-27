---
stage: claude-draft
factor: FA-T1
parent: single-point-fidelity-audit.md (§3.E FA-T1)
authority: 人工火烧云预报速成（长三角适用）.pdf §4.1.1 / §4.2
---

# FA-T1 — 云边界向日落时刻的风平移

> 事实层与推导 Claude 起草；判断层（valid_time 来源、风层选择）待 Nick 复核。

## 1. 问题：边界停在快照时刻，没推到日落

`analyze_sunward_profile`（[features.py](../../predictor/features.py)）从沿日落方位的
1-D 廓线找到**日落方向云边界** `sunward_cloud_boundary_km`，用的是**快照/模式时刻**的云量；
风只进 `BoundaryConfidence` 的**置信度**（`_projected_boundary_wind` 取 `abs` 投影），
**不平移边界本身**。`SunwardIlluminationGate` 随后用 `ratio = boundary / reach` 出分。

手册 §4.1.1 / §4.2 + 翻车清单 #1/#2 的核心步骤：模式场在（粗）时次有效，而火烧云发生在
**日落时刻**；其间云边界**随云高风移动**，必须用风把边界外推到日落再打分。§4.2 算例把一个
中云洞在 30 分钟内平移 ~40 km——足以翻转"边界在不在到达范围内"的结论。

## 2. 模型：沿观察者→日落轴的有符号风平移

设边界法向（≈沿观察者→日落方位 `azimuth_deg` 轴）的**有符号**风分量 `v∥`（m/s），
平移时长 `Δt = 日落时刻 − valid_time`（s）。平移后边界：

```
boundary_advected_km = max(0, boundary_km + v∥ · Δt / 1000)
```

- **符号约定**：气象风向是"风从哪来"，先转风**去向** `to = (dir+180) mod 360`，投影到
  日落方位轴 `v∥ = speed · cos(to − azimuth)`。`v∥ > 0` ⟹ 云**向日落方向（外）**移动 ⟹
  边界外推、`boundary` 增大；`v∥ < 0` ⟹ 云向观察者（内）移动、`boundary` 减小。
- **风层**：用画布层对应气压（low→850 / mid→700 / high→400 hPa），取边界两侧采样点均值
  （复用既有 `_projected_boundary_wind` 的风层与取点；本因子把它从 `abs` 改为**有符号**，
  `boundary_motion_m_s` 仍取 `abs` 不变）。
- 这是纯运动学外推（frozen-boundary advection），不改云的生消（手册把生消归为对流/噪声型，
  属 FA-T3，不在此）。

## 3. valid_time 从哪来（架构缝）

1-D 边界来自 Open-Meteo 快照（沿程 `sunward_profile`），其**有效时刻 = 查询 `time`**
（数据按该时取）。日落时刻 `sunset_time` 已在快照/`derive`（astral 回退）。故自洽的
`Δt = sunset_time − time`：

- 详细单点产品若**按日落时次**取数 ⟹ `Δt ≈ 0` ⟹ 平移为**恒等（无操作）**，安全。
- 若在**更早时次**（如午后模式场）取数预报日落 ⟹ `Δt > 0` ⟹ 边界被外推到日落。

为通用化（粗时次模式场，模式有效时刻 ≠ 查询时），`derive`/`analyze_sunward_profile` 接受
**可选 `valid_time` 覆盖**（默认 = 查询 `time`），调用方知道真实模式有效时刻时可传入。
注：2-D GFS cube 有自己的 `valid_time`，但它与 Open-Meteo 1-D 边界**不同源**，不可混用来
平移 1-D 边界；2-D 截面的逐列平移是更大的后续（见 §6）。

## 4. 假设与适用域

- **冻结边界平移**：Δt 内边界形状不变、只整体随风移动；适合手册的短时（数十分钟）外推，
  长 Δt 或强生消时退化（→ FA-T3 降置信）。
- 单一画布层风代表整段边界运动（手册典型云况）；切变强时偏差。
- `v∥` 用边界两侧采样点风的均值；与 `BoundaryConfidence` 同源同取点，方向相反语义（一个测
  "动多快不确定"、一个测"往哪动多远"）。
- **退化**：`Δt=0`、风缺测、或无边界 ⟹ 平移为恒等，`boundary_advected = boundary_raw`，
  逐位回到现行为（纯增量）。

## 5. 验证设计（先写失败测试；性质不变量 / 算例）

1. **纯平移闭式**：`advect_boundary_km(b, v∥, Δt) == b + v∥·Δt/1000`（外移增、内移减），floor 0。
2. **手册 §4.2 量级**：`v∥≈22 m/s`、`Δt=30 min` ⟹ 平移 ≈ 40 km（对算例）。
3. **Δt=0 恒等**：`sunset_time==valid_time` ⟹ `advected==raw`（无操作回归锁）。
4. **符号正确**：云去向=日落方位 ⟹ 边界外推增大；反向 ⟹ 减小、floor 不为负。
5. **接线**：`derive` 在 `Δt>0`、有风时填 `sunward_cloud_boundary_km`=平移值、
   `sunward_cloud_boundary_raw_km`=原值；`SunwardIlluminationGate` 消费平移值。
6. **metamorphic（composite）**：其它不变，边界被外推到**超出 reach** ⟹ `sunward_illumination`
   非增（边界越界 → gate 降/否决）。→ 扩 `test_metamorphic_physics` 或端到端。
7. **回归**：全量 `-m "not integration"` 绿；国家级/grid 不用 sunward 边界、不受影响；
   `boundary_motion_m_s`（abs）与 `BoundaryConfidence` 不变。

## 6. 后续

- 2-D 截面逐列/逐高平移（GFS cube valid_time）：把整张 `SunwardCrossSection` 的 cloud_layers
  按各列各层风×Δt 水平移位，喂 `trace_ray_clearance`——比 1-D 边界平移更全，但需解决 cube vs
  Open-Meteo 源/网格对齐，单列一个更大 story。
- FA-T2（P3）：模式时次-日落偏差跟踪与逐时插值，依赖本因子。

## 7. 对预测规则的启示

- [features.py](../../predictor/features.py)：`_projected_boundary_wind` 改有符号（call site 取 abs
  保持 `boundary_motion_m_s`）；`analyze_sunward_profile` 接受 `sunset_time`/`valid_time`，
  输出平移后 `sunward_cloud_boundary_km` + 原值 `sunward_cloud_boundary_raw_km`。
- [geometry.py](../../predictor/geometry.py) 或 spatial：纯 `advect_boundary_km`。
- `SunwardIlluminationGate`（[rules.py](../../predictor/rules.py)）消费平移后边界——签名不变。

参考：手册 §4.1.1、§4.2（中云洞 30 min 平移 40km）；solar-geometry §5 时次提醒；
[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.E FA-T1。
