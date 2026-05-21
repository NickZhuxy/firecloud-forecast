# 火烧云观察日志

倒序追加。每条记录将来用作 ML 训练集，所以字段越规整越好。

## 模板

```markdown
## YYYY-MM-DD（早晨日出 / 傍晚日落）
- 地点：城市, 州/省（lat, lon 可选）
- 时间：HH:MM（当地时区）
- 评级：N/5（1=无、5=极致）
- 颜色：橙 / 红 / 粉 / 紫 / ...（可多选）
- 云况：高云 / 中云 / 低云 比例和形态
- 能见度：清澈 / 雾霾 / ...
- PM2.5：μg/m³（若有）
- 预测器给的分：0.XX（哪几条规则贡献多少）
- 备注 / 偏差分析：模型在哪里失准了？
- 照片：[link or filename]
```

---

## 2026-05-20（傍晚日落，模型 dry-run）

> 这条不是实地观察，是项目跑通后的第一次"用一下"。无实测对照，仅暴露了一个模型结构性 bug。

- **地点**：Olympic Peninsula 海岸（Forks / La Push / Ruby Beach），WA
- **时间**：20:30 PDT（= 2026-05-21 03:30 UTC，约日落前 30 分钟）
- **评级**：N/A（未实地观察）
- **预测器给的分**：整片 BBOX 区域 0.62–0.63，几乎均匀
- **模型 inputs（典型点 47.70, -124.80）**：
  - `cloud_high_pct = 0.0`
  - `cloud_mid_pct = 0.0`
  - `cloud_low_pct = 18.0`
  - `humidity_pct = 86.0`
- **各规则分数**：
  - `mid_high_cloud_presence = 0.00`（没有云做"画布"）
  - `low_cloud_obstruction = 1.00`
  - `solar_angle = 1.00`
  - `humidity = 0.60`
- **HRRR cycle**：`hrrr@2026-05-21T01Z+f02`

### 偏差分析 / 模型 Bug #1（结构性）

composite = (2.0·0 + 2.0·1.0 + 1.5·1.0 + 1.0·0.6) / 6.5 = **0.63**

物理上说不通——**没有 mid/high 云就根本不可能有火烧云**。加权平均允许其他三条规则把分数撑起来，是 `RuleBasedPredictor` 的结构缺陷：把"必要条件"当成普通项平均掉。

候选修法（待挑选）：

1. **乘性组合**：`probability = ∏(score_i ^ w_i)`。零分项把整体归零。最物理。
2. **硬地板 (gate)**：`if mid_high_cloud_presence < 0.1: probability *= 0.1`。简单，但是阈值魔数。
3. **noisy-AND**：`probability = 1 - ∏(1 - score_i^w_i)` 或类似概率框架。更复杂但有理论基础。
4. **分两层**：必要条件做几何平均（任一为 0 则归零），充分条件做加权平均，两层相乘。

→ 待在 `predictor/rules.py` 中实现 + 加单测；记入 `research/theory/formation-conditions.md`。

---
