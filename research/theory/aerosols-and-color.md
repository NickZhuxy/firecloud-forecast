# 气溶胶对色彩的影响

> 为什么"火山喷发让日落更红"和"城市雾霾让日落更暗淡"两件事都对？答案在两层气溶胶（平流层 vs 对流层）的粒径分布不同——它们落在 [atmospheric-optics](atmospheric-optics.md) 散射区谱的相反两端。本笔记用 Krakatoa (1883)、Pinatubo (1991) 等火山案例的实测数据量化这层区别，并落到 `predictor/` 的数据源选择。
>
> stage: claude-draft（事实部分依据 peer-reviewed 案例研究；判断部分待 Nick 复核）

## 概念

地球大气里存在**两层物理上分开的气溶胶库**：

| 层 | 高度 | 主要成分 | 典型粒径 $r$ | 散射区 |
|---|---|---|---|---|
| **平流层** (stratosphere) | 12–50 km | 火山硫酸盐液滴、陨石尘 | 0.05–0.2 μm | 接近 **Rayleigh 极限** |
| **对流层** (troposphere) | 0–12 km，绝大部分在 PBL（0–2 km） | 人为污染（硫酸盐、黑碳、有机物）、矿物尘、海盐、生物烟雾 | 0.1–10 μm，主体 0.5–2 μm | **Mie 振荡区** |

回顾 [atmospheric-optics](atmospheric-optics.md) 的散射区谱：

- Rayleigh 区（粒径 $\ll \lambda$）：$\sigma \propto \lambda^{-4}$，**选择性散射蓝紫**，把红留下→**增强**红橙
- Mie 区（粒径 $\sim \lambda$）：**波长无关**，所有颜色等量被散射→**整体压暗、无色调偏移**

**关键结论**：两层气溶胶在火烧云上做相反的事——

- **平流层气溶胶**：粒径在 Rayleigh 极限附近，行为像"额外的空气分子"，增强长光路下的瑞利红化。
- **对流层气溶胶**：粒径在 Mie 振荡区，把整个可见光谱拖向灰白，**淹没**而非增强红橙。

这就是 Corfidi (2014) 那句 "clean air is the main ingredient" 的物理基础——这里的"clean"特指对流层清洁，而非整个大气柱无气溶胶。

## 关键案例（peer-reviewed）

### Krakatoa 1883

1883 年 8 月 Krakatoa 大爆发把估计 20 km³ 物质注入大气，其中相当部分以 SO₂ 形式上升到平流层，氧化成硫酸盐液滴。Symons (1888) 编辑的英国皇家学会专著《The Eruption of Krakatoa, and Subsequent Phenomena》记载了全球范围的**红绿色日落**和 afterglow 持续到 1884–1886 年。

Ribeiro 等 (2024, *Atmos. Chem. Phys.*) 用现代辐射传输模型重新分析了"绿色火山日落"现象，提出粒径分布在 0.1–0.3 μm 时，特定光路几何下可以在可见光谱里造成**绿色窗口**——这是平流层 Rayleigh-like 行为的副产品。

### Pinatubo 1991

1991 年 6 月 Pinatubo 喷发是 20 世纪最大注入事件之一，向平流层注入约 20 Mt SO₂，全球 AOD（550 nm）峰值约 0.15（背景值 ~0.01–0.02）。

- Mateshvili et al. (2005, *J. Geophys. Res.*) 在格鲁吉亚 Abastumani 天文台对 9 个波长（422–820 nm）做了 1991–1993 年的暮光多光谱测量，太阳天顶角 89°–107°，明确看到平流层气溶胶增长在暮光亮度-SZA 曲线上引起的"驼峰"。气溶胶 feature 强度在 1991 年 12 月 / 1992 年 1 月达到峰值。
- Mishra et al. (1996, *J. Atmos. Solar-Terr. Phys.*) 在印度 Ahmedabad 测量近红外暮光强度，证实平流层气溶胶层从赤道扩散到中纬度的时间序列。
- 同一时段，全球范围观察者报告日落色彩异常浓郁、afterglow 持续时间显著延长——直接验证 Lee 2003 后来的"必须有平流层贡献"的论点。

### 对流层污染日常案例

