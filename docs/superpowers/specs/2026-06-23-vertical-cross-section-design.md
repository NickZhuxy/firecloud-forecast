# 日落方位垂直剖面(距离 × 几何高度)— 设计 (#18)

Parent epic: #2 · Branch: `codex/18-vertical-cross-section`

## 目标

让用户直接看到日落方向上阳光会穿过哪些湿层、上升区与诊断云层——把 #12 的采样
路径 + 每点 #6 标准化廓线 + #10 诊断云层,组装成 距离×几何高度 的剖面并出图。

## 设计(两模块:纯数据 + headless 出图)

- **`predictor/cross_section.py`**(纯组装,零网络/零绘图):
  - `SunwardCrossSection`:`distances_km` (x)、`heights_m` (y)、`relative_humidity_pct`/
    `vertical_velocity_pa_s`/`temperature_k` 为 (height, distance) 数组、`mask` 有效掩膜、
    每列 `cloud_layers`、observer/azimuth/target_time/source_label。
  - `even_heights(max_m, count)`、`build_cross_section(path, profiles, layers_per_point, heights_m=)`。
  - **插值显式**:每列按几何高度 `np.interp` 线性插值到公共高度轴;**缺测掩膜明确**:
    低于地形(用 #12 注入的 elevation)、高于廓线顶、或点超出数据域/无廓线 → NaN 且
    `mask=False`,消费方不会把空洞误当数据。
- **`predictor/cross_section_plot.py`**(headless `Figure`,不走 pyplot):
  `plot_cross_section` / `save_cross_section`。RH 填色 + 上升区(w<0)填充阴影 +
  0°C 等温线 + 每列诊断云层竖条 + 观测点标记 + 太阳方向标注 + 超出覆盖列"no data"
  标注 + 覆盖图例。可导出 PNG 用于 Windy/人工对照。

## 验收标准映射

- [x] 剖面坐标为距离 × 几何高度
- [x] 展示 RH、垂直速度、温度与诊断云层边界
- [x] 标记观测点、太阳方向、超出数据覆盖区域
- [x] 插值(线性 np.interp)与缺测掩膜明确且可测试(`test_cross_section.py`)
- [x] 可导出同一时次图像(`save_cross_section`)
