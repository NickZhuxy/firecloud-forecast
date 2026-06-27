# FA-T1 — 云边界向日落时刻风平移 — 设计

Parent: Epic #54 / #57 P1。物理推导：[research/theory/fa-t1-boundary-advection.md](../../../research/theory/fa-t1-boundary-advection.md)。
权威：手册 §4.1.1 / §4.2。Branch: `codex/57-fa-t1-boundary-advection`（off main）。

## 目标

把日落方向云边界从快照/模式时刻**按云高风平移到日落时刻**（Δt=日落−valid_time），替换
"边界停在快照时刻"的近似（手册 §4.2 中云洞 30min 平移 40km）。纯运动学外推，纯增量、
`Δt=0`/无风/无边界时恒等回退。

## 改动面

1. **纯平移** [geometry.py](../../../predictor/geometry.py)
   - `advect_boundary_km(boundary_km, signed_wind_m_s, dt_seconds) -> float`：
     `max(0, boundary_km + signed_wind_m_s·dt_s/1000)`。
2. **有符号风** [features.py](../../../predictor/features.py)
   - `_projected_boundary_wind` 改返回**有符号**沿日落轴投影（`speed·cos(去向−azimuth)`，正=外移）；
     `analyze_sunward_profile` 里 `boundary_motion_m_s` 改取其 `abs`（语义/值不变）。
3. **接线** [features.py](../../../predictor/features.py)
   - `analyze_sunward_profile(profile, canvas_layer, *, sunset_time=None, valid_time=None)`：
     有 `sunset_time`+`valid_time`+边界+风时，算 `Δt`、平移；输出
     `sunward_cloud_boundary_km`=平移值、新增 `sunward_cloud_boundary_raw_km`=原值。
     缺省（None/2 参调用）⟹ 不平移（raw==consumed），既有测试与国家级路径不变。
   - `derive` 传 `sunset_time`（已算）与 `valid_time`（新可选形参，默认=查询 `time`）给它。
   - `Features` 增 `sunward_cloud_boundary_raw_km`。`SunwardIlluminationGate` 仍读
     `sunward_cloud_boundary_km`（现为平移值），签名不变。

## 不在本 PR

- 2-D `SunwardCrossSection` 逐列/逐高平移（cube valid_time；源/网格对齐）——更大 story。
- FA-T2（P3 时次-日落偏差插值）。
- 把真实模式 valid_time 接入（默认用查询 time；`valid_time` 形参已留口）。

## 测试（TDD 先红后绿）

- `test_geometry`：`advect_boundary_km` 闭式/方向/floor/Δt=0 恒等/手册 §4.2 量级（22 m/s·30min≈40km）。
- `test_features`：`_projected_boundary_wind` 有符号（外移正、内移负）、`boundary_motion_m_s` 仍 abs；
  `analyze_sunward_profile` 平移 + raw 暴露 + 缺省恒等。
- `test_rules`/端到端：边界外推超出 reach ⟹ `sunward_illumination` 非增。
- 回归：全量 `-m "not integration"` 绿；grid 1e-9 / 现有 gate / `boundary_motion_m_s` 不变。

## 安全

纯增量：新函数/新可选形参/新字段（默认 None ⟹ 恒等）。`_projected_boundary_wind` 由 abs 改
有符号是内部函数，唯一既有消费点 `boundary_motion_m_s` 同步取 abs，外部值不变。
