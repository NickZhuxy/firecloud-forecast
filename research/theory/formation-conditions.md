# 火烧云形成的综合条件

> 把“什么样的天气会出火烧云”从直觉转成可判定条件，并区分必要条件和增强条件。

## 概念

火烧云（sunset glow / afterglow / twilight color）指日出或日落前后，中高云被低角度阳光从下方或侧面照亮，呈现红、橙、粉、紫色。云本身不发光，而是反射经过长大气光路并被选择性消光后的太阳光。

物理机制：

1. **光路加长**：日落附近的大气光程远长于正午。
2. **选择性消光**：瑞利散射、米氏散射和臭氧吸收共同改变光谱。
3. **云层反射**：红化后的光必须穿过低层大气到达中高云画布。

## 关键变量

| 变量 | 类型 | 说明 |
|---|---|---|
| 中/高云存在 | 必要 | 没有可被照亮的画布就没有火烧云 |
| 低层与日落方向通透 | 必要 | 厚低云、雾或上游云层会切断光路 |
| 对流层空气较清洁 | 必要 | 高气溶胶负荷会削弱到达云层的有效光 |
| 太阳低角度 | 必要 | 长光路和红化的几何前提 |
| 中高云覆盖率 | 增强 | 覆盖过少缺画布，过满可能堵塞日落方向 |
| 云层高度 | 增强 | 高云通常拥有更长的直射窗口 |
| 云的形态与边界 | 增强 | 丝缕、波状和清晰边界会增强视觉层次 |
| 平流层火山气溶胶 | 条件性增强 | 与对流层污染作用不同，可能延长 afterglow |
| 湿度 | 增强且非线性 | 太干难成云，太湿又可能增加低层衰减 |

## 当前预测规则

早期加权平均会让“中高云覆盖为零、其他条件良好”的场景仍得到约 0.63，这是把必要条件当成可补偿变量造成的结构性误报。当前 `RuleBasedPredictor` 已改为两层组合：

```text
gate     = ∏ score_i^w_i
modifier = weighted_avg(score_j)
condition_index = gate × modifier
```

| 规则 | 类型 | 说明 |
|---|---|---|
| `MidHighCloudPresence` | gate | 必须存在可被照亮的中高云画布 |
| `LowCloudObstruction` | gate | 低云会切断观察者和阳光路径 |
| `SolarTiming` | gate | 约束低太阳高度角时间窗 |
| `CleanAirGate` | gate | 优先使用 550 nm AOD，缺失时谨慎回退能见度 |
| `IlluminationGeometry` | gate | 判断日落方向云边界是否仍能被照亮 |
| `HumidityFactor` | modifier | 湿度不能补偿缺失画布 |
| `CloudAltitudePreference` | modifier | 奖励更长的高云照明窗口 |
| `CloudCoverSweetSpot` | modifier | 奖励适中的画布覆盖 |
| `BoundaryConfidence` | modifier | 表达离散剖面和云边界运动的不确定性 |

下一步不是继续堆规则，而是用 GFS 压力层诊断真实云底、云顶和厚度，并让 800 km 剖面直接消费这些云层。阈值调整通过离线物理情景、公开资料和多源同时次对照验证。

## 资料来源

1. Corfidi, S. F. (2014). *The Colors of Twilight and Sunset*. NOAA Storm Prediction Center.
2. Kasten, F., & Young, A. T. (1989). *Revised optical air mass tables and approximation formula*. *Applied Optics*, 28(22), 4735–4738.
3. WMO International Cloud Atlas.
4. SunsetWx 与 Sunsethue 公开的方法说明，仅作为经验阈值参考。

## 延伸阅读

- [cloud-physics.md](cloud-physics.md)
- [atmospheric-optics.md](atmospheric-optics.md)
- [solar-geometry.md](solar-geometry.md)
- [aerosols-and-color.md](aerosols-and-color.md)
