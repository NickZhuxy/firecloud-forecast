# 火烧云形成的综合条件

> 把"什么样的天气会出火烧云"从直觉转成可判定的条件，并区分**必要条件**（缺一就一票否决）和**增强条件**（影响强度但非必需）。这一区分直接决定 `predictor/rules.py` 的组合函数该不该用加权平均。
>
> stage: claude-draft（事实部分由 Claude 综述自下列资料；判断部分待 Nick 重写）

## 概念

**火烧云**（英文文献：sunset glow / afterglow / twilight color）指日出或日落前后，中高云层被低角度阳光从下方/侧面照亮、呈现红橙粉紫的现象。云本身不发光——它是在反射经过长大气光路、被瑞利散射剥掉短波后的红橙光。

物理机制（Corfidi, 2014）：

1. **光路加长**。阳光在大气中走过的距离 ≈ (大气厚度) / sin(太阳高度角)。日落时太阳高度角接近 0，光路是正午的 10–30 倍。
2. **瑞利散射筛色**。空气分子对紫光的散射效率约为红光的 3–4 倍。光路一长，紫蓝绿被一层层散射出射线方向，剩下的光偏红橙。
3. **高云反射**。这束已经红化的光必须**穿过低层大气、打到较高云层上**，才能被云"画布"反射给地面观察者。如果低层有遮挡，光在到达高云之前就被衰减，画布得不到照亮。

## 关键变量

| 变量 | 必要 / 增强 | 说明 |
|---|---|---|
| **中/高云存在** | **必要** | 没有画布就没有火烧云。Corfidi 直接说低云（stratus/stratocumulus）"很少"出现火烧云，因为它们在边界层之内，接收的光已被衰减 |
| **低层 + 西方地平线通透** | **必要** | 阳光必须能从西方低角度穿过抵达高云。厚低云或大雾切断光路 |
| **清洁空气（低气溶胶）** | **必要** | Corfidi 原文："Clean air is, in fact, the main ingredient common to brightly colored sunrises and sunsets." 对流层污染气溶胶（0.5–1 μm）不是好的瑞利散射体，反而吸收光、把颜色压成暗淡的浅黄 |
| **太阳低角度** | **必要** | 长光路 → 强散射 → 红化的前提。Wikipedia 给出 civil twilight 窗口：太阳在地平线下 2–6°；可见火烧云的实际窗口更宽，约日落前 30 分钟到日落后 30 分钟 |
| **中高云覆盖率** | 增强 | 量化最关键的一条。SunsetWx 算法瞄 **50–75%** 覆盖；Sunsethue 给 **40–60%**。覆盖太低 → 画布不够；覆盖太满 → 西方地平线被堵 |
| **云的高度** | 增强 | 越高的云被照亮时间越长。Sunsethue：高云（> 6000 m）日落后可被照亮约 30 分钟；中云（2000–6000 m）次之；低云（< 2000 m）只有约 2 分钟 |
| **云的形态** | 增强 | 卷云的丝缕、高积云的鳞片结构产生光影渐变，比均匀云层视觉更丰富 (Corfidi 提到 altocumulus 的 "wave-like or roller motions") |
| **平流层火山气溶胶** | 增强 | 12–18 英里高空火山尘可延长 afterglow 至日落后 15+ 分钟。注意——对流层中的火山尘埃反而压制颜色，跟人为污染一样 |
| **湿度** | 增强（含糊） | Sunsethue："高湿度吸收部分光、火烧云不够鲜艳"。但水汽是云的前提，所以是非线性——太干没云、太湿吸光，存在中间最优 |

百度百科上一句"火烧云属于低云类"与 Corfidi 直接矛盾，不采信。可能是把"地平线低处的红云"和"高云被红化"混为一谈。

## 资料来源

