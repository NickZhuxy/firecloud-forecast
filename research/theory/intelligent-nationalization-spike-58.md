# 智能全国化方案研究（Spike #58）

> stage: codex-spike  
> Scope: Epic #54 / Issue #58。本文只给研究结论和 #59 推荐路线，不改生产全国评分代码。

## 1. 问题定义

当前全国图的 `grid_score` 是快速 overview：逐格使用低/中/高云量、湿度、能见度/AOD，并假设每个格点都在自己的日出/日落窗口内。它刻意省略了单点全物理里最重的部分：

- 观测点垂直廓线诊断出的真实云层、光学厚度与画布高度；
- `SunwardIlluminationGate` 的日向边界、低云/气溶胶路径遮挡；
- 2-D sunward cross-section 上的抛物线光追；
- 上游路径 AOD 与本地 AOD 的区分。

#58 的核心问题是：如何把这些单点保真度，以可接受算力带到约 25 km 全国网格。#59 再按本文路线改 `grid_score` / `national_field`。

## 2. 基准与误差度量

基准真值定义为当前详细单点路径：

```text
score_point_with_cube(..., distances_km=0..800 by 25 km, azimuth=270 deg, per-column AOD)
```

离线证据来自可复现实验脚本：

```bash
PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib \
  uv run --no-sync python research/experiments/nationalization_spike.py
```

实验场是合成但空间结构化的 9 x 14 小网格：西缘中高云盾、两个低云遮挡区、空间变化 AOD。它不是实况评估，但能稳定暴露全国化近似的典型偏差：overview 高估、边界稀疏候选、上游气溶胶/低云挡光、锚点复用漏掉窄候选带。

度量：

- `MAE/RMSE/P90/Max`：逐格概率误差。
- `F1/FP/FN`：以产品显示阈值 `probability >= 0.50` 判候选区。
- `gradient_mae`：相邻格点概率梯度误差，衡量空间结构和边界形态。
- `relative_physics_cost`：相对 25 km 完整单点路径的物理成本。overview 无压力层光追，记为近似 0.02；1-D screen 记为 0.18；粗光追按列数归一。

基准真值本轮输出：`126` 点，`probability` 范围 `0.0000..0.6991`，`>=0.50` 候选比例 `3.17%`，25 km 完整路径 wall time `~300 ms`（离线合成，真实 GFS I/O 另算）。

## 3. 候选方案与曲线

### C0 当前全国 overview

| Candidate | Cost | MAE | P90 | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| current_overview_grid_score | 0.02 | 0.6892 | 0.9313 | 0.0805 | 0.0800 | 92 | 0 |

结论：overview 召回高但严重误报。它会把“云量很好但日向边界太远、上游低云/气溶胶挡光”的大片区域涂成候选。这正是用户之前指出的全国图物理问题：连续云带里每格独立评分，缺少 sunward 边界语义。

### C1 观测柱垂直诊断 + 1-D sunward profile

| Candidate | Cost | MAE | P90 | Max | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| observer_diagnosis_plus_1d_sunward_100km | 0.18 | 0.0178 | 0.0000 | 0.5797 | 0.0295 | 0.6667 | 4 | 0 |

结论：1-D 物理 screen 是一个好“第一层”。它把 overview 的 92 个假阳性降到 4 个，且不漏掉真候选。但它仍会在少数路径遮挡场景上错得很大，因为它没有密集 2-D 光追，只看 100 km 级别的一维云量边界。

### C2 粗 2-D sunward ray trace

| Candidate | Cost | MAE | P90 | Max | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| coarse_2d_ray_200km_columns | 0.1515 | 0.0135 | 0.0000 | 0.5797 | 0.0249 | 0.7273 | 3 | 0 |
| coarse_2d_ray_100km_columns | 0.2727 | 0.0090 | 0.0000 | 0.5797 | 0.0149 | 0.8000 | 2 | 0 |
| coarse_2d_ray_50km_columns | 0.5152 | 0.0000 | 0.0000 | 0.0032 | 0.0001 | 1.0000 | 0 | 0 |

结论：50 km 截面在本基准上几乎贴住 25 km 真值，成本约一半。100/200 km 虽然均值误差很低，但仍可能跨过窄低云/气溶胶遮挡，留下候选区假阳性。#59 如果要把“单点保真度的可负担部分”搬上全国，50 km 是当前最稳的首选粗度；100 km 可作为先验筛选或低成本 fallback。

### C3 邻域/锚点复用

| Candidate | Cost | MAE | P90 | Max | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| nearest_full_physics_anchor_stride_4 | 0.1190 | 0.0504 | 0.2569 | 0.6991 | 0.0611 | 0.5000 | 5 | 1 |
| nearest_full_physics_anchor_stride_3 | 0.1905 | 0.0313 | 0.0000 | 0.6991 | 0.0408 | 0.0000 | 0 | 4 |
| nearest_full_physics_anchor_stride_2 | 0.3175 | 0.0313 | 0.0000 | 0.6991 | 0.0512 | 0.3333 | 1 | 3 |

结论：锚点复用不适合单独决定候选区。候选带本身很窄，锚点相位一错就会全漏或平移边界。它可以用于缓存、插值预览或渲染平滑，但不能替代候选判定。

### C4 分层算力预算

先用当前 overview 找 `0.50 +/- band` 再跑全物理的策略失败，因为 overview 的主要错误不是“阈值附近不确定”，而是把大量远高于阈值的物理假阳性打得很高。

| Candidate | Cost | MAE | P90 | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| tiered_overview_plus_full_band_0.10 | 0.0476 | 0.6656 | 0.9313 | 0.0912 | 0.0825 | 89 | 0 |
| tiered_overview_plus_full_band_0.20 | 0.1270 | 0.6447 | 0.9313 | 0.0853 | 0.0833 | 88 | 0 |
| tiered_overview_plus_full_band_0.30 | 0.3095 | 0.5597 | 0.9313 | 0.1001 | 0.0941 | 77 | 0 |

