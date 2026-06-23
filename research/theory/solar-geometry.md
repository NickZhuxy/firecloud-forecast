# 日落几何与大气光程

> 把"低角度太阳光走很长大气路径"这一火烧云的几何前提量化。给出 airmass、太阳角度时间窗、地平线下沉角三组公式，并把它们对接到 [atmospheric-optics](atmospheric-optics.md) 的消光积分和 [cloud-physics](cloud-physics.md) 的云照亮窗口。
>
> stage: claude-draft（公式部分依据 peer-reviewed 一手源 Kasten & Young 1989；判断部分待 Nick 复核）

## 概念

### 太阳几何坐标

定义观察者头顶为天顶。太阳的两个互补角度：

- **太阳高度角** $\alpha$（solar elevation, altitude）：太阳与地平面的夹角，正午最大，地平线时为 $0°$。
- **太阳天顶角** SZA（solar zenith angle）：$\mathrm{SZA} = 90° - \alpha$。

火烧云相关的角度区间 $\alpha \in [-6°, +5°]$ 对应 $\mathrm{SZA} \in [85°, 96°]$。

### Apparent vs Geometric Sunset

大气折射在地平线处约为 $34'$（0.57°），即光线被向上弯曲。所以：

- **几何日落**：太阳几何中心位于地平线（$\alpha_{\text{geom}} = 0°$）
- **视日落**：太阳被折射抬高 0.57° 后，**视位置**在地平线（$\alpha_{\text{geom}} \approx -0.83°$ 因为太阳本身有 0.27° 半径）

两个差约 2–3 分钟。`astral` 库默认返回的是视日落时间，符合天文台和大众预期。

### Twilight 三段

按太阳几何角度划分（IAU/NOAA 标准）：

| 阶段 | 太阳角度区间 (geometric) | 含义 |
|---|---|---|
| **Civil twilight** | $-6° < \alpha < 0°$ | 天空仍亮足够进行户外活动；行星和最亮恒星可见 |
| **Nautical twilight** | $-12° < \alpha < -6°$ | 地平线轮廓仍可辨；天空依然有彩 |
| **Astronomical twilight** | $-18° < \alpha < -12°$ | 天文观测仍有大气光残余；肉眼几乎全黑 |

火烧云典型时间窗是**视日落前 30 分钟到 civil twilight 结束**，对应 $\alpha \in [-6°, +5°]$。

## 数学

### 太阳运动速率

天球转动速率为 $360°/24\,\mathrm{h} = 15°/\mathrm{h}$。但太阳**高度角变化率**取决于其轨迹与地平线的夹角，是季节和纬度的函数。

近地平线粗略估计：在中纬度春秋分前后，$d\alpha/dt \approx 15°/\mathrm{h} \cdot \cos(\phi) \cdot \sin(\text{azimuth from north})$，约 $10°$–$14°/\mathrm{h}$，或 $0.17°$–$0.23°/\mathrm{min}$。极地和热带差异大：

| 纬度 | 春秋分时 $|d\alpha/dt|$ near horizon |
|---|---|
| 0° (赤道) | ~$0.25°/\mathrm{min}$ |
| 40° N | ~$0.19°/\mathrm{min}$ |
| 60° N | ~$0.13°/\mathrm{min}$ |
| 极地 (>66.5°) | 接近 0（极昼/夜临界） |

实际计算应直接调 `astral` / `pvlib` / `NREL SPA`，不要用 $0.25°/\mathrm{min}$ 这个粗值。下面几个时长换算只作量级参考。

### Airmass（相对光路长度）

定义：$m = $ 实际大气光路长度 / 天顶时大气厚度。

**平面大气近似**（valid $\mathrm{SZA} < 75°$）：

$$m \approx \frac{1}{\cos(\mathrm{SZA})} = \sec(\mathrm{SZA})$$

近地平线时 $\sec(\mathrm{SZA}) \to \infty$，所以必须用球面修正。

**Kasten & Young (1989) 修正公式**（peer-reviewed 标准，被 NREL SPA 和大多数太阳辐射模型采用）：

