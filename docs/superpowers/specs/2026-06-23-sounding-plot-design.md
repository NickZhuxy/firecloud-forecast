# 可复核探空图 — 设计 (#8)

Parent epic: #4 · Milestone: v0.2 · Branch: `codex/8-sounding-plot`

## 目标

把人工在 Windy/探空图中的判断过程,变成可复核的诊断界面:展示温度、露点、
高度、风,并标注诊断出的云层,附模型/时次/点位/缓存状态,可导出与 Windy
同时次人工对照。

## 模块 `predictor/sounding_plot.py`

- `plot_sounding(profile, layers, *, cached=False, figure=None) -> Figure`
- `save_sounding(profile, layers, path, *, cached=False) -> str`(导出 PNG)

**与诊断算法解耦**:只消费已标准化的 `NormalizedProfile`(#6)与已诊断的
`list[CloudLayer]`(#10),不导入诊断代码。使用 `matplotlib.figure.Figure`
直接构图(不走 pyplot),无需 GUI 后端,便于 headless 测试与服务端渲染。

## 图面

- T、Td(°C)对几何高度的两条曲线。
- 诊断云层:`axhspan` 灰带 + 文本(相态、来源、base/top/厚度/置信度)。
- 风:右侧固定列的风羽(u/v)。
- 标题:`source_label`(模型+run+fxx)、valid/run time、点位、cached/live。

## 验收标准映射

- [x] 展示温度、露点、压力/高度和风信息
- [x] 标注云底/云顶/厚度/置信度
- [x] 标明模型、run time、valid time、点位、缓存状态
- [x] 图表可导出(`save_sounding` → PNG)用于人工对照
- [x] 图表层与诊断算法解耦(只吃 profile + layers)
