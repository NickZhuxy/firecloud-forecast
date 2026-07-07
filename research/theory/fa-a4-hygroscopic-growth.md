---
stage: claude-draft
factor: FA-A4
parent: single-point-fidelity-audit.md (§2 表 FA-A4)
authority: 人工火烧云预报速成.pdf §2.4.3 / §1.1.3 / §1.3.1
---

# FA-A4 — RH 吸湿增长对气溶胶消光 β 的放大（雾霾）

> 事实层与推导 Claude 起草；判断层（增长函数形式、γ/参考点/封顶默认值）待 Nick 复核。
> 在 FA-A3（通道拆分）之后落地：放大器对"路径消光（几何）"与"本地观感（modifier）"
> 两条已拆清的通道同式生效。

## 1. 问题：干 AOD 低估潮湿边界层的近地消光

模型里所有 β 推导都从柱 AOD 出发（`β₀ = AOD/H`，指数廓线，
[geometry.py](../../predictor/geometry.py)）。手册 §2.4.3 指出这在湿边界层里系统性偏低：

> "当大气的相对湿度开始增加，气溶胶颗粒也会开始吸水，在微观上体现为颗粒物的大小
> 增长。即使大气相对湿度还不支持形成雾或者云（还不到活化云滴的湿度），颗粒物也会
> 增长（见章节 1.1.3 云的产生方式），使得空气能见度进一步恶化。"

> "当我们发现空气相对湿度比较大但还不至于形成雾（比如相对湿度小于 85%），且气溶胶
> 消光系数（或者颗粒物浓度）也比较大，我们就需要考虑**增加对气溶胶消光程度的估计**。"

> "这也是为什么当低云比较多的时候，低层大气很潮湿的时候，大气会看起来比只用气溶胶
> 光学厚度来预计的更加浑浊。"

§1.1.3 同源物理：吸湿性凝结核"在空气中水汽还没饱和的时候就已经开始吸水"。

## 2. 物理模型：有界 Hänel 幂律增长因子

标准气溶胶吸湿光学增长（Hänel 1976；IMPROVE f(RH) 曲线同族）：

```
g(RH) = 1                                        RH ≤ RH_ref
g(RH) = ((1 − RH_ref/100) / (1 − min(RH, RH_cap)/100))^γ    RH > RH_ref
```

默认 **RH_ref = 60%，RH_cap = 90%，γ = 0.6**（判断层，待 Nick 复核）：

| RH % | ≤60 | 70 | 80 | 85 | ≥90 |
|---|---|---|---|---|---|
| g | 1.00 | ≈1.19 | ≈1.52 | ≈1.80 | ≈2.30 |

- **RH_ref=60**：IMPROVE 曲线在 60% 以下 f≈1.0–1.15，增长可忽略；60% 以下严格
  g=1 保证干场景逐位回归。
- **RH_cap=90**：超过 ~90% 进入雾/云活化域——幂律发散无物理意义，且雾已由能见度
  信号与云诊断承担（§2.4.3："当水汽在底层大气凝结形成雾的时候，能见度会下降到比较
  低的数字，不管气溶胶光学厚度高还是不高"）。手册自己的操作口径也是"还不至于形成雾
  （比如相对湿度小于 85%）"。
- **γ=0.6**：Hänel 城市气溶胶 γ≈0.5–0.7 的中值。

**应用方式：有效 AOD = AOD · g(RH)**，其中 RH 取与该 AOD **同位**的近地相对湿度。
等效不透明地表变为 `h_x = H·ln(AOD·g/(H·β_x))`——g 进对数，放大有界且平滑。

## 3. 为什么不算重复计数（CAMS AOD 已是环境值）

Open-Meteo air-quality 的 AOD 来自 CAMS，是**环境（含水）柱值**。FA-A4 放大的不是
柱总量，而是修正 `β₀=AOD/H` 这一**固定指数廓线**假设：吸湿增长集中发生在 RH 最高的
边界层，使真实廓线比指数假设**更贴地**——掠射几何恰恰只关心近地那一段。§2.4.3 说
"地面附近气溶胶消光系数与气溶胶光学厚度之间……这种关系只是大致的成立"，湿边界层
正是主要偏差源。故 g 是"垂直再分配"修正，不是"再加一次水"。（claude-draft 判断，
若 Nick 认为柱值已含增长应只在廓线形状上修正，可把 g 降为形状因子——接口不变。）

