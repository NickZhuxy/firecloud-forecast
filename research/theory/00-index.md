# Theory 索引

> 全部笔记 `stage: claude-draft`（事实层 Claude 写、判断层等 Nick 复核）。每篇都以"对预测规则的启示"小节结尾，把研究结论接回 [predictor/rules.py](../../predictor/rules.py)。可作为论文 "Theoretical Background" 章节的基础。

## 推荐阅读顺序

依赖关系：

```
formation-conditions  ── 综述与 gate/modifier 框架
        ↓
cloud-physics          ── 为什么低云不行（geometric + PBL + optical thickness 三机制）
        ↓
solar-geometry         ── airmass 公式、地平线下沉角；所有"长光路"论证的几何基础
        ↓
atmospheric-optics     ── Rayleigh + Mie + 臭氧 Chappuis 三机制消光（Lange 2023 修订经典叙事）
        ↓
aerosols-and-color     ── 平流层 vs 对流层气溶胶反向作用；CleanAirGate 数据源
```

## 笔记一览

| 文件 | 主题 | 关键 peer-reviewed 来源 | 对应规则 |
|---|---|---|---|
| [formation-conditions](formation-conditions.md) | 必要 vs 增强条件；gate/modifier 两层组合 | Corfidi 2014 (NOAA SPC) | 全部 4 条规则 + 新 `CleanAirGate` |
| [cloud-physics](cloud-physics.md) | 云分层；为什么低云不形成火烧云（几何 + PBL + 光厚） | WMO Cloud Atlas; Corfidi 2014 | `MidHighCloudPresence`, `CloudAltitudePreference` (新) |
| [solar-geometry](solar-geometry.md) | airmass; 太阳角度时间窗；地平线下沉角 | Kasten & Young 1989; Reda & Andreas 2004 (NREL SPA) | `SolarAngleAtSunset` (建议改用角度而非分钟) |
| [atmospheric-optics](atmospheric-optics.md) | Rayleigh + Mie + 臭氧 Chappuis 三机制消光 | Lange et al. 2023 (ACP); Lee & Hernández-Andrés 2003 (Appl. Opt.); Stull 2017 | `CleanAirGate` (新), 未来 `OzoneColumn` 特征 |
| [aerosols-and-color](aerosols-and-color.md) | 平流层 vs 对流层气溶胶反向作用；PM2.5/AOD/VIS 代理 | Mateshvili 2005 (JGR); Ribeiro 2024 (ACP); Liao 2024 (ESSD) | `CleanAirGate` 的数据源选择 + 事件触发 `AerosolEnhancement` modifier |

## 主要 peer-reviewed 引用清单

按时间倒序：

- **Ribeiro et al. (2024)** — *Explaining the green volcanic sunsets after the 1883 eruption of Krakatoa.* ACP.
- **Liao et al. (2024)** — *Visibility-derived aerosol optical depth over global land from 1959 to 2021.* ESSD.
- **Lange, Rozanov, & Burrows (2023)** — *Revisiting the question "Why is the sky blue?"* ACP. → 修订 "Rayleigh 解释蓝天" 教科书叙事，臭氧 Chappuis 占 66%.
- **Mateshvili et al. (2005)** — *Twilight sky brightness measurements as a useful tool for stratospheric aerosol investigations.* JGR. → Pinatubo 多波长测量。
- **Reda & Andreas (2004)** — *Solar Position Algorithm.* NREL TP-560-34302.
- **Lee Jr. & Hernández-Andrés (2003)** — *Measuring and modeling twilight's purple light.* Appl. Opt. → 推翻 "平流层气溶胶单独够" 旧说。
- **Bodhaine et al. (1999)** — *On Rayleigh optical depth calculations.* JTECH.
- **Mishra et al. (1996)** — *Spectroscopic study of twilight intensity in the red region over Ahmedabad after Mt. Pinatubo.* JASTP.
- **Kasten & Young (1989)** — *Revised optical air mass tables and approximation formula.* Appl. Opt.
- **Hulburt (1953)** — *Explanation of the brightness and color of the sky, particularly the twilight sky.* JOSA. → 首次提出臭氧贡献，被 Lange 2023 验证。
- **Mie (1908)** — *Beiträge zur Optik trüber Medien.* Ann. Phys.
- **Strutt (Lord Rayleigh) (1871)** — *On the scattering of light by small particles.* Phil. Mag.

工程级背景：

- **Corfidi (2014)** — *The Colors of Twilight and Sunset.* NOAA SPC publication. → 主要事实综述。
- **Stull (2017)** — *Practical Meteorology* Ch. 22. 开源教科书。
- **WMO International Cloud Atlas** — 云分类国际标准。

## 论文构想（待 Nick 定稿）

把这 5 篇笔记串成一篇 paper，可能的 thesis：

> **"现有日落预测算法（如 SunsetWx, Sunsethue）把必要条件当作可加 modifier，导致在 ['mid/high cloud absent + other conditions favorable'] 的情形下严重高估火烧云概率。本文提出基于云物理 + 大气光学 + 暮光几何的两层 (gate × modifier) 评分框架，使用 NOAA HRRR 操作数据，并在 CONUS 上做端到端验证。"**

章节草图：

1. **Introduction** — 火烧云这个现象的科学/文化意义；现有商业服务的方法论缺口；本文的贡献。
2. **Theoretical Background**（合并 5 篇笔记）
   - 2.1 Atmospheric optics: Rayleigh + Mie + Chappuis（[atmospheric-optics](atmospheric-optics.md)）
   - 2.2 Solar geometry: airmass + 时间窗（[solar-geometry](solar-geometry.md)）
   - 2.3 Cloud physics: WMO 分层 + 三机制（[cloud-physics](cloud-physics.md)）
   - 2.4 Aerosols: 双层逆向作用（[aerosols-and-color](aerosols-and-color.md)）
   - 2.5 Synthesis: necessary vs sufficient（[formation-conditions](formation-conditions.md)）
3. **Methodology**
   - 3.1 Data source: HRRR variables, MERRA-2/OMI for ozone, VIS/HRRR-Smoke for aerosol
   - 3.2 Rule architecture: gate × modifier
   - 3.3 Scoring functions per rule (trapezoidal, geometric combiner)
4. **Implementation** — Python package `predictor/`，Jupyter notebook 验证管道。
5. **Validation** — citizen-science 观察日志对照；与 SunsetWx baseline 的对比。
6. **Discussion & Limitations** — 数据缺口（TOC、分层 AOD）、citizen-science 噪声。
7. **Conclusion + Future Work** — ML 扩展、全球化、色温预测。

**下一阶段研究空白**（可能各自成一篇笔记）：

- `ozone-chappuis.md` — 把 Lange 2023 的 TOC ↔ 颜色定量关系展开；接入 NASA OMI 数据流路径。
- `volcanic-events.md` — `AerosolEnhancement` 的事件触发逻辑；Global Volcanism Program 数据接入。
- `citizen-science-validation.md` — 如何把 observations/log.md 升级成可统计的 ground-truth 数据集；与 Mateshvili 2005 等专业测站的桥接方法。