城市 PM2.5 浓度 > 50 μg/m³ 时 AOD（550 nm）通常 > 0.5，柱内 boundary layer 部分占主导。这样的天气下日落几乎不出现火烧云——光从水平方向穿过 PBL 之前已损失大半。Husar et al. (2000) 等 SeaWiFS / MODIS 卫星反演显示亚洲沙尘事件期间整个东亚 AOD 升至 1.0+，配合的日落观测记录都是暗淡灰粉而非红橙。

## 数据接入路径

火烧云预测项目要把"气溶胶"做成可观测/可预测的输入变量，对应几个可用数据源：

| 变量 | 数据源 | 时空分辨率 | 注意 |
|---|---|---|---|
| **柱总 AOD** (550 nm) | MODIS / VIIRS 卫星反演；NASA GIOVANNI；MERRA-2 reanalysis | 卫星 1–10 km，每日；MERRA-2 0.5° hourly | 受云污染，云下 AOD 不可用 |
| **平流层 AOD** | OSIRIS、OMPS、SAGE III 卫星掩星 | 卫星 ~100 km，每日 | 火山事件期价值高，平时为背景 ~0.01 |
| **地表 PM2.5** | OpenAQ、EPA AirNow（美国）、中国国家空气质量监测站 | 站点级，逐小时 | PM2.5 是 AOD 的良好代理但受 PBL 高度调节 |
| **HRRR-Smoke** | NOAA HRRR-Smoke 模型，逐小时 3 km | CONUS only | 给地表 + 柱积分烟雾浓度，是 PM2.5 火灾源的强代理 |
| **能见度 (VIS)** | HRRR 直接输出 | CONUS，3 km，逐小时 | 与 AOD 反相关：VIS 高 → AOD 低 |
| **总臭氧柱 (TOC)** | NASA OMI / TROPOMI 卫星；GFS `TOZNE` | 卫星 0.25° 每日；GFS 0.25° hourly | Lange 2023 提出的第三贡献机制，HRRR 无 |

**当前实现**：优先使用 Open-Meteo/CAMS 的 550 nm AOD；AOD 缺失时才把地表能见度作为低置信度回退，并避免把雾或近地湿度误判成整层气溶胶。

**下一步**：沿日落方向读取 AOD，而不是只看观察点；对烟雾和普通背景气溶胶保留不同诊断来源。

**后续研究**：NASA OMI/TROPOMI 臭氧柱和分层气溶胶可改善颜色与平流层贡献诊断，但它们属于独立、低频的数据流，不应塞进普通天气请求。

## 资料来源

1. **Lee, R. L. Jr., & Hernández-Andrés, J. (2003).** *Measuring and modeling twilight's purple light.* *Applied Optics*, 42(3), 445–457. — 见 [atmospheric-optics](atmospheric-optics.md)。论证"平流层 + 对流层共同作用"的关键。
2. **Mateshvili, N., et al. (2005).** *Twilight sky brightness measurements as a useful tool for stratospheric aerosol investigations.* *J. Geophys. Res. Atmos.*, 110, D09209. <https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2004JD005512> — Pinatubo 后多波长暮光测量。
3. **Mishra, M. K., et al. (1996).** *Spectroscopic study of twilight intensity in the red region over Ahmedabad (23 °N) after the Mt. Pinatubo eruption.* *J. Atmos. Solar-Terr. Phys.*, 58, 1591–1598. <https://www.sciencedirect.com/science/article/abs/pii/S1364682696000958> — 红光波段的 Pinatubo 案例。
4. **Ribeiro, J. R., et al. (2024).** *Explaining the green volcanic sunsets after the 1883 eruption of Krakatoa.* *Atmos. Chem. Phys.* <https://acp.copernicus.org/articles/24/2415/2024/> — Krakatoa 绿色日落的现代辐射传输解释。
5. **Symons, G. J. (Ed.) (1888).** *The Eruption of Krakatoa, and Subsequent Phenomena.* Royal Society of London. — 19 世纪的全球观察集录，原始数据来源。
6. **Husar, R. B., et al. (2000).** *Asian dust events of April 1998.* *J. Geophys. Res.*, 106(D16), 18317–18330. — SeaWiFS 反演的大尺度对流层尘事件案例。
7. **Liao, Z., et al. (2024).** *Visibility-derived aerosol optical depth over global land from 1959 to 2021.* *Earth Syst. Sci. Data*, 16, 3233–3252. <https://essd.copernicus.org/articles/16/3233/2024/> — 能见度→AOD 的全球反演方法，是 `CleanAirGate` 用 HRRR `VIS` 做代理的依据。
8. **Pravosudova, A. P., et al. (2023).** *PM2.5 as a proxy for aerosol optical depth in night sky brightness models.* *Mon. Not. R. Astron. Soc.* — PM2.5 ↔ AOD 关系的当代综述。

