# An Operational, Physics-Motivated Framework for Sunset Glow Prediction over the Continental United States

**Working draft v0.1** — arxiv preprint target. Status: introduction + Section 2.1 (Atmospheric Optics) drafted; remaining sections are scaffolded with intent statements. Last updated 2026-05-21.

> Draft note (to be removed before submission): citations are real peer-reviewed papers identified via literature search, but specific numerical extractions (e.g., Lange et al. 2023's 66% ozone contribution) should be verified against the primary source before submission. The thesis—that necessary conditions for sunset glow are mishandled by additive scoring—is grounded in the theoretical literature; quantitative validation against ground-truth observations remains future work and is acknowledged as such in Sections 5 and 6.

## Abstract

Vivid sunset and sunrise glows—colloquially "fire clouds" in Chinese (火烧云)—arise from a narrow set of atmospheric conditions: mid- to high-level clouds illuminated by low-angle sunlight that has traversed a long atmospheric path, with the troposphere clean enough to deliver "unadulterated" red light to the cloud canvas. Existing commercial prediction services (SunsetWx, Sunsethue) score these conditions with weighted-sum combinations of meteorological variables, treating necessary conditions (such as the presence of mid- or high-level clouds) as substitutable for other favorable factors. We show this produces substantial false positives: in an end-to-end run over Washington State's Olympic Peninsula at sunset on 2026-05-20, a weighted-sum predictor returned probability 0.63 across the region despite mid- and high-level cloud coverage of zero. We propose a two-layer scoring architecture in which physically necessary conditions act as multiplicative gates and enhancement variables modulate the result. The framework incorporates ozone Chappuis-band absorption—recently shown by Lange et al. (2023) to dominate twilight blue color at low solar elevations—as an explicit pathway alongside Rayleigh and Mie scattering. We implement the framework as an open-source Python package consuming NOAA's High Resolution Rapid Refresh (HRRR) numerical weather prediction data, and present a preliminary case-study comparison. Full validation against citizen-science ground truth is identified as future work.

**Keywords:** atmospheric optics; twilight color; sunset prediction; numerical weather prediction; operational forecasting; Rayleigh scattering; Mie scattering; ozone Chappuis absorption.

## 1. Introduction

### 1.1 The Phenomenon

A "sunset glow" or "afterglow"—the brief reddening of mid- and high-level clouds in the western sky around sunset—is among the most widely photographed atmospheric phenomena, with significant cultural resonance in many languages (the Chinese 火烧云, the English "afterglow", the Spanish *arrebol*). Beyond aesthetic interest, the conditions producing a vivid sunset glow integrate several distinct branches of atmospheric science: scattering theory (Rayleigh and Mie regimes), gas-phase absorption (ozone Chappuis band), cloud microphysics (the boundary layer's role in attenuation), and the geometry of low-elevation solar paths.

Knowing when and where a sunset glow will occur has practical value for landscape photographers and amateur astronomers, but the underlying integration of variables makes it a useful pedagogical case for atmospheric optics. The problem has the unusual property that necessary conditions (a cloud canvas above the boundary layer, low-angle illumination, a clean troposphere) are difficult to substitute one for another: no amount of cloud will help if the sun is overhead, no amount of solar geometry will help in dense overcast.

### 1.2 Existing Approaches

Three public services currently offer sunset color predictions for North America: SunsetWx, a Penn State–origin model using NOAA Global Forecast System (GFS) data with a 20-factor weighted scoring algorithm \[Forecasting Beauty, 2015\]; Sunsethue, an independent service that publishes cloud-cover, altitude, humidity, and air-quality thresholds in narrative form on its blog; and Skyfire, a closed-source feature of the PhotoPills planning application. None of these services has published a peer-reviewed methodology paper, released scoring weights, or provided systematic validation against ground truth.

Peer-reviewed research on twilight color has focused on the optical mechanism rather than operational prediction. Foundational works include Strutt's (Lord Rayleigh's) 1871 derivation of the $\lambda^{-4}$ molecular scattering dependence \[Strutt, 1871\]; Mie's (1908) treatment of arbitrary-sized particle scattering \[Mie, 1908\]; and Hulburt's (1953) early recognition that ozone absorption contributes substantially to sky color \[Hulburt, 1953\]. Operational synthesis includes Corfidi's (2014) summary for the NOAA Storm Prediction Center \[Corfidi, 2014\], which provides the most authoritative qualitative account of which clouds redden and why.

Recent quantitative work has refined the textbook picture. Lee Jr. and Hernández-Andrés (2003) combined spectral measurements over multiple seasons with radiative transfer modeling to show that twilight's "purple light" cannot be attributed to stratospheric aerosols alone: both tropospheric and stratospheric scattering and extinction are required \[Lee and Hernández-Andrés, 2003\]. Lange, Rozanov, and Burrows (2023) revisited the canonical question of why the sky is blue, demonstrating with the SCIATRAN radiative transfer model that ozone Chappuis-band absorption, not Rayleigh scattering, dominates sky blue color at high solar zenith angles: at total ozone column 300 DU with zenith viewing geometry, ozone contributes 66% of the blue color and Rayleigh only 34% \[Lange et al., 2023\].

The gap addressed by the present work lies between these two strands of literature. Existing operational prediction tools lack a physics-rigorous foundation; peer-reviewed optics literature has not been translated into a deployable forecasting framework.

### 1.3 Contributions

This paper contributes:

1. An explicit catalog of **necessary versus enhancing conditions** for sunset glow formation, grounded in current peer-reviewed atmospheric optics literature (Section 2).
2. A two-layer **gate × modifier scoring architecture** that respects the multiplicatively-gated nature of necessary conditions, avoiding a class of false positives produced by weighted-sum scoring (Section 3).
3. To the authors' knowledge, the first published prediction framework to **incorporate ozone Chappuis-band absorption** as an explicit factor, building directly on Lange et al. (2023) (Section 2.1 and Section 3.2).
4. An **open-source Python implementation** consuming NOAA HRRR data, with end-to-end reproducibility (Section 4, code at \[GitHub URL\]).
5. A **preliminary case study** on the Olympic Peninsula demonstrating the false-positive pathology of additive scoring and motivating the gate × modifier alternative (Section 5).

### 1.4 Outline

Section 2 develops the theoretical background spanning atmospheric optics (2.1), solar geometry (2.2), cloud physics (2.3), and aerosol effects (2.4), concluding with a synthesis of necessary versus enhancing conditions (2.5). Section 3 defines the methodology: data sources, feature derivation, scoring rule design, and the gate × modifier architecture. Section 4 describes the software implementation. Section 5 presents a preliminary case study. Section 6 discusses implications and acknowledges limitations. Section 7 concludes with planned future work, including a citizen-science validation pipeline and a planned extension to global coverage.

## 2. Theoretical Background

### 2.1 Atmospheric Optics: Three Mechanisms of Selective Extinction

The color of a sunset glow is the surviving signature of selective light extinction along the long optical path from the sun to a high-altitude cloud surface. Three independent mechanisms contribute, in order of decreasing wavelength selectivity: molecular Rayleigh scattering, gas-phase Chappuis-band ozone absorption, and aerosol Mie scattering. We treat each in turn and combine them via the Beer–Lambert law.

#### 2.1.1 Rayleigh Scattering

For air molecules with diameters far smaller than the wavelength of visible light ($D \ll \lambda$), the scattering cross section follows Rayleigh's (1871) classical result:

$$\sigma_R(\lambda) = \frac{8 \pi^3 (n^2 - 1)^2}{3 N^2 \lambda^4}$$

where $n$ is the refractive index of air and $N$ is the molecular number density. The defining feature is the $\lambda^{-4}$ dependence: violet light at 400 nm has a scattering cross section approximately $(700/400)^4 \approx 9.4$ times that of red light at 700 nm. Bodhaine et al. (1999) provide a precise treatment incorporating the King correction factor (approximately 1.05, reflecting molecular anisotropy) and refractive-index dispersion; these refinements add roughly 5% to the leading $1/\lambda^4$ term and we do not develop them here \[Bodhaine et al., 1999\].

#### 2.1.2 Mie Scattering

For particles whose size is comparable to the wavelength of light, the Rayleigh approximation breaks down and the full Mie (1908) solution to electromagnetic scattering by a sphere is required. The relevant non-dimensional parameter is the size parameter

$$x = \frac{2 \pi r}{\lambda}$$

with three regimes:

- $x \ll 1$: Rayleigh limit, $\sigma \propto \lambda^{-4}$ as above.
- $x \sim 1$: Mie regime, oscillatory dependence on $\lambda$ with overall near-grayness.
- $x \gg 1$: geometric optics limit.

For visible light ($\lambda \in [0.4, 0.7]\,\mu\text{m}$) and typical tropospheric aerosol radii ($r \in [0.05, 0.5]\,\mu\text{m}$, corresponding to particle diameters $D \in [0.1, 1.0]\,\mu\text{m}$), the size parameter $x$ falls in the range 1–10. This places anthropogenic pollution, mineral dust, and most biomass-burning aerosols squarely in the Mie oscillation regime. Stull (2017, §22.4) summarizes the practical implications in tabular form \[Stull, 2017\]:

| $D/\lambda$ | Diameter | Source | Scattering type |
|---|---|---|---|
| $< 1$ | 0.0001–0.001 µm | Air molecules | Rayleigh |
| $\approx 1$ | 0.01–1.0 µm | Aerosols, smoke, PM2.5 | Mie |
| $> 1$ | 10–100 µm | Cloud droplets | Geometric |

The consequence for sunset color is that tropospheric pollution, far from enhancing red hues, *attenuates the full visible spectrum nearly uniformly*, producing the pale, washed-out sunsets characteristic of urban haze. This is the physical mechanism behind Corfidi's (2014) operational observation that "clean air is, in fact, the main ingredient common to brightly colored sunrises and sunsets" \[Corfidi, 2014\].

#### 2.1.3 Ozone Chappuis Absorption

Ozone has a broad, weak absorption band in the 500–700 nm range known as the Chappuis band, with peak absorption near 600 nm. At solar zenith angles approaching 90° the optical path through the stratospheric ozone layer is approximately 30 times longer than at solar noon, so Chappuis absorption becomes correspondingly more important at sunset.

Lange et al. (2023) used the SCIATRAN radiative transfer model to quantify the relative contributions of Rayleigh scattering versus ozone Chappuis absorption to the perceived blueness of the twilight sky. For 300 DU total ozone column at solar zenith angle 90° and zenith viewing, they find ozone contributes 66% and Rayleigh 34% to the chromaticity displacement \[Lange et al., 2023\]. The contribution varies systematically with total ozone column: 60% at 240 DU, 76% at 500 DU. Their result confirms a long-standing single-scattering estimate by Hulburt (1953) using modern multi-scattering radiative transfer \[Hulburt, 1953\]. This finding modifies the textbook picture in which Rayleigh scattering is the sole explanation for sky blue—and by extension, contributes to the late-stage reddening of sunset glow by removing residual orange-yellow wavelengths in transit through the ozone layer.

#### 2.1.4 Combined Extinction

The three mechanisms combine additively in optical depth. For sunlight along a path of geometric length $L$, the surviving spectral irradiance is

$$\frac{I(\lambda)}{I_0(\lambda)} = e^{-\tau_{\text{total}}(\lambda)}$$

with

$$\tau_{\text{total}}(\lambda) = \tau_R(\lambda) + \tau_{\text{Mie}}(\lambda) + \tau_{O_3}(\lambda)$$

where each term integrates the corresponding extinction coefficient along the path. At low solar elevation, the path length is dominated by horizontal transit through the lower atmosphere (Section 2.2). The wavelength-dependent differences in $\tau_{\text{total}}(\lambda)$ across the visible spectrum constitute the physical answer to the question of why sunsets are red.

### 2.2 Solar Geometry: Air Mass and the Twilight Window

*[Section to be drafted from `research/theory/solar-geometry.md`. Key content: Kasten-Young (1989) air mass formula and tabulation; horizon depression angle $d(h) = \arccos(R/(R+h))$ as the function determining how long clouds at altitude $h$ remain directly illuminated; civil/nautical/astronomical twilight definitions; the resulting ~30 minute viewing window for high cirrus versus ~5 minutes for low stratus.]*

### 2.3 Cloud Physics: Altitude, Type, and the Planetary Boundary Layer

*[Section to be drafted from `research/theory/cloud-physics.md`. Key content: WMO three-tier altitude classification; the planetary boundary layer as locus of attenuating aerosols and water vapor; three independent mechanisms producing the asymmetry between high and low clouds: geometric illumination window, boundary-layer optical attenuation of incoming sunlight, and high optical thickness of low water clouds.]*

### 2.4 Aerosols: Stratospheric Enhancement, Tropospheric Suppression

*[Section to be drafted from `research/theory/aerosols-and-color.md`. Key content: the two-layer aerosol picture; volcanic stratospheric aerosols (Krakatoa 1883, Pinatubo 1991) act in the Rayleigh-like limit and enhance reddening, while tropospheric aerosols (PM2.5, smoke) operate in the Mie regime and suppress contrast; Lee & Hernández-Andrés (2003)'s finding that both layers are required; data sources for tropospheric aerosol observations (HRRR visibility, HRRR-Smoke, OpenAQ, MERRA-2).]*

### 2.5 Synthesis: Necessary vs. Enhancing Conditions

*[Section to be drafted from `research/theory/formation-conditions.md`. Key content: an explicit catalog distinguishing physically necessary conditions (mid- or high-level cloud presence, a clear low-altitude horizon, low tropospheric aerosol loading, low solar elevation) from enhancing modifiers (cloud cover percentage in 40–75% range, cloud structure, total ozone column, humidity in 40–80% range). This taxonomy is the conceptual hinge between the theoretical background and the methodology of Section 3.]*

## 3. Methodology

### 3.1 Data Sources

*[Section to draft: NOAA HRRR (3 km CONUS, hourly) provides cloud cover at high/mid/low layers, 2 m relative humidity, surface visibility, and planetary boundary layer height. NOAA HRRR-Smoke supplies near-surface smoke concentration. GFS provides global coverage at coarser resolution. NASA OMI/TROPOMI provide total ozone column at daily cadence. We document the Herbie library (Blaylock, 2024) for operational HRRR data access.]*

### 3.2 Feature Derivation

*[Section to draft: from raw HRRR variables, we derive the `Features` dataclass: high/mid/low cloud coverage percentages, 2 m relative humidity, solar elevation angle computed via the NREL Solar Position Algorithm (Reda and Andreas, 2004), local sunset time, and air mass via the Kasten-Young (1989) formula. Cite specific variable names and equations.]*

### 3.3 Scoring Rule Design

*[Section to draft: each physically motivated condition is encoded as a `ScoringRule` mapping derived features to a scalar in [0, 1]. We choose trapezoidal membership functions for variables with a "Goldilocks zone" (humidity, mid-high cloud presence) and asymmetric ramps for monotonic conditions (low cloud obstruction, solar angle proximity to sunset). Cite SunsetWx and Sunsethue threshold ranges as starting points and document our refinements with literature anchors (e.g., the 50-75% mid-high cloud cover sweet spot from SunsetWx and the 40-80% humidity range from Sunsethue).]*

### 3.4 The Gate × Modifier Architecture

*[Section to draft, MOST IMPORTANT SECTION: define the two-layer combiner explicitly. Necessary conditions enter a multiplicative gate $G = \prod_i s_i^{w_i}$; enhancing conditions enter a weighted average modifier $M = \sum_j w_j s_j / \sum_j w_j$; the final score is $P = G \cdot M$. The gate goes to zero if any necessary score is zero, regardless of modifier scores. Compare formally with the naive weighted-sum approach. Note the connection to noisy-AND models in probabilistic logic.]*

## 4. Implementation

### 4.1 Software Architecture

*[Section to draft: Python package `predictor/` exposes a Protocol-based public surface (`Predictor`, `WeatherSource`, `ScoringRule`); concrete implementations are pluggable. The architecture supports straightforward extension to GFS, alternative satellite-derived sources, or future ML models without changes to downstream consumers.]*

### 4.2 Code Organization

*[Section to draft: brief tour of `predictor/score.py` (public types), `predictor/features.py` (feature derivation), `predictor/fetch.py` (data sources, with concrete `HRRRSource` using Herbie), `predictor/rules.py` (scoring rules and predictor composition). Include the test suite design (26 unit tests, 1 integration test gated by network marker).]*

### 4.3 Reproducibility

*[Section to draft: open source under \[license TBD\]; environment managed by `uv`; HRRR data caching on disk via Herbie; example Jupyter notebook (`apps/notebook/forecast-map.ipynb`) for end-to-end reproduction. Note the in-memory dataset cache for grid-scale notebook execution.]*

## 5. Preliminary Case Study: Olympic Peninsula, 2026-05-20

*[Section to draft: the Olympic Peninsula run described in the abstract. Methodology: query time 2026-05-20 20:30 PDT (= 2026-05-21 03:30 UTC), bounding box covering Forks, La Push, and Ruby Beach in Washington State. Result: weighted-sum predictor returns ~0.63 uniformly despite HRRR-reported mid- and high-cloud coverage of 0%. Decomposition of the score by rule shows the false positive originates from low cloud obstruction = 1, solar angle = 1, and humidity = 0.6 dominating the weighted sum. Re-run with the proposed gate × modifier produces values approaching zero, consistent with the physical impossibility of fire cloud formation in the absence of canvas clouds. Include a side-by-side figure (placeholder).]*

## 6. Discussion

### 6.1 Implications for Atmospheric Science

*[Section to draft: the gate × modifier framework generalizes beyond sunset prediction to any prediction problem in which necessary conditions cannot substitute for enhancing modifiers. Examples include thunderstorm initiation (CAPE + trigger + moisture all necessary), aurora visibility (geomagnetic activity + clear sky + darkness all necessary), and stratospheric ozone hole formation (cold + chlorine + sunlight all necessary). The mathematical pitfall of treating necessary conditions additively is widespread in operational forecasting heuristics.]*

### 6.2 Comparison with Existing Services

*[Section to draft: SunsetWx and Sunsethue both publish enough information to permit qualitative reconstruction of their scoring approach. Both appear to use additive scoring without explicit gating, suggesting the false-positive pathology we describe is potentially widespread in commercial sunset prediction. We do not have access to ground truth comparison and decline to make strong claims about relative accuracy. Section 7 outlines our planned citizen-science validation pipeline.]*

### 6.3 Open Questions

*[Section to draft: ozone column variability and its operational data accessibility (OMI/TROPOMI are not real-time); aerosol layer separation (stratospheric vs. tropospheric) is not directly observable from HRRR; the choice of trapezoidal versus more flexible scoring functions (e.g., Gaussian, sigmoid) for individual rules. We also note the cos(lat) correction required for nearest-grid lookup in our HRRR fetch implementation, a subtle issue at mid-to-high latitudes.]*

## 7. Conclusion and Future Work

### 7.1 Summary

*[Section to draft: recap the contributions and the case study finding.]*

### 7.2 Citizen-Science Validation Pipeline

*[Section to draft: design for a structured ground-truth dataset built from observation log entries; integration with platforms such as iNaturalist or a dedicated submission portal; statistical methodology for handling observer bias and geographic non-uniformity.]*

### 7.3 ML Extension

*[Section to draft: once a labeled dataset exists, the `Predictor` protocol allows a drop-in `MLPredictor` implementation. We discuss the likely architecture (gradient-boosted trees on the existing feature set, or a simple feed-forward network) and the relationship to the rule-based scoring function (the latter as an interpretable baseline).]*

### 7.4 Global Expansion

*[Section to draft: replacement of `HRRRSource` with `GFSSource` (global, coarser) for non-CONUS coverage. Tradeoffs in resolution and operational latency.]*

## Acknowledgments

*[To be added: any data providers, code library authors (Herbie, xarray, cfgrib, astral), reviewers.]*

## References

\[Citations are real peer-reviewed papers identified via literature search. Specific numerical extractions should be verified against primary sources before submission. To be converted to BibTeX before submission.\]

- Blaylock, B. K. (2024). *Herbie: Retrieve NWP model data*. <https://github.com/blaylockbk/Herbie>.
- Bodhaine, B. A., Wood, N. B., Dutton, E. G., & Slusser, J. R. (1999). On Rayleigh optical depth calculations. *J. Atmos. Oceanic Technol.*, 16, 1854–1861.
- Corfidi, S. F. (2014). *The Colors of Twilight and Sunset*. NOAA Storm Prediction Center publication.
- Hulburt, E. O. (1953). Explanation of the brightness and color of the sky, particularly the twilight sky. *J. Opt. Soc. Am.*, 43(2), 113–118.
- Husar, R. B., et al. (2000). Asian dust events of April 1998. *J. Geophys. Res.*, 106(D16), 18317–18330.
- Kasten, F., & Young, A. T. (1989). Revised optical air mass tables and approximation formula. *Applied Optics*, 28(22), 4735–4738.
- Lange, A., Rozanov, V. V., & Burrows, J. P. (2023). Revisiting the question "Why is the sky blue?" — A radiative transfer model study. *Atmos. Chem. Phys.*, 23, 14829–14851.
- Lee, R. L. Jr., & Hernández-Andrés, J. (2003). Measuring and modeling twilight's purple light. *Applied Optics*, 42(3), 445–457.
- Liao, Z., et al. (2024). Visibility-derived aerosol optical depth over global land from 1959 to 2021. *Earth Syst. Sci. Data*, 16, 3233–3252.
- Mateshvili, N., et al. (2005). Twilight sky brightness measurements as a useful tool for stratospheric aerosol investigations. *J. Geophys. Res. Atmos.*, 110, D09209.
- Mie, G. (1908). Beiträge zur Optik trüber Medien, speziell kolloidaler Metallösungen. *Annalen der Physik*, 330, 377–445.
- Mishra, M. K., et al. (1996). Spectroscopic study of twilight intensity in the red region over Ahmedabad (23 °N) after the Mt. Pinatubo eruption. *J. Atmos. Solar-Terr. Phys.*, 58, 1591–1598.
- Reda, I., & Andreas, A. (2004). *Solar Position Algorithm for Solar Radiation Applications*. NREL/TP-560-34302.
- Ribeiro, J. R., et al. (2024). Explaining the green volcanic sunsets after the 1883 eruption of Krakatoa. *Atmos. Chem. Phys.*
- Rozenberg, G. V. (1966). *Twilight: A Study in Atmospheric Optics*. Plenum (English ed.); Springer 2012 reprint.
- Strutt, J. W. (Lord Rayleigh) (1871). On the scattering of light by small particles. *Philosophical Magazine*, 41, 447–454.
- Stull, R. (2017). *Practical Meteorology: An Algebra-based Survey of Atmospheric Science*. Open textbook.
- Symons, G. J. (Ed.) (1888). *The Eruption of Krakatoa, and Subsequent Phenomena*. Royal Society of London.
- World Meteorological Organization. *International Cloud Atlas*. <https://cloudatlas.wmo.int/>.

## Appendix A: Rule Weights and Parameters

*[To be added: a table of all `ScoringRule` parameters in the current implementation, their values, and the literature anchor for each.]*

## Appendix B: Code Listings

*[To be added: minimal code excerpts showing the `Predictor` protocol, the `RuleBasedPredictor.score` method, and the `geometric_combiner` function.]*
