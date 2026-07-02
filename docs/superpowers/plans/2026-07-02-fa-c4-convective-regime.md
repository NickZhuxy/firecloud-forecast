# #86 FA-C4 斜温图稳定度与对流/层状判别 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 单点 detailed 链路能从廓线判别对流/层状云况:浓积云级切 §1.2.3 垂直线时长模型、按 §4.1.2 明示+降置信,metadata/geometry 暴露诊断;层状路径零回归。

**Architecture:** 理论依据全在 `research/theory/fa-c4-skewt-stability-convective-regime.md`(用户已核)。四层:`thermo.py` 加气块抬升纯函数(干绝热/露点线/LCL/伪绝热/状态曲线)→ 新 `predictor/stability.py` 判别器(右偏厚度→regime,手册 §2.2 阈值+边缘带)→ `geometry.py` 加 `convective_duration_min`(√(2R·h_CT)/v,复用 FA-G4 的 v)→ `score_point_with_cube` 诊断 observer 廓线并后置处理 Forecast(damping 向 0.5、explanation 注记、geometry 块)。`rules.py` 的 modifier 管线不动。

**Tech Stack:** Python 3.11 · numpy · pytest;全离线合成廓线,零网络

## Global Constraints

- 测试命令:`PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest -m "not integration" -q`
- 提交信息中文、不加 Co-Authored-By;TDD;覆盖率按测试清单论证
- 手册常数为准:Γd=9.8℃/km、露点线 1.2℃/km ⇒ LCL 系数 1/(9.8−1.2) km/K ≈116.3 m/K;湿绝热用 AMS/Bolton 伪绝热式(理论笔记 §2.1)
- 判别阈值(可配置):congestus ≥2000 m、mediocris ≥400 m、marginal 带 ±500 m
- **零回归保护**:全稳定廓线的 Forecast.probability 逐位不变;既有全部测试(610+)保持绿
- 分支 `feat/86-fa-c4-convective-regime`(已建);理论笔记已提交(e76a79a)

---

### Task 1: thermo 气块抬升原语

**Files:** Modify `predictor/thermo.py`;Test `predictor/tests/test_thermo.py`

**Produces:**
```python
DRY_LAPSE_C_PER_KM = 9.8          # 手册 §1.1.3,近地 3–4 km
DEWPOINT_LINE_C_PER_KM = 1.2      # 手册 §1.4.1 等比湿线
def lcl_height_m(t0_k, td0_k) -> float            # (T−Td)/(9.8−1.2)*1000,负差取 0
def moist_adiabatic_lapse_c_per_km(t_k, p_hpa) -> float   # 伪绝热(AMS/Bolton)
def parcel_profile_k(heights_m, t0_k, td0_k) -> np.ndarray
    # 状态曲线:LCL 以下干绝热;以上逐段用局地 Γm(T_parcel, p 由 heights 上的
    # 廓线气压传入?——不:签名带 pressures_hpa 参数,逐段积分)
```
签名定稿:`parcel_profile_k(heights_m, pressures_hpa, t0_k, td0_k)`(heights 升序,返回同长数组)。

- [ ] Step 1 失败测试(test_thermo.py 追加):LCL 线性(116.3 m/K,带宽 100–130 断言两点比值);饱和起抬 lcl=0;0<Γm≤9.8 且 T=−60℃、p=200hPa 时 Γm≥9.0(趋近干绝热);parcel 曲线在 LCL 以下斜率=−9.8、以上更缓;heights 单调性检查
- [ ] Step 2 确认失败 → Step 3 实现(伪绝热式:`Γm = 9.8·(1+Lv·rs/(Rd·T))/(1+Lv²·rs·ε/(cpd·Rd·T²))`,rs 由 `saturation_vapor_pressure_hpa` 折算;逐段 trapezoid 积分)→ Step 4 全量绿 → Step 5 Commit `feat(predictor): #86 thermo 气块抬升原语(LCL/伪绝热/状态曲线)`

### Task 2: stability 判别器

**Files:** Create `predictor/stability.py`;Test `predictor/tests/test_stability.py`(新)

**Produces:**
```python
@dataclass(frozen=True)
class StabilityConfig:
    congestus_min_depth_m: float = 2000.0
    mediocris_min_depth_m: float = 400.0
    marginal_band_m: float = 500.0

@dataclass
class StabilityDiagnosis:
    lcl_m: float
    unstable_top_m: float | None      # LCL 以上首个连续右偏区顶;无右偏 → None
    unstable_depth_m: float           # 右偏区厚度(无 → 0)
    regime: str                       # stratiform|cumulus_humilis|cumulus_mediocris|cumulus_congestus
    marginal: bool                    # |depth − congestus 阈值| ≤ marginal_band

def diagnose_stability(profile: NormalizedProfile, config=...) -> StabilityDiagnosis
```
地面层 = 廓线最低有效层;parcel 曲线 vs 环境温度,右偏 = T_parcel > T_env;
regime 由 depth 分级(<400 stratiform/humilis 合并为 stratiform?——**否**:humilis 也标出但不切几何;<400 → `cumulus_humilis` 仅当 depth>0,depth==0 → `stratiform`)。