改用 C1 的物理 screen，再只对 screen 高分格点跑完整 2-D，则成本和保真度同时好：

| Candidate | Cost | MAE | P90 | Max | Grad MAE | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tiered_1d_screen_plus_full_ge_0.30 | 0.2673 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0 | 0 |
| tiered_1d_screen_plus_full_ge_0.50 | 0.2435 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0 | 0 |
| tiered_1d_screen_plus_full_ge_0.70 | 0.1800 | 0.0178 | 0.0000 | 0.5797 | 0.0295 | 0.6667 | 4 | 0 |

结论：推荐路线不是“overview 阈值带精修”，而是“物理 screen 后精修”。在本基准里，1-D screen + `>=0.50` 完整 2-D 精修以约 `0.24x` 完整成本达到真值。

## 4. 物理偏差与可接受性

### Overview 的系统偏差

偏差：独立逐格评分会系统高估连续云盾内部；只要本格云量、湿度、能见度好，就给高概率，不知道日向边界是否在几何可达范围内。

可接受性：只能作为低成本预览或第一代 baseline。不能作为 #59 的物理升级目标。

### 1-D screen 的系统偏差

偏差：能表达日向边界距离、上游 AOD 均值和低云覆盖，但路径遮挡仍是“沿线最大/边界”启发式，不知道抛物线实际穿过哪一层云或哪段气溶胶。

可接受性：适合作为全国第一层物理筛选。它不应直接作为最终候选图，除非产品明确标注为 coarse screen。

### 粗 2-D ray trace 的系统偏差

偏差：列距越粗，越可能跳过窄云洞、窄低云、局地 AOD 锋区。50 km 在合成场里稳定，但真实 GFS 0.25° 本身约 25 km；若列距大于 50 km，容易失去路径遮挡语义。

可接受性：50 km 可作为 #59 的首版全国精修目标；100 km 可作为性能兜底；200 km 只适合粗筛。

### 锚点复用的系统偏差

偏差：候选带通常窄且贴着云边界，锚点相位决定成败；空间插值会把“物理边界”变成“插值边界”。

可接受性：不推荐单独用于概率判定。可以用于缓存、调参预览、或者对已经完成物理判定的图做 display-only 平滑。

### 卫星临近订正的位置

PR #52 已把 Himawari 连续 B13 IR 帧的云边界运动 nowcast 合入现状：`cloud_motion.nowcast_correction` 能给位移、regime、confidence，并对模型场做有限幅度订正。它应放在 #59 的后处理/订正层，而不是替代单点物理全国化：

1. 先用物理 screen + 2-D ray trace 得到“此时此地若云场如模式所示，是否能烧”的概率；
2. 再用卫星 nowcast 修正云边界位置和近期演变；
3. 对流 regime 置信度低时降低或标注不确定性，避免把卫星外推当作确定真值。

## 5. 推荐给 #59 的实现路线

推荐实现 **两阶段物理全国化**：

1. **Stage A：全国 1-D physics screen**
   - 仍按每格日出/日落选择 GFS valid hour；
   - 在全国压力层 cube 上做观测柱云层诊断，拿真实画布高度/光学厚度/低云遮挡；
   - 用 100 km 间距的日向 1-D profile 估计边界距离、路径 AOD 均值、边界梯度；
   - 输出 `screen_probability` 和诊断因子图：presence、low obstruction、clean air、sunward boundary、screen decision。

2. **Stage B：候选带 50 km 2-D ray trace 精修**
   - 对 `screen_probability >= 0.50`，以及建议的安全带 `0.30..0.50` 或高不确定格点，跑 50 km sunward cross-section；
   - 每个 valid hour 共享 GFS pressure cube，按 tile/valid_time 复用，不做每格网络请求；
   - 只在精修格点调用完整 `score_point_with_cube` 等价逻辑；
   - 输出 `refined_probability`，并记录 `refinement_fraction`、`ray_spacing_km`、`screen_threshold`。

3. **Stage C：卫星 nowcast 修正**
   - 接 PR #52 的 `nowcast_correction`，对近 1–2 h 云边界做有限幅度修正；
   - metadata 区分 `model_probability`、`physics_refined_probability`、`satellite_corrected_probability`。

预期收益（以本基准为证据）：相对当前 overview，MAE 从 `0.6892` 降到近 `0`，`>=0.50` 候选误报从 `92` 降到 `0`，成本约为完整 25 km 单点全跑的 `0.24x`。真实收益需要在 live GFS + satellite 样本上再验证，但方向明确：先加物理 screen，再精修候选带。

## 6. #59 验收建议

#59 不应只看图片观感，应至少验收：

- 与本脚本同类的离线 benchmark：当前 overview、1-D screen、50 km 2-D refinement、最终方案同表比较；
- 在重叠抽样点上，最终全国概率相对 `score_point_with_cube(...25km)` 的 MAE、P90、Max；
- `>=0.50` 候选的 precision/recall/F1，以及 FP/FN 的物理归因；
- 空间结构指标：`gradient_mae` 或候选边界 Hausdorff/IoU；
- metadata 写明 screen/refinement/nowcast 的成本与使用比例；
- 离线测试绿，覆盖率不低于项目地板。

## 7. 可复现脚本

实验脚本在 [nationalization_spike.py](../experiments/nationalization_spike.py)。它只依赖现有 `predictor/` 模块和合成场，不联网，不改生产代码。后续 #59 可以把它升级成回归 benchmark：保留当前合成场，再增加 2–3 个真实 GFS 缓存样本。
