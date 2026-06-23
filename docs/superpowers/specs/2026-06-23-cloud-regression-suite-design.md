# 云层诊断离线回归测试集 — 设计 (#7)

Parent epic: #4 · Milestone: v0.2 · Branch: `codex/7-cloud-regression`

## 目标

在没有个人长期观测数据的前提下,用可控物理情景保护 `diagnose_clouds`(#10)
的迭代,避免阈值/合并规则调整造成静默回归。零网络、可重复。

## 模块

- **`predictor/tests/cloud_scenarios.py`** — 情景库:共享标准廓线 + 六个手工
  构造的 `NormalizedProfile`,每个附期望(层数、base/top 范围、置信度上界、
  相态/来源)。文件头声明:改 `CloudDiagnosisConfig` 默认值必须回来更新期望。
- **`predictor/tests/test_cloud_regression.py`** — 参数化遍历情景:断言层数、
  几何范围、置信度方向;并 **pin 住 config 默认阈值**,阈值漂移会失败报警。

## 情景覆盖(对应验收)

| 情景 | 构造 | 期望 |
|---|---|---|
| clear | 无凝结物、低 RH | 0 层 |
| thin_high_cirrus | 单层 300 hPa 冰 | 1 层,ice,高空,conf≤0.6(单层惩罚) |
| low_stratus | 950–900 hPa 液态 | 1 层,liquid,低空,贴地端点 |
| multi_layer | 700–600 液 + 300–250 冰 | 2 层 |
| deep_convective | 850→300 贯通 + 顶部冰 | 1 厚层,conf 0.8 |
| missing_data_rh | 凝结物 NaN + RH 高带 | 1 层,source=rh,conf≤0.5 |

## 验收标准映射

- [x] fixture 覆盖无云/薄高云/低云遮挡/多层/深对流/缺测
- [x] 每情景明确期望层数、云底/云顶范围、置信度方向
- [x] 不访问外网、可重复
- [x] 现有评分测试继续通过(194 passed)
- [x] 阈值变化必须显式更新情景说明(config pin 测试 + 文件头声明强制)