- [ ] Step 1 失败测试:全稳定廓线(逆温/等温)→ stratiform,depth 0;教科书条件不稳定廓线(混合层 9.8 + 中层 7.5℃/km 环境、湿地面)→ congestus 且 unstable_top 等于构造值 ±1 层;环境整体 +5K → depth 单调不增;地面 +5K → 单调不减;depth 恰在 2000±500 → marginal=True;阈值 ε 扰动不翻转远离阈值用例
- [ ] Step 2–5:确认失败 → 实现 → 全量绿 → Commit `feat(predictor): #86 条件不稳定判别器(右偏厚度→积云分级)`

### Task 3: 对流时长几何

**Files:** Modify `predictor/geometry.py`;Test `predictor/tests/test_geometry.py`(按现有该文件惯例;若无则新建)

**Produces:** `convective_duration_min(cloud_top_m, lat) -> float` = √(2R·h_CT)/v(v=representative_terminator_speed_km_min;h≤0 或 v≤0 → 0.0)。注释注明 = 层状 characteristic 的一半、h 取云顶非云底(§1.2.3)。

- [ ] Step 1 失败测试:∝√h(4h → 2×);伊春数量级(h=10 km、v 按 47.7°N 实算 → 15~25 min 区间);h=0 → 0
- [ ] Step 2–5 同上;Commit `feat(predictor): #86 对流云火烧云垂直线时长(√(2R·h_CT)/v)`

### Task 4: 接线 score_point_with_cube + 降置信

**Files:** Modify `predictor/sunward_section.py`;Test `predictor/tests/test_sunward_section.py`(按现有夹具)

**Produces:** `score_point_with_cube` 在 `normalize(cube.profile_at(...))` 后调 `diagnose_stability(observer)`;返回前:
- 一律 `forecast.geometry = {**(forecast.geometry or {}), "cloud_regime": diag.regime, "lcl_m", "unstable_depth_m", "regime_marginal": diag.marginal}`
- regime==congestus 且 not marginal:`convective_duration_min` 进 geometry;probability 向 0.5 收缩 50%(`p' = 0.5 + (p−0.5)*0.5`),`components["convective_regime_damping"] = 0.5`,explanation 追加 `;浓积云对流云况(§4.1.2 模式支持度低,建议临近实况)`
- marginal congestus:geometry 全暴露(含时长)但**不 damping**(边缘带只标注)
- 新 kwarg `stability_config: StabilityConfig = DEFAULT_STABILITY_CONFIG`

- [ ] Step 1 失败测试:稳定合成 cube(现有夹具)→ geometry.cloud_regime=="stratiform" 且 probability 与改动前逐位一致(零回归:直接对比未打补丁的期望值/旧断言不动);构造不稳定 cube(混合层+条件不稳定+湿地面)→ regime congestus、damping 生效(p 向 0.5 靠拢一半)、explanation 含"对流云况"、geometry 含 convective_duration_min>0
- [ ] Step 2–5;Commit `feat(predictor): #86 单点链路接对流判别——明示+降置信+垂直线时长`

### Task 5: metamorphic 扩充 + 收尾

- [ ] `test_metamorphic_physics.py` 追加:①环境变暖 → congestus 概率 damping 不减弱结论单调性(全稳定→不 damp;更不稳定→仍 damp);②时长 √ 缩放律(跨 Task3 已测,此处以 profile 级端到端一条)
- [ ] 全量绿;完成记录回写计划;`gh issue` #86 关联;push;PR(base main,Closes #86);记忆更新

## Self-Review

- 理论笔记 §5"启示"四条 ↔ Task 1/2/3/4 一一对应;§4 不变量 1–8 ↔ Task1(1,2)/Task2(3,4,5,8)/Task3(6,7)/Task5(端到端)✓
- 用户拍板 4 点:LCL 手册系数=Task1;伪绝热补公式=Task1;只有浓积云切几何=Task4(humilis/mediocris 只标注);§4.1.2 明示+降置信=Task4(damping 0.5 + explanation)✓
- 类型一致:`StabilityDiagnosis`/`StabilityConfig`/`convective_duration_min`/`parcel_profile_k(heights_m, pressures_hpa, t0_k, td0_k)` 全文一致 ✓
- 全国/局部产品不动(local_field 经 score_point_with_cube 自动获得 geometry 标注,但无渲染改动)✓

## 完成记录(2026-07-02)

5 任务完成,离线套件 **628 passed**(+18 个新测试:thermo 4 / stability 7 / geometry 4 / 接线 2 / metamorphic 1)。

**实现中被物理修正的两处**(理论笔记已同步):
1. 不变量 3 原表述"地面加热→右偏厚度不减"有误:固定露点下加热抬高 LCL,硬盖之下厚度可合法缩小 —— 单调不降的是**对流云顶**,测试与笔记均已改。
2. 等温层"盖不住"暖湿气块(+10K 跳变后气块还能再爬 1km+)—— 教科书夹具需要随高增温的真逆温;顶点落点带一到两个网格层的分辨率容差。

另:normalize 以比湿为水汽主变量重算露点,合成 cube 的"湿地面"必须写在 q 上(23 g/kg @925hPa ⇒ Td≈299K),RH 字段会被覆盖 —— 夹具坑,已注释在测试里。

交付形态:所有 detailed 单点 Forecast.geometry 恒带 `cloud_regime/lcl_m/unstable_depth_m/regime_marginal`;明确浓积云级追加 `convective_duration_min` 并 damping(0.5 系数、components+explanation 可解释);局部产品经同一入口自动获得标注。全国产品未动(后续按需)。
