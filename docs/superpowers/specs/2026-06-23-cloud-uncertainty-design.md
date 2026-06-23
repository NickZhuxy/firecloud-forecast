# 云层诊断不确定性与跨时次一致性 — 设计 (#11)

Parent epic: #4 · Milestone: v0.2 · Branch: `codex/11-uncertainty`

## 目标

避免单一阈值、单一模式时次给出过度精确的云层高度。把"层级稀疏、阈值边缘、
来源回退、时次分歧"折进 confidence,并输出**结构化原因**而非黑盒数值。

## 改动

- **`predictor/clouds.py`**:`CloudLayer` 新增 `signal_margin`(层内峰值信号 / 阈值,
  ≥1;接近 1 = 阈值边缘)。`diagnose_clouds` 填充它。向后兼容(默认 NaN)。
- **`predictor/uncertainty.py`**:
  - `ConfidenceFactor(name, multiplier, detail)`、`ConfidenceBreakdown(overall, factors)`
  - `UncertaintyConfig`(集中权重:匹配容差 800 m、边缘比 2.0、RH 0.6、单层 0.7、
    边缘下限 0.5、时次下限 0.5)
  - `cross_time_agreement(layer, neighbor_diagnoses, tol)` — 相邻时次中存在匹配层的比例
  - `assess_layer(layer, profile, neighbor_diagnoses, config) -> ConfidenceBreakdown`

## confidence 因子(相乘,各带原因)

1. 来源:condensate ×1.0 / rh ×0.6
2. 垂直支撑:≥2 层 ×1.0 / 单层 ×0.7
3. 阈值边缘:margin≥2 ×1.0;否则在 [0.5,1] 线性
4. 跨时次一致:`min_time + (1-min_time)·agreement`;无相邻时次则中性(不归零)

`overall = Π multiplier`,`factors` 给出可审计的结构化原因。

## 可插拔对照 / 无付费依赖

`neighbor_diagnoses` 是任意免费来源(相邻 GFS run/valid 时次,或其他免费模式)
的层列表;本 Story 不引入付费 ECMWF。

## 验收标准映射

- [x] 比较相邻 GFS run/valid time 的云层结构变化(`cross_time_agreement`)
- [x] 层级稀疏 / 阈值边缘 / 来源回退 / 时次分歧 纳入 confidence
- [x] 输出结构化原因(`ConfidenceBreakdown.factors`)
- [x] 免费模型仅作可插拔对照,无付费 ECMWF 依赖
