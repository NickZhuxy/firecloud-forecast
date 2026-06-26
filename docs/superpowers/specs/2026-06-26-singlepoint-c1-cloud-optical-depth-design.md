# 单点物理拟真增强 — FA-C1：由含水量诊断云光学厚度 — 设计 (#57 P1)

Parent epic: #54 · #57 P1。依据 `research/theory/single-point-fidelity-audit.md` 的 FA-C1。
权威：手册 §1.1.2（典型云滴半径 ~10 µm）、§1.3.2（云消光由**含水量与云滴谱**决定；低云 τ>10 近全反射成灰白、卷云 τ<1 透光显色）。
Branch: `codex/57-c1-cloud-optical-depth`（off main，独立于 #66；只改 `_layer_opacity` 内部、签名不变，故 FA-G5 光追合并后自动受益）。

## 问题（审计 FA-C1）

`illumination._layer_opacity` 现用 `min(1, 厚度/2000) × 相态系数 × 置信度` 作云不透明度代理——**不用**廓线里真实的
`cloud_water_kg_kg`/`cloud_ice_kg_kg`。于是"薄而密的低层水云" vs "厚而稀的卷云"会被错排（厚度代理偏向后者）。

## 物理（手册 §1.3.2 标准云光学）

层云光学厚度 `τ = (3/2)·WP / (ρ_cond · r_e)`，水路径 `WP = ∫ ρ_air · q dz`：
```
ρ_air = p / (R_d · T),  R_d = 287.05         # p in Pa, T in K
LWP = Σ_trap ρ_air · q_liquid · dz           # kg/m²   (trapezoidal over in-layer levels)
IWP = Σ_trap ρ_air · q_ice    · dz
τ_liq = 1.5 · LWP / (ρ_w · r_e,liq),  ρ_w=1000,  r_e,liq=10 µm
τ_ice = 1.5 · IWP / (ρ_i · r_e,ice),  ρ_i= 917,  r_e,ice=30 µm   # 大冰晶 → 同等路径更透
τ = τ_liq + τ_ice
```
冰晶有效半径更大 → 同等含水路径 τ 更小 → 卷云天然更透（与手册一致）。
**自检**：低层水云 q_l=5e-4、Δz=1km、p≈900hPa → τ≈80（不透）；薄卷云 q_i=1e-5、Δz=2km、p≈300hPa → τ≈0.5（透）。

## 设计决定

1. **`CloudLayer` 加 `optical_depth: float = NaN`**；`diagnose_clouds` 在 `source=="condensate"` 时按上式逐层算并填入；
   RH 回退层（无凝结物）留 `NaN`；单层（无法梯形积分）留 `NaN`。
2. **`_layer_opacity` 改为 τ 优先、厚度回退**（签名不变）：
   ```
   od = layer.optical_depth
   base = (1 − exp(−od)) if isfinite(od) else min(1, 厚度/2000) × 相态系数   # 旧式
   return base × confidence
   ```
   τ 已编码相态（冰/水有效半径）与含水量×深度，故 τ 路径不再乘厚度/相态代理。置信度加权保留。
3. **常量入 `CloudDiagnosisConfig`**：`liquid_eff_radius_m=1e-5`、`ice_eff_radius_m=3e-5`；ρ_w/ρ_i/R_d 为模块常量。
4. **向后兼容**：直接构造的 `CloudLayer`（无 `optical_depth` → NaN）走旧式回退 → `test_obstruction_grading`/`test_illumination` 等**不受影响**；诊断类测试只断言层几何/相态/来源，不断言不透明度 → 也不受影响。

## 测试（TDD：先红后绿）

`test_clouds.py`（新增）/ `test_illumination.py`：
- `diagnose_clouds` 在液态云廓线上 → 该层 `optical_depth` 有限且 **>10**（不透低云）；在薄卷云廓线上 → **<1**（透）。
- **metamorphic**：含水量更高 → `optical_depth` 更大（同几何两条廓线对比）。
- `_layer_opacity`：`optical_depth=5`（直接设）→ opacity≈(1−e⁻⁵)×conf≈0.993·conf；`=0.1` → ≈0.095·conf。
- **τ 覆盖厚度代理**：薄层（厚度100m，旧式≈0.05）但 `optical_depth=5` → opacity≈0.99；厚层（厚度3000m，旧式≈1.0）但 `optical_depth=0.1` → opacity≈0.095。
- **回退不变**：`optical_depth=NaN` 的层 → 旧式厚度×相态×置信度（钉住既有 0.27/0.7/1.0 等不动）。
- **物理排序**（手册要点）：薄而密的低水云 opacity > 厚而稀的卷云（两条诊断廓线对比）。
- 边界：单层 condensate 层 → NaN → 回退；零/负含水 → τ=0 → opacity 0。
- **回归**：全量 `pytest -m "not integration"` 全绿；`grid_score` 1e-9、`test_metamorphic_physics`（走 cover% 不经 `_layer_opacity`）不受影响；`test_obstruction_grading` 直接构造层 → 不受影响。

## 限制 / 后续

- 有效半径为固定假设（手册只给定性）；未来若有卫星反演 r_e/COD 可替换。
- 多次散射、相函数不建模——只取消光厚度 → 透过率 `1−e^{−τ}` 作不透明度代理。
- 接 FA-G5 光追后，逐列遮挡判定自动用上真实 τ（更准的"杂云挡光"）。
