# 多层云诊断 — 设计 (#10)

Parent epic: #4 · Milestone: v0.2 · Branch: `codex/10-cloud-diagnosis`

## 目标

从 `NormalizedProfile`(#6)诊断多层云的 base/top/厚度/相态/置信度,用真实垂直
结构替换固定低/中/高云代表高度,为照明几何与遮挡判断提供基础(下游 #13)。

## 数据可用性说明

#9 的 profile 携带凝结物(`cloud_water_kg_kg` + `cloud_ice_kg_kg`),但**不含逐层
云量**(GFS pgrb2.0p25 未取)。因此主信号用凝结物,凝结物缺失时回退 RH——这与
故事"优先云量与凝结物"的意图一致,在数据范围内如实实现。

## 模块 `predictor/clouds.py`

- `CloudLayer`:`base_m, top_m, thickness_m, phase_hint, confidence, source`。
- `CloudDiagnosisConfig`(frozen,集中阈值 + 来源注释):凝结物阈值 1e-6 kg/kg、
  RH 阈值 90%、合并间隙 300 m、地面以下高度下限 0 m、相态温度界、置信度先验。
- `diagnose_clouds(profile, config=DEFAULT) -> list[CloudLayer]`。

## 算法

1. 丢弃 `geometric_height < min`(地面以下压力层)与非有限高度层。
2. 选信号:凝结物可用 → `clw+ice`(阈值 1e-6,source=condensate);否则 RH
   (阈值 90%,source=rh)。
3. `signal >= threshold` 取连续段。
4. 段边界:RH 路径(信号平滑渐变)**线性插值**阈值穿越高度;凝结物路径(阶跃
   信号,阈值远低于云内值)用**半格距 midpoint**,避免边界被钉到相邻无云层而
   夸大厚度。段在廓线端点则用端点高度。
5. 合并"下层 base − 上层 top < 合并间隙"的相邻层。
6. 相态:凝结物 → 冰占比 >0.7 ice / <0.3 liquid / 否则 mixed;RH 回退 → 按层平均温度。
7. 置信度:condensate 0.8 / rh 0.5;单层 ×0.6;触廓线端点 ×0.9(extent 未知)。

## 验收标准映射

- [x] 每层输出 base/top/thickness/phase_hint/confidence
- [x] 无云 / 单层 / 多层 / 薄层 / 地面以下层 均有测试覆盖
- [x] 不确定时降低 confidence(RH 回退、单层、开放端点),不伪造精确高度
- [x] 阈值与合并规则集中在 `CloudDiagnosisConfig` 且有来源说明
