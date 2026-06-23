# 云的分层与覆盖

> 火烧云为什么只在中高云上出现？答案是云的高度和大气边界层的关系。本笔记先给云的标准分层（WMO 三层制），再把它和"日落时被照亮的几何窗口 + 边界层光衰减 + 云本身的光学厚度"三个独立机制对接。
>
> stage: claude-draft

## 概念

### WMO 三层分类（按云底高度，温带）

国际气象组织（WMO）的 *International Cloud Atlas* 把对流层云分为三层：

| 层 | 云底高度 | 主要云属 | 物质 | 光学特征 |
|---|---|---|---|---|
| **高云 (high)** | 5–13 km | 卷云 Ci, 卷积云 Cc, 卷层云 Cs | 冰晶为主 | 半透明、丝缕状、光学厚度通常 < 1 |
| **中云 (middle)** | 2–6 km | 高积云 Ac, 高层云 As, 雨层云 Ns | 水滴/冰晶混合 | 片状或波纹状、中等光学厚度 |
| **低云 (low)** | < 2 km | 层云 St, 层积云 Sc, 积云 Cu | 主要为水滴 | 致密、不透明、光学厚度常 > 10 |

高度区间随纬度漂移：极地区高云可低至 3 km，热带高云可达 18 km。`predictor/` 当前用 HRRR 给出的 `HCDC` / `MCDC` / `LCDC` 三层覆盖率变量，对应的层界由 NOAA 模型内部定义，大致与此表一致。

### 行星边界层 (Planetary Boundary Layer, PBL)

地球表面到大气自由层之间、被地面摩擦和加热驱动产生湍流混合的那一层，称为**行星边界层**。

- 白天 PBL 厚度典型 1–2 km（大陆夏天可到 3 km +），夜间塌缩到几百米；
- 日落后白天的"残层 (residual layer)"在 ~2 小时内还保留高浓度气溶胶；
- 陆地上 90%+ 的对流层气溶胶（人为污染、扬尘、海盐、水汽）聚集在 PBL 内。

这一段对火烧云的意义在下面"机制 2"。

## 关键变量

### 为什么低云不形成火烧云——三个独立机制叠加

**机制 1：几何窗口短**

地球曲率给一个高度 $h$ 的云一个"地平线下沉角度"：

$$d(h) = \arccos\!\left(\frac{R_\oplus}{R_\oplus + h}\right), \quad R_\oplus = 6371\,\text{km}$$

代入：

| 云高 $h$ | 下沉角 $d$ | 含义 |
|---|---|---|
| 1 km | 1.02° | 太阳低于地平线 1° 后即对该云隐没 |
| 2 km | 1.44° | 低云的"被照亮终点"约在日落后 ~6 分钟（太阳约 0.25°/min 下沉） |
| 5 km | 2.28° | 中云照亮终点约日落后 ~9 分钟 |
| 10 km | 3.22° | 高云照亮终点约日落后 ~13 分钟 |
| 15 km | 3.94° | 极高卷云接近 civil twilight 末端（4–6°）|

这与 [formation-conditions](formation-conditions.md) 引用的 Sunsethue 经验数据"低云照亮 ~2 min、高云 ~30 min"在量级上对得上（差异部分来自后者把多次散射形成的"间接照亮"也算了进去）。

**机制 2：低云在 PBL 内，原光在到达前已被严重衰减**

日落时的阳光走的是几乎水平的方向，全程穿过 PBL 这段最厚的大气。PBL 内的气溶胶 + 水汽按 Beer-Lambert 律衰减原光：

$$I = I_0 \cdot e^{-\tau}$$

其中 $\tau$ 是光学厚度。城市 PBL 的可见光 $\tau$ 在 0.3–1.0 量级。换算下来，原光在到达 PBL 上方之前已经损失 25%–63%。**位于 PBL 内的低云**接收的就是这种已经衰减的"二手光"，且这束光本身就缺乏"清洁瑞利散射"产生的鲜艳红橙色。

这正对应 Corfidi 的原话：

