# 用诊断云层几何替换固定代表高度 — 设计 (#13)

Parent epic: #2 · Milestone: v0.2 · Branch: `codex/13-diagnosed-geometry`

## 目标

把现有照明/遮挡/画布判断从 1 / 3.5 / 7 km 固定代表高度,升级为 #10 诊断出的
真实云底/云顶/厚度;无廓线数据时显式回退旧三层逻辑并降低置信度;新旧可对比。

## 设计(加法式,默认行为不变)

- **`predictor/illumination.py`**(消费 `CloudLayer`,复用 `geometry`,不导入评分):
  - `canvas_layer_from_diagnosis(layers)` — 取最高的诊断云层为画布(被照最久)
  - `cloud_base_from_diagnosis(layers)` — 画布层云底
  - `assess_layer_contributions(layers, lat)` — 每层的照明时长(geometry)+ 是否被
    下方云层遮挡 + 是否为画布。**多层云分别计算受光/遮挡贡献**。
- **`predictor/features.py`**:`derive(..., cloud_layers=None)`
  - 有诊断层 → `cloud_base_m` = 画布层诊断云底,`cloud_base_source="diagnosed"`,
    `cloud_base_confidence` = 该层置信度
  - 否则源报告云底 → `"source_reported"`(0.7)
  - 否则固定估计 → `"fixed_estimate"`,**置信度降到 0.4**(回退)
  - 始终记录 `cloud_base_fixed_m`(旧估计)供**新旧对比**
  - 新增 Features 字段均有默认值;`cloud_layers` 默认 None → 旧行为不变

`cloud_base_m` 经现有 `SunwardIlluminationGate`(equivalent base → penetration)
流入评分,因此 illumination gate 自然接受诊断结果。

## 验收标准映射

- [x] 现有 canvas 与 illumination gate 接受 CloudLayer 列表(经 `derive(cloud_layers=)`)
- [x] 多层云分别计算受光和遮挡贡献(`assess_layer_contributions`)
- [x] 无廓线数据时回退旧三层逻辑并降低置信度(`fixed_estimate` → 0.4)
- [x] 新旧算法可在诊断输出中对比(`cloud_base_m` vs `cloud_base_fixed_m`)
- [x] 现有离线测试通过(212 passed)+ 新增真实层几何测试
