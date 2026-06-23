# 瑞利散射与米氏散射

> 火烧云红色的物理来源不止瑞利散射一项。这一篇把三种主要的大气消光机制——分子瑞利散射、气溶胶米氏散射、臭氧 Chappuis 吸收——的量化关系厘清，并解释为什么"清洁空气"是个 Goldilocks 变量、而不是单调"越清洁越好"。
>
> stage: claude-draft（可作为 paper "Theoretical Background" 章节的基础。事实部分依据 peer-reviewed 一手源；判断部分待 Nick 复核）

## 概念

火烧云的色彩源于"原色阳光"在穿越大气时被选择性消光，剩下的光抵达云层、被反射给观察者。三种主要机制按对波长的依赖排序：

| 机制 | 媒介 | 波长依赖 | 主导粒径 |
|---|---|---|---|
| **瑞利散射 (Rayleigh)** | 空气分子 | $\sigma \propto \lambda^{-4}$ | $D \ll \lambda$ (~ 0.001 μm) |
| **米氏散射 (Mie)** | 气溶胶颗粒 | 弱（接近灰色） | $D \sim \lambda$ (0.01–1 μm) |
| **臭氧 Chappuis 吸收** | $\mathrm{O_3}$ 分子 | 选择性带状，主峰 ~600 nm | 分子级 |
| 几何反射 | 云滴、雨滴 | 无依赖 | $D \gg \lambda$ (> 10 μm) |

历史上"瑞利单独解释蓝天和红日落"是教科书结论。Lange et al. (2023) 用辐射传输模拟直接修订了这一说法：在太阳天顶角 $90°$（日落时刻）、臭氧柱 300 DU 时，**66% 的天顶天空蓝色由臭氧 Chappuis 吸收贡献，仅约 34% 来自瑞利散射**。

## 数学

### 瑞利散射

Strutt (1871) 给空气分子单粒子散射截面：

$$\sigma_R(\lambda) = \frac{8\pi^3 (n^2 - 1)^2}{3 N^2 \lambda^4}$$

其中 $n$ 是空气折射率、$N$ 是分子数密度。**核心事实**：$\sigma_R \propto 1/\lambda^4$，紫光 (400 nm) 散射截面是红光 (700 nm) 的 $(700/400)^4 \approx 9.4$ 倍。

精确处理还需加 *King correction factor*（约 1.05，考虑分子各向异性）和折射率色散修正。这些在 $1/\lambda^4$ 主导项之上是 ~5% 量级，详见 Bodhaine et al. (1999)；本笔记不展开。

### 米氏散射

Mie (1908) 给球形粒子任意大小下的精确散射，无解析闭式。实践中用**尺寸参数**

$$x = \frac{2\pi r}{\lambda}$$

来分类：

- $x \ll 1$：回到瑞利极限，$\sigma \propto \lambda^{-4}$
- $x \sim 1$：米氏振荡区，整体接近"灰色"散射
- $x \gg 1$：几何光学极限

对可见光 ($\lambda = 0.4$–$0.7$ μm) 和典型对流层气溶胶 ($r = 0.05$–$0.5$ μm，即 $D = 0.1$–$1.0$ μm)：$x$ 落在 1–10，处于米氏振荡区。Stull (*Practical Meteorology* §22.4) 列了对应的物理图景：

| $D/\lambda$ | 粒径 | 来源 | 散射类型 |
|---|---|---|---|
| $< 1$ | 0.0001–0.001 μm | 空气分子 | Rayleigh |
| $\approx 1$ | 0.01–1.0 μm | 气溶胶、烟雾、PM2.5 | Mie |
| $> 1$ | 10–100 μm | 云滴 | 几何光学 |

### 臭氧 Chappuis 吸收

臭氧分子在 500–700 nm 有一个宽吸收带（**Chappuis band**），主峰约 600 nm。日落时阳光走的水平路径穿过的臭氧柱比正午高约 30 倍（见 [solar-geometry.md](solar-geometry.md) 的 airmass 推导），因此 Chappuis 吸收在消光预算里的占比从正午的 < 5% 升到 $\mathrm{SZA} = 90°$ 时的 66%。

