# Theory 索引

> 全部笔记 `stage: claude-draft`（事实层 Claude 写、判断层等 Nick 复核）。每篇都以"对预测规则的启示"小节结尾，把研究结论接回 [predictor/rules.py](../../predictor/rules.py)。可作为论文 "Theoretical Background" 章节的基础。

> 🎯 **权威目标模型**：`research/人工火烧云预报速成（长三角适用）.pdf`（外部作者手册）含完整的火烧云几何模型、消光/颜色物理与操作化预报流程，**权威性高于本目录的 claude-draft 笔记**——是项目逆向逼近的目标。
>
> 📋 **[single-point-fidelity-audit.md](single-point-fidelity-audit.md)** — Spike #56 单点物理保真度审计：对照上述手册逐环节列出"当前简化 vs 真实物理"的差距，给出有优先级的拟真 backlog（几何/云/气溶胶/散射四类），供 Epic #54 的 #57 立项。**优先级待 Nick 复核定稿。**

## 按因子推导（#57 拟真增强）

每个拟真因子落地前的物理推导 + 假设 + 验证设计（接回审计对应条目）：

| 文件 | 因子 | 主题 | 手册依据 |
|---|---|---|---|
| [fa-a2-path-extinction](fa-a2-path-extinction.md) | FA-A2 | 沿光线逐列路径消光（替代沿程 AOD 均值）；逐列等效不透明地表 | §1.3.1–4 / §4.1.1 / §2.4.2 |
| [fa-t1-boundary-advection](fa-t1-boundary-advection.md) | FA-T1 | 云边界按云高风平移到日落时刻（Δt=日落−valid_time）| §4.1.1 / §4.2 |

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

> **“加权和会让有利变量补偿缺失的必要条件，从而高估火烧云。当前框架用 gate × modifier 保留物理不可替代性，并通过公开 NWP、空间几何、离线情景和多源资料逐步验证。”**

章节草图：

1. **Introduction** — 火烧云这个现象的科学/文化意义；现有商业服务的方法论缺口；本文的贡献。
2. **Theoretical Background**（合并 5 篇笔记）
   - 2.1 Atmospheric optics: Rayleigh + Mie + Chappuis（[atmospheric-optics](atmospheric-optics.md)）
   - 2.2 Solar geometry: airmass + 时间窗（[solar-geometry](solar-geometry.md)）
   - 2.3 Cloud physics: WMO 分层 + 三机制（[cloud-physics](cloud-physics.md)）
   - 2.4 Aerosols: 双层逆向作用（[aerosols-and-color](aerosols-and-color.md)）
   - 2.5 Synthesis: necessary vs sufficient（[formation-conditions](formation-conditions.md)）
3. **Methodology**
   - 3.1 Data sources: Open-Meteo baseline, GFS pressure levels, satellite/radar correction
   - 3.2 Rule architecture: gate × modifier
   - 3.3 Scoring functions per rule (trapezoidal, geometric combiner)
4. **Implementation** — Python package `predictor/` 与本地 SunsetWx 科研制图产物。
5. **Validation** — 离线物理情景、公开资料、专业观测和多源同时次对照。
6. **Discussion & Limitations** — 数据缺口（TOC、分层 AOD、真实云底）与模式不确定性。
7. **Conclusion + Future Work** — 全国精细化、垂直剖面和卫星临近订正。

**下一阶段研究空白**（可能各自成一篇笔记）：

- `ozone-chappuis.md` — 把 Lange 2023 的 TOC ↔ 颜色定量关系展开；接入 NASA OMI 数据流路径。
- `volcanic-events.md` — `AerosolEnhancement` 的事件触发逻辑；Global Volcanism Program 数据接入。
- `validation-sources.md` — 可自动化使用的公开探空、卫星、雷达和专业观测资料，以及各自的误差边界。
