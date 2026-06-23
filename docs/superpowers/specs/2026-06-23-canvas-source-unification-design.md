# 统一 canvas 来源 — 设计 (#32)

Parent epic: #4 (integration) · Branch: `codex/32-canvas-unification`
来源:PR #29(#13)review 的后续。

## 目标

选用诊断 canvas 时,让 `canvas_layer` 与高度调节项跟随诊断 canvas 高度,而非
三层 snapshot 百分比——消除 `canvas_layer`(原 "mid")与诊断 `cloud_base_m`
(如 7 km 高层)指向不同云层的不一致。

## 设计(加法式,仅诊断路径生效)

- **`predictor/features.py`**:
  - 新增 `tier_from_height(base_m)`:WMO étage 边界(低 <2 km、中 2–6 km、高 >6 km)。
  - `derive`:有诊断 canvas 时 `canvas_layer = tier_from_height(canvas.base_m)`,
    否则保持三层 `select_canvas_layer`。`canvas_cloud_pct` 取该 tier 的 snapshot
    覆盖率(可用的覆盖代理)。
  - 由此 `analyze_sunward_profile` 的遮挡层选择自动跟随诊断 canvas(验收 1)。
- **`predictor/rules.py`**:`CloudAltitudePreference` 在 `cloud_base_source==
  "diagnosed"` 时按 canvas tier 给质量(high 1.0 / mid 0.5 / low 0.1),否则保持
  原覆盖加权公式。诊断云底因此不再是唯一改变评分的高度信号(验收 2)。

## 边界 / 与 #35 的分工

- 覆盖量类调节项(`CloudCoverSweetSpot`、`MidHighCloudPresence`)仍读 snapshot
  覆盖率——它们衡量的是"覆盖多少",需要 canvas 覆盖率来源;诊断 `CloudLayer`
  不带覆盖率,故这部分跨模型一致性(诊断结构 vs Open-Meteo 覆盖)留给 **#35**。
- 无诊断时(全国网格 / 无 GFS)所有行为不变。

## 验收标准映射

- [x] 选用诊断 canvas 时,从诊断高度推导 canvas_layer 与 sunward 遮挡层选择
- [x] 高度调节项(CloudAltitudePreference)跟随诊断 canvas;覆盖量项的协调见 #35
- [x] 加测试钉住跨字段关系(诊断高度 → canvas_layer tier → 高度偏好)
