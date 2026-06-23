# 标准化垂直廓线 — 设计 (#6)

Parent epic: #4 · Milestone: v0.2 · Branch: `codex/6-normalize-profile`

## 目标

把任意来源的原始 `AtmosphericProfile`(#9)统一成可比较、可画图、可诊断云层的
物理廓线 `NormalizedProfile`:计算 RH、露点、几何高度,按高度严格排序,集中
单位/常量。

## 模块

- **`predictor/thermo.py`** — 热力学转换与常量(集中管理,评分代码不再散落魔法
  常量)。标量/numpy 通用,缺测传播 NaN:
  - `saturation_vapor_pressure_hpa(T_K)` — Magnus(over water, Bolton 1980)
  - `specific_humidity_to_rh(q, T_K, p_hPa)` — e = p·q/(ε+(1−ε)q),RH 限 0–100
  - `dewpoint_k(T_K, RH%)` — Magnus 反解,结果 ≤ T
  - `geopotential_to_geometric_height(H, lat=None)` — z = R·H/(R−H),R=6371 km
  - 常量:`EARTH_MEAN_RADIUS_M`、`EPSILON=0.622`、Magnus 系数
- **`predictor/profiles.py`** — 新增 `NormalizedProfile` 数据类型(与 Profile/Cube
  同处),显式区分 `geopotential_height_m`(模式能量高度)与 `geometric_height_m`
  (真实海拔)。
- **`predictor/normalize.py`** — `normalize(AtmosphericProfile) -> NormalizedProfile`。

## normalize 流程

1. 由位势高度算几何高度。
2. 可用层 = 几何高度与温度皆有限;按几何高度升序稳定排序。
3. 折叠重复高度(`diff > 0`),保证严格单调递增。
4. RH:`q` 有限时由 q/T/p 计算(规范路径,跨源可比),否则回退源 RH;限 0–100。
5. 露点由 T、RH 计算,≤ T。
6. 其余变量按同一索引重排。

## 验收标准映射

- [x] 压力层按几何高度严格排序并处理重复/缺层 → 排序 + diff>0 折叠 + 有限性掩码
- [x] 由 T、q、p 计算 RH 和露点,限物理范围 → `thermo` + clip
- [x] 位势高度与几何高度定义明确 → `NormalizedProfile` 两字段 + docstring
- [x] 单位转换集中管理 → `predictor/thermo.py`
- [x] 数值结果用已知样例和边界条件测试 → `test_thermo.py` / `test_normalize.py`