1. **Corfidi, S. F. (2014). *The Colors of Twilight and Sunset*.** NOAA Storm Prediction Center publication. <https://www.spc.noaa.gov/publications/corfidi/sunset/> — 本笔记的主要事实来源，同行评议质量。
2. **SunsetWx Algorithm** (Penn State 学生 + 校友). 基于 GFS 数据的日落预测服务；公开的方法论摘要见 [PetaPixel 报道](https://petapixel.com/2015/12/01/sunsetwx-can-forecast-picture-perfect-sunsets/) 和 [FiveThirtyEight 专题](https://fivethirtyeight.com/features/how-to-avoid-boring-sunsets/)。
3. **Sunsethue Prediction Guide**. 商业日落预测服务的方法论，给出量化云高/云量阈值。<https://sunsethue.com/blog/predict-sunset>
4. **Wikipedia: *Afterglow***. civil twilight 时间窗（太阳 2–6° 低于地平线）的来源。<https://en.wikipedia.org/wiki/Afterglow>

## 对预测规则的启示

**Bug 复述**：当前 `RuleBasedPredictor` 用加权平均把 4 条规则平均，导致"中高云覆盖=0、其他都好"时仍给 0.63 分（见 `research/observations/log.md` 2026-05-20 条）。这是把必要条件当 modifier 平均掉的结构性错误。

**依据上面的"必要 / 增强"分类，组合函数应重构为两层：**

```text
gate     = ∏ score_i^w_i           # 必要条件，乘性，任一为 0 则归零
modifier = weighted_avg(score_j)   # 增强条件，加权平均，作为乘子上下调
probability = gate * modifier
```

具体到现有 4 条规则 + 待加规则：

| 规则 | 现状 | 应归到 | 备注 |
|---|---|---|---|
| `MidHighCloudPresence` | trapezoid 30–70% | **gate**（乘性） | 同时把甜区收窄到 SunsetWx 50–75% / Sunsethue 40–60% 区间；中位约 55% |
| `LowCloudObstruction` | 1.0 if ≤ 20%，线性降到 0 at 100% | **gate**（乘性） | 阈值看起来合理，不改 |
| `SolarAngleAtSunset` | 1.0 内 ±30 min，线性到 0 at ±60 min | **gate**（乘性） | 阈值合理；可考虑扩到 ±45 / ±90 min 因为高云被照亮时间更长 |
| `HumidityFactor` | trapezoid 40–80% | **modifier**（加权平均的一项） | 当前权重 1.0，**应该降到 0.3 左右**——它影响色彩浓度，不决定有没有火烧云 |
| **新增** `CleanAirGate` | — | **gate**（乘性） | Corfidi 第一必要条件。数据源待定：HRRR 不直接给 AOD（气溶胶光学厚度）。过渡方案：用能见度变量做代理，或并入 MERRA-2 / OpenAQ |
| **新增** `CloudAltitudePreference` | — | **modifier** | 高云权重 > 中云权重 > 低云权重，反映"高云照亮时间长"的事实 |
| **新增** `CloudCoverSweetSpot` | — | **modifier** | 当中高云覆盖率落入 40–75% 时给加成；现有 `MidHighCloudPresence` 是 gate 形式（"够不够"），这条是 modifier 形式（"是不是恰到好处"） |

**下一步实现顺序：**

1. 在 `predictor/rules.py` 加 `geometric_combiner` 和新的两层组合接口（保留 `weighted_average` 给 modifier 用）
2. 把 `MidHighCloudPresence` / `LowCloudObstruction` / `SolarAngleAtSunset` 标为 gate-class
3. 把 `HumidityFactor` 标为 modifier，权重降到 0.3
4. 新增 `CleanAirGate` 占位实现——先看 HRRR 是否能拉 `VIS`（能见度）变量，用它做 AOD 代理
5. 加单测：构造"中高云=0 但其他都满分"的合成 features，断言 probability < 0.05
6. 在 `apps/notebook/forecast-map.ipynb` 重跑 Olympic Peninsula 测试用例，确认 0.63 → 接近 0
7. `research/observations/log.md` 加 follow-up 条，记下重构后的对比

延伸阅读（下一篇笔记的种子）：

- [cloud-physics.md](cloud-physics.md)：为什么 < 2000 m 低云不形成火烧云？边界层光衰减 + 云高度决定被照亮的几何窗口长度
- [atmospheric-optics.md](atmospheric-optics.md)：瑞利 vs 米氏散射的量化对比；为什么 0.5–1 μm 气溶胶不是好散射体
- [solar-geometry.md](solar-geometry.md)：太阳高度角 → 光路长度的几何换算
- [aerosols-and-color.md](aerosols-and-color.md)：平流层 vs 对流层气溶胶的反向作用