与 `HumidityFactor`（40–80% 梯形，画布湿度质量）不重复：那是云物理通道，本项是
气溶胶光学通道；两者共享输入 RH 但作用于不同物理量。

## 4. 生效位置（与 FA-A3 拆好的通道一一对应）

1. **本地观感（modifier）**：`LocalAerosolPerception` 查表 2.3 前先
   `AOD_eff = AOD·g(f.humidity_pct)`——手册："大气会看起来比只用 AOD 预计的更浑浊"。
2. **观察者等效底（概率，几何）**：`equivalent_cloud_base_from_aod_m(base, aod, rh_pct=…)`
   新增可选 RH；1-D `SunwardIlluminationGate` 与 2-D 顶点（features.py 观察者列）传
   观察者地面 RH。
3. **逐列否决（概率，FA-A2 光追）**：`trace_ray_clearance` 每列
   `h_x(AODⱼ·g(RHⱼ))`，RHⱼ = 该列截面最低层（≤1.5 km）有限 RH；观察者基准同式
   `h_x(AOD₀·g(RH₀))`。**均匀 AOD + 均匀 RH ⟹ Δⱼ=0，不自我否决——FA-A2 核心
   不变量保持**；均匀 AOD + 上游湿池 ⟹ 可否决——这正是手册的"雾霾"联手场景，
   FA-A2 笔记 §5 明列的"忽略 RH 吸湿增长"缺口在此补上。
4. **国家 grid 镜像**：`grid_score._clean_air` / `_equivalent_base_from_aod` /
   `_sunward_illumination` 增湿度参数（cell 同位 RH），矢量化同式，parity 1e-9。

**退化**：RH 缺失（列 NaN / 无最低层）⟹ g=1 ⟹ 与现状逐位一致；RH≤60 同理。

## 5. 验证设计（先写失败测试；metamorphic / 性质不变量）

1. **增长因子性质**：RH≤60 严格 =1；单调不减；封顶 g(95)=g(90)；g(80)≈1.52（数值钉）。
2. **等效底**：同 AOD，RH=84 的等效底 < RH=60（=干值）；rh=None 逐位回归。
3. **观感**：AOD=0.40 时 RH=84 的 clean_air 分 < RH=60 的分（0.40·1.74→查表更低）；
   RH=60 分值与 FA-A3 版本逐位一致。
4. **逐列否决**：均匀 AOD+均匀高 RH ⟹ clear（不自我否决，核心回归）；均匀 AOD+
   上游湿列（RH 85 vs 观察者 60）⟹ 否决存在性；观察者湿+上游干 ⟹ clear。
5. **端到端 metamorphic**：AOD 在场时地面 RH 于 [60,90] 上升 ⟹ composite 单调不增
   （湿度梯形与吸湿放大同向）；clean_air 组件严格下降保证非平凡。
6. **grid parity**：湿 cell（RH 84 + AOD）标量/grid 1e-9；国家 sunward 路径同。
7. **回归**：全量离线套件绿；RH≤60 的既有场景逐位不动。

## 6. 对预测规则的启示（变更清单）

- [geometry.py](../../predictor/geometry.py)：新增 `hygroscopic_growth_factor`；
  `aerosol_ground_height_m` / `equivalent_cloud_base_from_aod_m` 增可选 `rh_pct`。
- [rules.py](../../predictor/rules.py)：`LocalAerosolPerception` 与
  `SunwardIlluminationGate` 传 `f.humidity_pct`。
- [features.py](../../predictor/features.py)：2-D 顶点等效底传 snapshot 湿度。
- [ray_path.py](../../predictor/ray_path.py)：逐列近地 RH 提取 + 有效 AOD。
- [grid_score.py](../../predictor/grid_score.py)：三处矢量化镜像。
- 不动：`equivalent_cloud_base_range_from_aod_m`（FA-A1 的 H 扫描正交，留待合流）、
  `national_physics` 采样（raw AOD 照旧，消费端放大）。

参考：手册 §2.4.3（雾霾、增估指引）、§1.1.3（未饱和吸水）、§1.3.1（消光-能见度）；
Hänel (1976) *Adv. Geophys.* 19；IMPROVE f(RH)（Malm et al. 1994）；
[fa-a3-aerosol-dual-role.md](fa-a3-aerosol-dual-role.md)、
[fa-a2-path-extinction.md](fa-a2-path-extinction.md) §5。