> "A cloud must be high enough to intercept 'unadulterated' sunlight—light that has not suffered attenuation by passing through the atmospheric boundary layer."

**机制 3：低云光学厚度大、近乎全反射成灰白**

层云 / 层积云的光学厚度常 > 10，对可见光近乎不透。即使得到一点边角红光，云顶吸收/反射的混合也不会显出明显的红橙色——更可能是均匀的灰粉。卷云相反，光学厚度 < 1，光能透过、被云中冰晶散射，鲜艳度因此更高。

**三个机制独立、叠加**：低云在火烧云这件事上是"几乎不可能赢"的。

## 资料来源

1. **WMO International Cloud Atlas**, World Meteorological Organization. <https://cloudatlas.wmo.int/> — 云分类的国际标准。
2. **NOAA JetStream — Ten Basic Clouds**. <https://www.noaa.gov/jetstream/clouds/ten-basic-clouds> — 与 WMO 一致的美国官方教学页面，给出对应的英尺/米换算。
3. **Wikipedia: *List of cloud types***. <https://en.wikipedia.org/wiki/List_of_cloud_types> — 各属云的高度区间（含纬度差异），与上表一致。
4. **Corfidi, S. F. (2014). *The Colors of Twilight and Sunset*.** NOAA SPC. <https://www.spc.noaa.gov/publications/corfidi/sunset/> — "unadulterated sunlight" 一段；"低云很少形成火烧云"的判断。详见 [formation-conditions](formation-conditions.md)。
5. **Wikipedia: *Planetary boundary layer*** 及 *J. Geophys. Res. Atmos.* 2025 综述系列 — PBL 厚度、日变化、气溶胶聚集。
6. **几何**：地平线下沉角 $d = \arccos(R/(R+h))$ 是标准地球曲率几何，任意大气光学/航海几何教材都有，未引用具体文献。

## 对预测规则的启示

`MidHighCloudPresence` 这条 gate 在 cloud-physics 角度有**三条独立支撑**（几何窗口、PBL 衰减、光学厚度），不是单一机制。这意味着即使在边缘条件下，这条 gate 也很稳健——不像湿度那种可以被其他变量补偿。

进一步细化建议（与 [formation-conditions](formation-conditions.md) 的新规则清单衔接）：

1. **`CloudAltitudePreference`（modifier）** 的权重排序应反映几何窗口的差异：
   - 高云（HCDC）：权重 1.0
   - 中云（MCDC）：权重约 0.5
   - 低云（LCDC）：权重 0.1（仅作为"有总比没有强"的微小加成；接近零）

2. **`MidHighCloudPresence`** 的"中高云覆盖率"定义建议改为加权和：
   - 现状：`(cloud_mid_pct + cloud_high_pct) / 2`
   - 建议：`0.7 * cloud_high_pct + 0.3 * cloud_mid_pct`
   - 反映"高云被照亮时间更长、光学更利于显色"的事实。

3. **PBL 高度作为新特征**：HRRR 提供 `HPBL`（Planetary Boundary Layer Height）变量。如果当日 HPBL 异常厚（如 > 2.5 km，意味着 PBL 升高、把更多气溶胶混到中云高度），中云的反射质量也会下降。这可以并入 `CleanAirGate` 的派生特征。

4. **光学厚度作为隐含变量**：HRRR 不直接给云的光学厚度（cloud optical depth），但给 `Total Cloud Cover` 和分层覆盖率。如果未来需要更细，可以从 MERRA-2 或 GOES 卫星反演产品里拉 COD。

延伸阅读：

- [atmospheric-optics.md](atmospheric-optics.md)：Beer-Lambert 衰减的散射机制细节；瑞利 vs 米氏；为什么 0.5–1 μm 气溶胶不是好散射体。
- [solar-geometry.md](solar-geometry.md)：地平线下沉角的几何推导；太阳高度角与光路长度（airmass）的换算公式。
- [aerosols-and-color.md](aerosols-and-color.md)：火山平流层尘 vs 对流层污染——同是颗粒，色彩效应相反。
