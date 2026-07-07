---
stage: claude-draft
factor: FA-A3
parent: single-point-fidelity-audit.md (§3.C FA-A3, §5 单调性澄清)
authority: 人工火烧云预报速成.pdf §2.4.1（表 2.3）/ §1.3.4 / §4.1.1
---

# FA-A3 — 气溶胶双角色拆分：路径消光（进概率）vs 本地观感（进质量）

> 事实层与推导 Claude 起草；判断层（层级归属、缺数据语义）待 Nick 复核。
> 依赖 FA-A2（已并入 main）：路径消光的概率角色已有几何载体。

## 1. 问题：一条 gate 同时扮演两种物理角色

当前 `CleanAirGate`（[rules.py](../../predictor/rules.py)）取
`max(本地 AOD, sunward_aod_mean)` 过表 2.3 分段曲线，作为**概率 gate**：

- **角色混淆**（审计 §3.C 原文）：手册区分"路径消光"（决定光能否到达画布 →
  有无）与"本地观感"（削弱看到的亮度/饱和度 → 质量），这里被 `max()` 合成一个数。
- **双重计数**：路径 AOD 同时进了几何等效地表（1-D `SunwardIlluminationGate` 的
  `equivalent_cloud_base_from_aod_m(base, sunward_aod_mean)`；2-D 光追 FA-A2 的
  观察者列等效底 + 逐列超出否决）。同一物理量在概率里吃了两次。

## 2. 手册物理：两条通道各自的归宿

**路径消光 → 有无（概率）。** §1.3.4 / §4.1.1：“气溶胶要少在**阳光传播路径上**，
光在本地或者地面附近少是不够的。”这是几何问题——光沿掠射抛物线穿过哪些列、
哪列的近地消光超出基准，FA-A2 已逐列建模；1-D 路径用 `sunward_aod_mean` 的
等效地表近似。**概率通道里的气溶胶就到此为止。**

**本地观感 → 质量（亮度/饱和度）。** §2.4.1（节名即"气溶胶的**观感**"）：

> "本地的气溶胶会把火烧云散射的光线消光，导致火烧云的颜色亮度和饱和度都下降很多。"
> "总之，本地的气溶胶对于火烧云基本没有正面影响，我们希望气溶胶光学厚度越小越好。"

表 2.3 的标题是"AOD 与**视觉上**大气通透度的对照关系"——这张表本来就是观感表，
不是有无表。关键语义：

- `>0.8` 档的措辞是"火烧云**再怎么大烧**也是污烧"——事件仍然发生（"我也见过"），
  是质量崩坏，不是概率归零。现状把它当 gate 归零概率，语义错了。
- 正向不对称："如果发现气溶胶非常少，就算火烧云概率不算大……也可以出去看看"——
  洁净空气抬升观赏价值而非发生概率。
- **单调性保留**（审计 §5 明确）：对火烧云这种反射视角，"AOD 越小越好"单调成立，
  **不做 Goldilocks**（Lee 2003 的平流层背景气溶胶增强是暮光余晖场景，火烧云以
  云为画布，不适用；此澄清同步补进 [aerosols-and-color.md](aerosols-and-color.md)
  "对预测规则的启示"第 2 条）。

## 3. 设计

项目的两层架构（paper §6.2）恰好就是这两个通道：**gate 层 = 必要条件（有无），
modifier 层 = 质量**。所以拆分 = 归位：

1. **路径消光留在几何通道（不新增代码）**：2-D = FA-A2 观察者列等效底 + 逐列
   超出否决；1-D = `SunwardIlluminationGate` / `grid_score._sunward_illumination`
   的 `sunward_aod_mean` 等效地表。`CleanAirGate` **停止读取 `sunward_aod_mean`**，
   双重计数消除。
2. **本地观感成为 modifier**：`"clean_air"` 从 `STANDARD_GATES` 移除 ⇒ 自动进
   modifier 层（算术加权平均）。曲线不变：表 2.3 分段线性
   `(0,1)(0.1,1)(0.2,0.9)(0.3,0.75)(0.5,0.4)(0.8,0)`，单调不增。权重保持 1.5
   （§2.4.1："本地的气溶胶多少对火烧云观赏的影响是巨大的"，高于 humidity 的 1.0）。