$$m(\mathrm{SZA}) = \frac{1}{\cos(\mathrm{SZA}) + 0.50572 \,(96.07995 - \mathrm{SZA})^{-1.6364}}$$

（$\mathrm{SZA}$ 以度为单位。）

代入：

| $\alpha$ | $\mathrm{SZA}$ | airmass $m$ | 含义 |
|---|---|---|---|
| 90° | 0° | 1.00 | 正午 |
| 30° | 60° | 2.00 | 上午/下午 |
| 10° | 80° | 5.6 | 黄昏开始 |
| 5° | 85° | 10.4 | 火烧云典型阶段开始 |
| 1° | 89° | 27 | 日落前几分钟 |
| 0° | 90° | 38 | 视日落瞬间 |
| –4° | 94° | $\to$ 模型外推区 | 高云仍被照亮 |

也就是说**日落时的大气光路是正午的近 40 倍**。这是把 [atmospheric-optics](atmospheric-optics.md) 的所有消光积分（Rayleigh、Mie、Chappuis）放大到决定性程度的物理原因——同样的 $\tau$ 单位长度，沿这条光路要累积 38 次。

### 地平线下沉角（云被照亮的几何窗口）

观察者在海平面，云在高度 $h$。云能"看到"太阳iff 太阳几何高度 $\alpha$ 高于该云的**地平线下沉角** $-d(h)$：

$$d(h) = \arccos\!\left(\frac{R_\oplus}{R_\oplus + h}\right), \quad R_\oplus = 6371\,\text{km}$$

小角近似 $h \ll R_\oplus$：

$$d(h) \approx \sqrt{\frac{2h}{R_\oplus}} \quad (\text{rad})$$

代入：

| $h$ | $d(h)$ | 视日落后云仍被直射的时长（粗略，0.2°/min） |
|---|---|---|
| 1 km | 1.02° | ~5 min |
| 2 km | 1.44° | ~7 min |
| 5 km | 2.28° | ~11 min |
| 10 km | 3.22° | ~16 min |
| 15 km | 3.94° | ~20 min |
| 20 km | 4.55° | ~23 min |

这张表是 [cloud-physics](cloud-physics.md) "为什么低云不形成火烧云"的几何核心——低云的照亮窗口比高云短一个量级。

注意"被直射"和"被照亮"不同。云的边缘还能接受到二次散射光（被高大气、临近云反射的间接光），所以视觉上的火烧云持续时间通常比上表给出的"直射结束时刻"再延长几分钟。

### 云被直射的时间窗（从视日落算起）

定义云在高度 $h$ 处可被直射的时段为：从太阳几何高度 $-d(h)$ 上升到 $-d(h)$ 之上。日落前后这一段大约是：

$$\Delta t(h) \approx \frac{2 \cdot d(h)}{|d\alpha/dt|}$$

中纬度 ($|d\alpha/dt| \approx 0.2°/\mathrm{min}$) 春秋分：

| 云高 $h$ | $\Delta t$ |
|---|---|
| 1 km (低云) | ~10 min |
| 5 km (中云) | ~23 min |
| 10 km (高云) | ~32 min |
| 15 km (高云上限) | ~40 min |

与 [formation-conditions](formation-conditions.md) 引用的 Sunsethue 经验数据（低云 2 min 直射 + 多次散射间接、高云 30 min）量级吻合。

## 资料来源