Lange et al. (2023) 给出的天空蓝色臭氧/瑞利分解（天顶视向）：

| 总臭氧柱 (TOC) | 臭氧贡献 | 瑞利贡献 |
|---|---|---|
| 240 DU | 60% | 40% |
| 300 DU | 66% | 34% |
| 500 DU | 76% | 24% |

这个量化关系直接接到火烧云的"为什么是红"——日落光路在 Chappuis 带的损耗，把残余光从橙黄进一步往纯红推。

### 消光累积（Beer-Lambert）

光强沿路径衰减 $I/I_0 = e^{-\tau}$，其中 $\tau = \int \sigma N \, ds$。多机制时

$$\tau_{\text{total}}(\lambda) = \tau_R(\lambda) + \tau_M(\lambda) + \tau_{\mathrm{O_3}}(\lambda)$$

日落几何下 $\tau_{\text{total}}$ 在可见光不同波长上的差异，就是"火烧云为什么红"的最终答案。

## 应用到火烧云

把上面三个机制对到 NOAA SPC 综述 (Corfidi 2014) 和 Lee & Hernández-Andrés (2003) 的实测：

1. **瑞利**：长光路下紫蓝大幅散射出去——红化的第一主因。
2. **米氏（对流层气溶胶 0.5–1 μm）**：弱波长依赖。**关键含义**——对流层污染**不会增强**红色，而是把整个可见光谱均匀地拖到暗灰白。这是 Corfidi 说 "clean air is the main ingredient" 的物理来源。
3. **臭氧 Chappuis**：吸收掉残余的橙黄绿（500–700 nm 中部），让剩下的光偏向更纯的红/紫——Lange 2023 提出、教科书没充分讨论的第三机制。
4. **平流层气溶胶**：来自火山的细小尘粒 ($r$ < 0.1 μm，接近瑞利极限) 能增强红色。Lee 2003 同意这点，但强调：

> "background stratospheric aerosols by themselves do not redden sunlight enough to cause the purple light's reds. Furthermore, scattering and extinction in both the troposphere and the stratosphere are needed to explain most purple lights."

这一句是关键。它意味着对流层不应被简单当成"越清洁越好"——存在**多重散射通路**的需求。完全无气溶胶的对流层在 Lee 的模型里也得不到典型的紫光红分量。

注意：Lee 2003 讨论的"紫光"是日落后天空背景的色彩，与火烧云"中高云被红化反射"的现象在物理上分担同一基础，但侧重不同。火烧云作为**反射现象**对 AOD 的容忍度更低——一旦低层 AOD 把直射光衰减到云层之前，云的画布就没法被照亮。

## 资料来源

1. **Lange, A., Rozanov, V. V., & Burrows, J. P. (2023).** *Revisiting the question "Why is the sky blue?" — A radiative transfer model study.* *Atmos. Chem. Phys.*, 23, 14829–14851. <https://acp.copernicus.org/articles/23/14829/2023/> — peer-reviewed 量化臭氧 Chappuis 贡献；本笔记的 66%/34% 分解出处。
2. **Lee, R. L. Jr., & Hernández-Andrés, J. (2003).** *Measuring and modeling twilight's purple light.* *Applied Optics*, 42(3), 445–457. <https://opg.optica.org/ao/abstract.cfm?uri=ao-42-3-445> — 实测 + 辐射传输建模；推翻"背景平流层气溶胶单独解释紫光"的旧说。
3. **Stull, R. (2017).** *Practical Meteorology: An Algebra-based Survey of Atmospheric Science*, Ch. 22 (Atmospheric Optics). 开源教科书，LibreTexts 镜像：<https://geo.libretexts.org/Bookshelves/Meteorology_and_Climate_Science/Practical_Meteorology_(Stull)/22%3A_Atmospheric_Optics/> — 散射区域分类表、Rayleigh 公式、Beer-Lambert 处理。
4. **Strutt, J. W. (Lord Rayleigh) (1871).** *On the scattering of light by small particles.* *Philosophical Magazine*, 41, 447–454. — 原始 $\lambda^{-4}$ 推导。
5. **Mie, G. (1908).** *Beiträge zur Optik trüber Medien, speziell kolloidaler Metallösungen.* *Annalen der Physik*, 330, 377–445. — 米氏理论原始论文。
6. **Bodhaine, B. A., Wood, N. B., Dutton, E. G., & Slusser, J. R. (1999).** *On Rayleigh optical depth calculations.* *J. Atmos. Oceanic Technol.*, 16, 1854–1861. — King correction factor 等修正项的精确处理（备查）。
7. **Corfidi, S. F. (2014).** *The Colors of Twilight and Sunset.* NOAA SPC. — 见 [formation-conditions](formation-conditions.md)。
8. **Rozenberg, G. V. (1966).** *Twilight: A Study in Atmospheric Optics.* (Russian original 1963; English translation Plenum 1966, reprinted Springer 2012). — 经典专著，所有后续暮光光学研究的起点。