3. **输入 = 本地信号**：`f.aerosol_optical_depth`（Open-Meteo air-quality 本地柱
   AOD）优先；缺失时回退地表能见度 5–20 km 线性（本地边界层消光的观感代理，
   Liao 2024 能见度→AOD 反演支持）。
4. **缺数据 = None（组件缺席）**，不再返回 1.0。`ScoringRule` 协议注释本来就要求
   "missing ≠ perfect"；旧的 1.0 在 gate 几何平均里通过稀释指数隐性抬分。
5. **命名**：类改名 `LocalAerosolPerception`（语义如实），组件键保持 `"clean_air"`
   （权重表、解释串、外部元数据稳定）。
6. **grid 镜像**（[grid_score.py](../../predictor/grid_score.py)）：`clean_air`
   权重从 `_GATE_WEIGHTS` 移到 `_MODIFIER_WEIGHTS`；信号缺失 ⇒ 从 modifier 集缺席
   （替代现在的 `ones` 填充），与标量 None 语义镜像，parity 测试维持 1e-9。

## 4. 可预期的分值漂移（有意的语义修正）

- **重霾点**（AOD ≥ 0.8）：composite 从 0 变为 G·M 里 M 被压低——"污烧"可见但
  低分,不再假装不发生。
- **国家场**：能见度默认填充 25 km ⇒ `clean_air≈1.0` 从 gate 层（中性）变为
  modifier 层成员（抬高 M 的加权平均）⇒ 全场分值轻微整体上移；雾区从"gate 归零"
  变为"质量压低"。
- **无信号点**：组件缺席 ⇒ gate 指数重归一化，分值相对旧 1.0-gate 略降。

## 5. 验证设计（先写失败测试；metamorphic / 性质不变量）

1. **角色分离**：本地洁净 + 路径均值脏 ⇒ `clean_air` 组件 = 1.0（路径的影响只能
   经 `sunward_illumination` 出现）。翻转现有
   `test_clean_air_uses_worst_of_local_and_sunward_aod`。
2. **污烧不灭**：全 gate 通过 + 本地 AOD=0.9 ⇒ composite > 0 且显著低于洁净
   同场景（质量压低、概率不灭）。
3. **单调性（metamorphic，真实链路）**：本地 AOD 上升 ⇒ composite 单调不增；
   路径 AOD 上升 ⇒ composite 单调不增（几何通道，FA-A2 既有测试继续锁）。
4. **缺数据**：AOD 与能见度双缺 ⇒ `evaluate` 返回 None ⇒ 组件缺席。
5. **层级**：`"clean_air" ∉ STANDARD_GATES`；标准预测器 components 仍含
   `clean_air`（有数据时）。
6. **grid parity**：AOD 有 / 仅能见度 / 全缺三态下 grid 与标量 1e-9 一致
   （更新 `test_missing_clean_air_signals_are_neutral_like_scalar` 到缺席语义）。
7. **回归**：FA-A2 逐列否决测试不动；全量离线套件绿（钉绝对值的场景测试按
   §4 的漂移逐条核对后更新，不盲改）。

## 6. 对预测规则的启示（变更清单）

- [rules.py](../../predictor/rules.py)：`CleanAirGate` → `LocalAerosolPerception`
  （键 `clean_air` 不变；去 `sunward_aod_mean`；双缺 → None）；`STANDARD_GATES`
  移除 `clean_air`。
- [grid_score.py](../../predictor/grid_score.py)：`clean_air` 移入
  `_MODIFIER_WEIGHTS`；`_clean_air` 缺信号 ⇒ 缺席而非 `ones`。
- [aerosols-and-color.md](aerosols-and-color.md) 启示 §2：补火烧云单调性澄清
  （交叉引用审计 §5）。
- 不动：`features.py`（两个 AOD 字段本就分开）、FA-A2 光追、1-D 等效地表、
  `national_physics` 采样。

参考：手册 §2.4.1（表 2.3、观感案例）、§1.3.4（路径消光）、§4.1.1（操作流程）；
[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.C FA-A3、§5；
[fa-a2-path-extinction.md](fa-a2-path-extinction.md) §3（本地 vs 上游的几何分工）。
