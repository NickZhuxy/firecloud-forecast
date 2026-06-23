# 逐层贡献接入评分 + 分级遮挡 — 设计 (#31)

Parent epic: #4 (integration) · Branch: `codex/31-layer-contributions-scoring`
来源:PR #29(#13)review 的后续。

## 目标

让诊断出的逐层受光/遮挡真正影响评分与输出;把遮挡从布尔升级为**分级**估计。

## 设计

- **`predictor/illumination.py`**:
  - `LayerContribution` 增 `obstruction_fraction`(0–1,保留 `obstructed` 布尔)。
  - 不透明度代理 `_layer_opacity`:`min(1, thickness/2000m) × phase{liquid 1.0, mixed 0.7, ice 0.4}`。
  - `_obstruction_below`:下方各层重叠合并 `1 − Π(1 − opacity_i)`。
  - `canvas_obstruction_fraction(layers)`:画布层被下方各层遮挡的分级值。
- **`predictor/features.py`**:`derive(cloud_layers=)` 时填充 `diagnosed_obstruction_pct`
  (画布遮挡 ×100)与 `layer_contributions`(逐层)。新字段默认 None。
- **`predictor/rules.py`**:`LowCloudObstruction` 信号优先级
  **diagnosed → sunward transect → cloud_low_pct**;无诊断时行为不变。
- **`app/server.py`**:响应新增 `diagnosed` 块(`obstruction_pct` + 逐层 `layers`)。

## 物理依据

夕照以掠射角穿过低层到达画布;下方云层的遮挡随厚度与相态变化——厚液态层几乎
全挡,薄卷云(冰)挡得少。分级模型比"下方有云即遮挡"更贴近 `LowCloudObstruction`
本身的连续处理。

## 验收标准映射(#31)

- [x] 逐层受光/遮挡接入输出(server `diagnosed.layers`)与评分(`LowCloudObstruction`)
- [x] 分级遮挡(厚度 × 相态不透明度,重叠合并)
- [x] 无诊断时回退,默认行为不变(现有测试通过)
- [x] 单测:分级值、薄冰 < 厚液、gate 优先 diagnosed、回退不变、server 输出