## 对预测规则的启示

把上面四类气溶胶物理对回 `predictor/` 的具体改动：

1. **`CleanAirGate` 的实施次序**：
   - **第 0 阶（立即）**：用 HRRR `VIS`（地表能见度，单位 m）做对流层 AOD 的负代理。阈值建议：
     - $\mathrm{VIS} > 20$ km → score = 1.0
     - $5 < \mathrm{VIS} < 20$ km → 线性
     - $\mathrm{VIS} < 5$ km → score = 0
   - **第 1 阶**：接入 HRRR-Smoke 的 `MASSDEN` / `COLMD`（地表烟雾密度 / 柱密度），夏季野火季节有效。
   - **第 2 阶**：接入 MERRA-2 或 OMI 的卫星 AOD，全球扩展时启用。

2. **不要把"气溶胶"做成单一 gate**。Lee 2003 表明背景平流层气溶胶反而**支持**火烧云生成。所以严格的 `CleanAirGate` 只应惩罚**对流层**异常高 AOD，不要惩罚平流层贡献——这意味着如果未来有了卫星反演的分层 AOD 数据，要区分 trop/strato。

3. **PBL 高度调节 PM2.5 → AOD 的转换**：同一 PM2.5 浓度，PBL 厚度大时柱总 AOD 大、薄时小。`HPBL` 是 HRRR 直接输出的变量；如果将来用 PM2.5，应该构造 `PM2.5 × HPBL` 作为派生特征。

4. **`AerosolEnhancement`（火山事件期开启的 modifier）**：火山喷发后 0–18 个月平流层 AOD 异常升高，火烧云会显著增强。这是一个**事件触发**的 modifier，不是常态规则。可以用 SAGE III / OMPS 的近实时反演判定，或简单查询 Global Volcanism Program 的最近 18 个月 VEI ≥ 4 事件列表。

5. **色彩诊断作为独立研究问题**：本笔记 + atmospheric-optics 提示红、橙、粉、紫的差异取决于对流层/平流层 AOD、臭氧柱和米氏粒径分布。现阶段先输出可解释的光学变量，不把颜色分类并入主评分。

## 论文章节种子

这一篇可以扩成 paper 的 "Aerosol Effects" 小节，要补的：

- **Krakatoa 全球记录数据可视化**：1883–1886 年的观察日记按地理分布画热力图（如果能数字化 Symons 1888 的原始数据，这是 paper 的"历史 + 现代"亮点）。
- **Pinatubo 全球 AOD 时间序列**：从 1991-06 到 1993-12，用 SAGE II 或 OMPS 卫星数据，叠加全球暮光观察报告。
- **现代 PM2.5 → 火烧云抑制案例**：比较北京 2013-01 大霾、加州 2020-09 山火和印度恒河平原烧荒季的公开 AOD、卫星云产品与专业观测资料。
- **Lee 2003 Goldilocks 结论的复核**：使用公开 AOD 再分析、卫星云产品和历史专业观测检查 0.05–0.15 区间；在获得足够独立证据前不把它写成硬阈值。

延伸：

- [atmospheric-optics](atmospheric-optics.md)：本笔记的"两层粒径不同"完全继承自 atmospheric-optics 的散射区谱。
- [formation-conditions](formation-conditions.md)：本笔记给 `CleanAirGate` 提供了具体的代理变量和阈值。
- 待考虑新笔记 `volcanic-events.md`：跟踪近期 VEI ≥ 4 事件、SAGE III / OMPS 数据接入、`AerosolEnhancement` modifier 的事件触发逻辑。
