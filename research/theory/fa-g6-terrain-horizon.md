---
stage: claude-draft
factor: FA-G6
parent: single-point-fidelity-audit.md (§3.A FA-G6)
authority: 人工火烧云预报速成.pdf §1.2.1（平原假设）/ §1.2.4
---

# FA-G6 — 地形地平线遮蔽：观察者海拔下沉角 + 路径山脊挡光

> 事实层与推导 Claude 起草；判断层（基准缺失时的退化语义）待 Nick 复核。
> 承 FA-G5 光追载体（[ray_path.py](../../predictor/ray_path.py)）与 FA-A2 的
> "相对观察者基准超出量"判据结构。

## 1. 问题：高程已采样，但只用来掩蔽网格

手册 §1.2.1 的典型模型显式假设"**地形为平原或者海面**"——理想化。审计 §3.A：
`SunwardSample.elevation_m` 已经通过注入式 `elevation_fn` 沿路径采样
（[spatial.py](../../predictor/spatial.py)），但只在
[cross_section.py](../../predictor/cross_section.py) 里**掩蔽地形以下的网格单元**；

- **观察者自身海拔**不参与几何；
- 路径上**升起进光路的山脊对光追透明**——无云的山体挡不住掠射阳光（错）。

issue #56 验收明列"地形地平线遮蔽 horizon depression"。

## 2. 物理：下沉角与山脊挡光是同一件事的两面

地平线下沉角 `d(h) = arccos(R/(R+h))`（solar-geometry 笔记；平坦坐标系里体现为
观察者平面以下的可视域）。在手册 §1.2.4 的平坐标抛物线模型里：

- **观察者升高** ⟹ 上游地形相对观察者平面**变矮** ⟹ 掠射光更容易越过 ⟹
  光路更通、更长（下沉角效应的平坐标等价表述）；
- **上游山脊**升出观察者平面、抛物线在其附近压低 ⟹ 山体截断低角度阳光
  ——与云层遮挡、FA-A2 浓气溶胶超出层同构。

## 3. 设计：地形超出量否决（沿用 FA-A2 基准结构）

截面新增逐列地形高程（数据已有，只是没存）：

- `SunwardCrossSection.terrain_elevation_m_per_column: list[float|None] | None`；
  `build_cross_section` 直接从 `path.samples[j].elevation_m` 填充（全 None ⟹ 属性
  None，与 `aerosol_optical_depth_per_column` 同约定）。

`trace_ray_clearance` 增加第三类遮挡（次序：云层 → **地形** → 气溶胶）：

> 基准 `t₀` = 观察者列（`distance < min_path_distance_km`）的地形高程。
> 第 `j` 列地形超出量 `Δt_j = t_j − t₀`。若 `Δt_j > 0 且 h_ray(l_j) ≤ Δt_j`
> ⟹ 该列山体挡光（`blocked_layer=None`，地面类遮挡）。

- **为什么不用绝对海拔当地板**：抛物线顶点掠 0——绝对地板会让**任何**正海拔的
  均匀高原（成都平原 ~500 m、昆明 ~1900 m）否决一切光线（FA-A2 §2 同一几何错配）。
  基准差表述下，**均匀高原 = 基准平移 = 永不自我否决**，平原/海面路径逐位回归。
- **观察者在山上、上游是低地/矮脊**：`Δt_j < 0` ⟹ 不否决——升高看得更远
  （下沉角）自然涌现。
- **观察者在谷底、上游山脊**：`Δt_j > 0`、顶点附近 `h_ray` 米级 ⟹ 否决——
  山脊吃掉贴地段。
- **退化**：`t₀` 缺失（观察者列无高程）⟹ 跳过全部地形检查（没有基准就不猜；
  避免绝对地板复活）；单列 `t_j` 缺失 ⟹ 该列不查。全 None（现状国家/1-D 路径与
  既有测试fixture）⟹ 行为逐位一致。

**已知近似（记录，不在本项修）**：等效底深度仍用云底 AMSL 相对 z=0 计（现状），
高海拔平坦地区 reach 有 ~√(1−t₀/h_cb) 量级的高估；基准差机制不受影响。挂 P3 尾巴。

## 4. 验证设计（先写失败测试）

1. **均匀高原不自我否决**：全列 500 m ⟹ clear（核心不变量，防绝对地板）。
2. **上游山脊挡光存在性**：观察者 0 m、150 km 处山脊 800 m（该处 h_ray≈7 m）
   ⟹ blocked at 150、`blocked_layer is None`。
3. **下沉角**：观察者 1000 m、同一 800 m 山脊 ⟹ clear（升高越过）。
4. **基准缺失退化**：观察者列高程 None + 山脊已知 ⟹ clear（跳过地形检查）。
5. **装配**：`build_cross_section` 填充 `terrain_elevation_m_per_column`；
   全 None 路径 ⟹ 属性 None（回归锁）。
6. **回归**：全量离线套件绿（默认 None ⟹ 现状逐位一致）。

## 5. 对预测规则的启示（变更清单）

- [cross_section.py](../../predictor/cross_section.py)：新字段 + 装配填充。
- [ray_path.py](../../predictor/ray_path.py)：地形超出量否决（云→地形→气溶胶）。
- 不动：1-D `SunwardIlluminationGate`、国家 grid（无高程数据源）、
  `equivalent_cloud_base_*`（AMSL 基准近似记录在案）。

参考：手册 §1.2.1（平原假设原文）、§1.2.4（视线-高度角）；
[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.A FA-G6；
[fa-a2-path-extinction.md](fa-a2-path-extinction.md) §2（基准差判据的几何论证）；
[solar-geometry.md](solar-geometry.md)（下沉角 d(h)）。