1. **Kasten, F., & Young, A. T. (1989).** *Revised optical air mass tables and approximation formula.* *Applied Optics*, 28(22), 4735–4738. <https://opg.optica.org/ao/abstract.cfm?uri=ao-28-22-4735> — 当代 airmass 公式的 peer-reviewed 标准；本笔记的 $m(\mathrm{SZA})$ 出处。
2. **Reda, I., & Andreas, A. (2004).** *Solar Position Algorithm for Solar Radiation Applications.* NREL/TP-560-34302. <https://www.nrel.gov/grid/solar-resource/solpos.html> — 高精度太阳位置算法 (±0.0003°)，业界标准；`pvlib` / `astral` 的底层。
3. **Meeus, J. (1998).** *Astronomical Algorithms* (2nd ed.). Willmann-Bell. — 太阳/月亮位置计算的经典教材。
4. **Wikipedia: *Air mass (astronomy)***. <https://en.wikipedia.org/wiki/Air_mass_(astronomy)> — 多个 airmass 近似公式的横向对比。
5. **NOAA Earth System Research Laboratory: *Solar Calculator***. <https://gml.noaa.gov/grad/solcalc/> — 太阳位置在线计算器；折射和 twilight 阶段定义出处。
6. **几何**：$d = \arccos(R/(R+h))$ 是标准地球曲率几何，亦见 [cloud-physics.md](cloud-physics.md)。

## 对预测规则的启示

把上面的几何对回 `SolarAngleAtSunset` 规则：

1. **当前实现的瑕疵**：现在 `SolarAngleAtSunset` 用固定的 $\pm 30$ 分钟到 $\pm 60$ 分钟窗。但真实窗口长度取决于纬度和季节：赤道附近 civil twilight 约 24 min，中纬度春秋分 ~30 min，温带夏季 ~38 min，高纬度更长。固定阈值会在 Olympic Peninsula (47.9° N) 这种高纬地点低估窗口，在低纬度高估。

2. **改进建议**：把规则的窗口定义从"分钟"换成"太阳几何高度"——
   - 满分窗 $\alpha \in [-3°, +3°]$（火烧云高峰）
   - 线性降到 0 在 $\alpha = -6°$（civil twilight 结束）或 $\alpha = +6°$（高度太高、光路不够长）
   - 这样窗口长度自动随纬度/季节调整。`astral` / `pvlib` 都能直接给 `solar_elevation_deg`，已在 [features.py](../../predictor/features.py) 里有 `solar_elevation_deg` 字段。

3. **新增 `Airmass` 派生特征**：直接计算 $m(\mathrm{SZA})$ 作为 features 之一。下游可以暴露给 ML 阶段使用，或作为 atmospheric-optics 三机制消光的乘子。

4. **`CloudAltitudePreference` 的权重应反映直射窗口长度**：
   - 高云 ($h \approx 10$ km，$\Delta t \approx 32$ min)：权重 1.0
   - 中云 ($h \approx 5$ km，$\Delta t \approx 23$ min)：权重 0.7
   - 低云 ($h \approx 1$ km，$\Delta t \approx 10$ min)：权重 0.3

5. **HRRR 数据时间分辨率限制**：HRRR 是逐小时输出，但 fire cloud 时间窗只有 ~30 min。意味着我们一次预报应该绑定**最接近 sunset 的那个整点**，而不是任意时刻——`HRRRSource` 当前实现按查询时间往前 2 小时取 cycle，可以改为"取离 sunset 最近的可用 cycle"。

## 论文章节种子

这一篇可以扩成 paper 的 "Geometry & Path Length" 小节，要补的：

- 一张图：把 Kasten-Young airmass 曲线和"高云 vs 低云直射窗口"叠在同一时间轴上，火烧云的"为什么持续这么久"一目了然。
- 太阳路径与地平线夹角的纬度依赖图（即"为什么高纬度夏天的日落特别长"——光线沿地平线滑行而非垂直下落）。
- 把 airmass $m(\mathrm{SZA})$ × 三机制波长依赖的 $\tau(\lambda)$ 乘积积分，得到日落时刻可见光谱透射函数 $T(\lambda)$ 的数值表，作为"火烧云为什么红"的最终量化结论。

延伸：

- [atmospheric-optics](atmospheric-optics.md)：本笔记 airmass 是给 atmospheric-optics 三机制消光乘上的几何因子；二者一起决定 $\tau_{\text{total}}(\lambda)$ 的数值。
- [cloud-physics](cloud-physics.md)：本笔记的"地平线下沉角"是 cloud-physics "为什么低云不行" 的几何机制 1。
- [aerosols-and-color](aerosols-and-color.md)：airmass 决定臭氧柱和气溶胶柱在日落光路里被"放大"的倍数。
