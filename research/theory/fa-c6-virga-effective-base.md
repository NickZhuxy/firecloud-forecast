---
stage: claude-draft
factor: FA-C6
parent: single-point-fidelity-audit.md (§3.B FA-C6)
authority: 人工火烧云预报速成.pdf §2.2.2（纤维状/幡状）/ §4.2.1(1) / §1.4.3
---

# FA-C6 — 落幡/虹幡压低有效云底 + IR 顶→底推断

> 事实层与推导 Claude 起草；判断层（温度门槛、RH 门槛、延伸上限、τ 下限）待 Nick 复核。
> 依赖 FA-C1（逐层 τ，已并入）。

## 1. 问题：云底从不被修正，落幡不存在于模型里

审计 §3.B：`cloud_top.py`（#15）对**云顶**保真度好，但**云底**——抛物线几何的关键量
（顶点、reach、时长全由它出）——从不被订正；`cloud_motion.py` 自承
"passive IR does not constrain cloud base"。落幡（虚幡/降水线）压低有效云底未建模。

手册 §2.2.2 的物理（纤维状结构）：

> "如果一片可能形成火烧云的层状云底部出现了纤维状结构，意味着层状云云底出现降水。
> ……这也意味着层状云**实际的云底高度下降了，会影响火烧云出现的范围、时间和可能性**。
> 不均匀的**浓密幡状云还会挡住阳光**，使得火烧云的范围大打折扣。"

高积云落幡（§2.2 图 2.23）：温度低于 **−20 ℃** 时落幡云洞常见（贝吉龙效应）；
虹幡（§2.7 附近，火烧幡状云中的彩虹）同源。柱现象经验："云底（**不算落幡**）温度
在 −10 ~ −25 ℃"——手册自己就把 étage 归属与落幡分开：**幡压低的是有效几何底，
不改变云层的身份**。

## 2. 设计 A（核心，离线）：廓线诊断的虚幡延伸

落幡的可诊断前提（全部来自已有廓线量）：

1. **云层能产生降水物**：`optical_depth ≥ τ_min = 1.0`（薄卷丝几乎不掉幡；FA-C1 量）
   且 source=condensate（RH 兜底层没有含水量证据）；
2. **冰相/过冷倾向**：层底温度 `T(base) ≤ −10 ℃`（手册高积云 −20 ℃ 落幡云洞常见，
   一般幡更早出现；判断层默认取 −10，扫描留待复核）；
3. **底下的空气足够湿**：幡在不饱和空气里边落边蒸发——沿层底向下逐级
   `RH ≥ 60%` 的**连续**湿层就是幡能到达的深度。

**延伸量** `virga_extension_m = min(连续湿层深度, 1500 m 上限)`，挂在
`CloudLayer.virga_extension_m`（默认 0.0，加字段对既有构造零影响）。
干燥次层（RH<60）⟹ 0；暖底 ⟹ 0；薄层 ⟹ 0——三条否决保证典型场景逐位回归。

**消费**（有效底 = `base_m − virga_extension_m`）：

- [features.py](../../predictor/features.py) 画布底：`cloud_base_m` 用有效底
  （顶点/reach/时长/等效底链条全自动跟随——"影响范围、时间和可能性"）；
  **étage 归属仍用真底**（手册"不算落幡"）。
- [ray_path.py](../../predictor/ray_path.py) 光追跨度：遮挡判定改为
  `base_m − virga_extension_m ≤ h_ray ≤ top_m`——上游浓密幡挡光
  （"使得火烧云的范围大打折扣"）。不透明度仍由 `_layer_opacity` 判
  （只有本就浓密的层，其幡才挡光；薄层幡不额外造遮挡）。

## 3. 设计 B（伴侣纯函数）：IR 顶→底推断

手册 §4.2.1(1) 的工作流：IR 亮温 → 探空上找对应层 → **读那一层的模式云底**。
#15 已实现顶订正纯算法（`correct_cloud_top`）但从未接线（repo 无消费者——#15 的
遗留）。本项补齐它的底伴侣：

- `infer_base_from_corrected_top(model_base_m, model_top_m, correction)`：
  当订正采用卫星顶（`source == "satellite"`）时，**保持模式厚度**平移云底
  `base = corrected_top − (model_top − model_base)`；保留模式顶（`"model"`）时底不动。
  厚度是模式对该层最稳的量（§4.2.1 图 4.21 的偏差解读正是"厚度被低估或云底被低估"
  ——无从分辨时保厚度是中性选择；§1.4.3 四类亮温误差由顶订正的置信度承担）。
- 纯函数、离线可测；接线到卫星实时路径 = #15 遗留 + integration 标记，**不在本项**
  （记录于 [[firecloud-issue-15-status]] 方向）。

## 4. 验证设计（先写失败测试）

1. **虚幡存在性**：冷底（−15 ℃）浓层（τ≥1）+ 底下连续 RH 70% 湿层 ⟹
   `virga_extension_m > 0` 且 ≤ 上限；湿层被 40% 干层截断 ⟹ 延伸止于干层。
2. **三条否决**：暖底（+5 ℃）/ 干次层（RH 30%）/ 薄层（τ<1）⟹ 0（回归锁）。
3. **有效底进几何**：同场景带虚幡 vs 不带 ⟹ `Features.cloud_base_m` 更低；
   étage 归属不变（真底）。
4. **metamorphic**：virga 延伸只会缩短 reach ⟹ sunward gate/composite 单调不增。
5. **光追**：150 km 处不透明中云,底在射线上方 500 m,虚幡 600 m ⟹ blocked;
   无幡 ⟹ clear。
6. **顶→底**：卫星顶被采用 ⟹ 底随厚度平移；保留模式顶 ⟹ 底不动。
7. **回归**：全量离线套件绿。

## 5. 变更清单

- [clouds.py](../../predictor/clouds.py)：`CloudLayer.virga_extension_m`（默认 0）、
  `VirgaConfig`、诊断尾部的虚幡标注 pass。
- [features.py](../../predictor/features.py)：画布有效底（étage 用真底）。
- [ray_path.py](../../predictor/ray_path.py)：遮挡跨度下沿 − 虚幡。
- [cloud_top.py](../../predictor/cloud_top.py)：`infer_base_from_corrected_top`。
- 不动：国家/1-D 路径（无逐层诊断）、卫星实时接线（#15 遗留）。

参考：手册 §2.2.2（纤维状=降水=云底下降+浓幡挡光）、§2.2（落幡云洞 −20 ℃）、
§4.2.1(1)（IR→探空→云底工作流）、§1.4.3（亮温误差）；
[single-point-fidelity-audit.md](single-point-fidelity-audit.md) §3.B FA-C6。