## 对预测规则的启示

把上面的物理对回 `predictor/` 的具体改动：

1. **`CleanAirGate` 是 Goldilocks 而非单调 gate**。Lee 2003 表明对流层 AOD = 0 在紫光现象里不是最优。但火烧云作为**反射现象**对 AOD 的容忍度更低（云的画布需要直射光），所以最优区在很低但非零的 AOD——用**梯形隶属函数**而非线性单调下降。数据源待挖：HRRR 不直接给 AOD，可用能见度 `VIS` 做反代理（VIS 高 → AOD 低），或并入 MERRA-2 / OpenAQ / EPA AirNow。
2. **臭氧柱 TOC 作为候选新特征**。Lange 2023 的量化（240 DU → 60%, 300 DU → 66%, 500 DU → 76% 臭氧贡献）说明 TOC 在约 30% 范围内显著改变颜色。可从 NASA OMI/TROPOMI 或包含总臭氧的模式产品获取；在数据时效与空间匹配方案明确前，它只进入诊断研究，不进入主评分。
3. **米氏区粒径范围 0.5–1 μm 对应 PM2.5**。CleanAirGate 的代理变量可以用 PM2.5（粒径 ≤ 2.5 μm 恰好覆盖米氏区主体）的预报或实测。OpenAQ、EPA AirNow 提供这种数据；HRRR-Smoke 给地表烟雾浓度。
4. **~600 nm Chappuis 中心**意味着火烧云的橙红波段恰好与臭氧吸收峰重叠。Lange 2023 的隐含含义：**高臭氧柱（300+ DU）让火烧云更偏纯红、低臭氧柱让它偏黄橙**。这是一个可观测的色彩诊断量，未来 ML 阶段可作为预测器的目标变量之一（不只是 binary "出火烧云 Y/N"，还可以预测色温）。

## 论文章节种子

这一篇可以直接扩展成 paper 的 "Theoretical Background" 章节，要补的：

- 三种机制各自的 wavelength-resolved 数值表（Lange 2023 Figure 5 的数据）
- 一张"$\tau_{\text{total}}$ 沿日落光路的波长依赖"复合图——把三个贡献叠加画出来，红色为什么残留就一目了然
- 一段历史脉络：Rayleigh 1871 → Mie 1908 → Hulburt 1953 (首次提出臭氧贡献) → Rozenberg 1966 → Lee 2003 → Lange 2023。这条线索本身可以构成 paper 的 "Related Work"
- Lange 2023 vs Hulburt 1953 的对比应作为 paper 的"现有研究"小节，说明这条道路的里程碑

延伸：

- [solar-geometry.md](solar-geometry.md)：airmass 公式 + 太阳高度角到水平路径长度的换算。本笔记的所有"长路径"论证都依赖这层几何。
- [aerosols-and-color.md](aerosols-and-color.md)：火山平流层气溶胶（Krakatoa, Pinatubo）案例的实测数据；OpenAQ / EPA AirNow 数据流接入路径。
- 待考虑新笔记 `ozone-chappuis.md`：Chappuis 吸收带的精确光谱学；TOC 时空变化；NASA OMI 数据接入。这是 Lange 2023 引出的、原 spec 里没有的方向。
