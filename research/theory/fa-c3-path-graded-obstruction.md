---
stage: claude-draft
factor: FA-C3
parent: single-point-fidelity-audit.md (§3.B FA-C3)
authority: 人工火烧云预报速成.pdf §4.1.1-5（杂云核对项）/ §4.2.1(2)（卷云透明度分档）/ §4.2.2
---

# FA-C3 — 沿光路多层分级遮挡（杂云调光）；互照部分论证延后

> 事实层与推导 Claude 起草；判断层（互照延后的裁决、逐列累积近似）待 Nick 复核。
> 依赖 FA-G5 光追（已并入）。P2 梯队最后一项。

## 1. 现状与缺口

审计 §3.B 两个子项：

- **(a) 下层/杂云沿光路挡光**：FA-G5 之后，`trace_ray_clearance` 已对**不透明**
  （opacity ≥ 0.5）层做二值否决；FA-A2/A4/G6/C6 补齐了气溶胶/地形/虚幡。
  仍缺的是**半透明杂云的分级调光**：opacity < 0.5 的薄层今天对光路完全透明——
  一条掠射光穿过数百 km 的薄高积云幕应当被显著削弱（闷烧），而非无事发生。
- **(b) 云层间二次反射互照**：见 §4 的延后论证。

## 2. 手册物理：杂云不是有/无，是透光/半透明/封死三档

- §4.1.1-5 / §4.2.2 核对清单固定项："**有没有其他杂云挡住光路？**"——伊春算例的
  幸运恰在"层积云上方与下方以及云边界以外的区域空气非常干燥，因此基本没有杂云"。
- §4.2.1(2) 对卷云幕给出**透明度三分档**：透光（支持大烧）/ 半透明（**闷烧**）/
  不透光（封死天空）。半透明档正是二值否决表达不了的中间态。
- §3.2.3（图 3.x 附近）云洞判读："洞中间似乎有杂云干扰"——杂云以**程度**参与判断。

## 3. 设计：光路透过率 Π(1−opacity) 进照明 gate

`trace_ray_clearance` 在既有循环里累积**路径透过率**：

- `RayClearance.path_transmittance: float = 1.0`（新字段，默认 1 保持既有构造）。
- 射线穿过某列某层（`base−virga ≤ h_ray ≤ top`）时：
  - opacity ≥ 0.5：维持既有**二值否决**（早退，`path_transmittance=0.0`）；
  - opacity < 0.5：`T *= (1 − opacity)` 继续追。
- 地形/气溶胶否决不变（它们由"有效不透明"定义，无分级）。

`SunwardIlluminationGate`：clear 时把 1-D 几何得分乘以 `T`
（1.0 → T，边界坡道 → 坡道×T；0 与 None 分支不变——T 只调制**存在的**几何得分，
不改变组件缺席语义）。国家/1-D 无截面路径不变。

**逐列累积 = 掠射路径长度积分的粗离散**：一片横展薄幕被近水平射线穿越多列，
每列乘一次 (1−opacity)——列距（生产 `DETAIL_SUNWARD_DISTANCES_KM` 25 km）就是
积分步长。层的 opacity 标定自垂直穿越（τ/厚度），逐列连乘把"掠射在幕内走了
250 km"表达为 10 次垂直穿越的串联——量级正确（§4.2.1(2) 幕越长越接近封死），
分辨率依赖记录在案（生产列距固定，测试自证语义）。

**不重复计数**：观察者列被 `min_path_distance_km` 跳过——同柱画布遮挡仍归
`_obstruction_below`（LowCloudObstruction），光路调光只吃上游列。

## 4. 互照（二次反射）：论证延后（判断层，待 Nick 裁决）

审计 (b) "云层间二次反射间接照亮"：

- 手册通读后**没有可操作的互照公式**——最接近的文字是 §4.2.2"个别浓积云……
  没有严重的互相遮挡阳光的现象，都可能被霞光照亮"（说的是**互相遮挡**的反面，
  非二次反射增亮）；"间接照亮"的量化在手册中不存在。
- 与 **FA-S3（多次散射时长尾，owner 已定 P3 延后）** 物理同源：二次反射的能量
  收支属于多次散射建模。先于 FA-S3 单独发明一个互照启发式，违背"手册为权威、
  不虚构物理"的项目纪律（[[firecloud-authoritative-manual]]）。
- **建议**：FA-C3 交付 (a) 分级调光；(b) 并入 P3 的 FA-S3 一起设计。若 Nick
  希望现在就要一个保守启发式，可在复核时改判。

## 5. 验证设计（先写失败测试）

1. **分级存在性**：薄层（opacity≈0.05）横在光路 ⟹ `clear=True` 且
   `path_transmittance ≈ 0.95`；晴空 ⟹ 恒 1.0（回归锁）。
2. **连乘语义**：同一薄层跨两列 ⟹ T=(1−o)²（钉逐列积分近似）。
3. **二值否决不变**：不透明层 ⟹ `clear=False`、T=0（既有测试原样）。
4. **gate 调制**：clear 轨迹 + T=0.6 + 1-D 得分 1.0 ⟹ gate=0.6；
   None 分支不受 T 影响（组件缺席语义不变）。
5. **metamorphic**：在照亮路径上加一片半透明杂云，composite 严格不升
   （非平凡：确实下降）。
6. **回归**：全量离线套件绿（无杂云路径 T=1 逐位一致）。

## 6. 变更清单

- [ray_path.py](../../predictor/ray_path.py)：`RayClearance.path_transmittance` +
  循环内累积。
- [rules.py](../../predictor/rules.py)：`SunwardIlluminationGate` clear 分支乘 T。
- 不动：`_obstruction_below`（同柱）、国家/1-D、互照（§4 延后论证）。

参考：手册 §4.1.1-5 / §4.2.2（杂云核对项与算例）、§4.2.1(2)（透明度三档）；
[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.B FA-C3；
[fa-c2-canvas-layer-selection.md](fa-c2-canvas-layer-selection.md)（substance 的
0.5 地板同源于"薄≠无"哲学）。
