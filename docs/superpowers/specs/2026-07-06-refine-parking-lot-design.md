# #59 停车场四项 — 设计过审稿

> 状态:**待 Nick 过审**。四项均为 #59(全国场物理升级,已收官)验证期间记录的
> 后续小项,当时约定"需要先过设计"。本稿每项给出:现状(代码锚点)→ 问题 →
> 方案选项 → 建议 → 验收设计 → 成本。批准后各自开独立 story 实现(TDD)。

---

## 1. refine 跳过候选的降权

**现状**:`national_refine.refine_national_probabilities`(threshold=0.50,
`max_refine_cells=4000` 上限)按 screen 概率降序截断;超出预算的候选**保留原始
screen 值**并计入 `cells_skipped`(PR-B 的三级概率透明化:metadata `refined_mask`
+ PNG 实心点标注 refined)。

**问题**:live 验证(2026-07-02)显示 refine 把 ≥0.50 的 screen 格从 1419 砍到
686(−52% 假阳性)。全国活跃日 7912 候选 > 4000 上限——近半候选保留**系统性偏
乐观**的 screen 值;标注了"未精修"但数值本身没有校正。

**选项**:
- **A. 全局经验存活率乘子**:当次运行内 `factor = (refine 后仍 ≥0.50 的格数) /
  refined 格数`,乘到所有 skipped 候选上。自校准、一行公式;缺点:cap 按概率降序
  截断 ⇒ skipped 群体的 screen 概率**系统性低于** refined 群体,同一乘子对低分段
  偏松。
- **B. 固定折扣**(如 live 标定的 ×0.48):最简单;随季节/天气漂移,会过时。
- **C. 只改显示不改数值**:skipped 候选降一档概率级 + PNG 空心点。零假精度;
  但下游任何吃数值的消费者(阈值统计、后续对比)仍拿到乐观值。
- **D. 分箱存活率乘子(建议)**:在 refined 群体内按 screen 概率分箱
  (0.05 步长),每箱算存活率(refine 后仍 ≥0.50 的比例),skipped 候选按其
  screen 概率取所在箱的乘子;样本 < 30 的箱向邻箱合并,全空时退化到 A 的全局
  乘子。metadata 记录 `skipped_downweight`(分箱表 + 生效格数)。

**建议**:**D**(A 为退化路径),同时把 C 的 PNG 空心点做上(视觉区分便宜且诚实)。
乘子只作用于 skipped **候选**(screen ≥ 0.50 未精修),不碰 <0.50 的非候选格。

**验收设计**:合成场(构造分箱已知存活率,断言 skipped 格乘对箱)、单调性
(降权不抬值;screen 值高的 skipped 格降权后仍 ≥ 值低者)、cap 拉满时(全部
refined)无 skipped ⇒ 场逐位不变、metadata schema、PNG 空心点渲染测试。

**成本**:低-中(纯后处理,无网络;~1 个函数 + 渲染分支)。

---

## 2. 0.30–0.50 概率安全带

**现状**:候选 = `screen >= 0.50`(`national_refine.py:149/168`)。screen 对比
单点真值 mean|Δ|=0.059(live §2)——0.30–0.50 段的格有翻越 0.50 的可能(假阴性),
今天永远不被精修。

**方案(单一,参数化)**:候选集扩到 `screen >= refine_band_floor`(默认 0.30),
**预算排序保持两段式**:先 ≥0.50 主候选(降序)吃预算,剩余预算给 0.30–0.50
安全带(降序)。上限语义(`max_refine_cells`)不变——主候选永远不会被安全带
挤出(活跃日 cap 被主候选占满 ⇒ 行为与今天完全一致;平静日空余预算用来消灭
假阴性)。metadata 记录 `band_candidates` / `band_refined` / `band_promoted`
(带内精修后 ≥0.50 的格数——这是本项的直接价值度量)。

**与第 1 项的交互**:安全带里被跳过的格**不降权**(它们本来就 <0.50,不进产品
阈值;降权只针对 ≥0.50 的 skipped 主候选)。

**建议**:默认 ON(`refine_band_floor=0.30`,`None` 关闭)。理由:零主候选回归 +
warm-rerun 计算 ~0.05 s/格,4000 格预算上限的额外计算最多 ~200 s,只发生在
平静日(预算空余时)。

**验收设计**:合成场(带内格精修后越过 0.50 出现在产品/统计;主候选优先不被
挤出——构造候选数=cap 断言带零精修)、`band_promoted` 记账、`--no-refine`/
无 cube_source 路径不受影响、活跃日回归(candidates>cap ⇒ 与现状逐位一致)。

**成本**:低(候选掩码 + 排序改两行,metadata 三字段)。

---

## 3. 局部产品更细网格的卫星运动

**现状**:Stage C(#84)在 **0.25°** 网格上做连续帧互相关,速度地板 =
1 px / pair gap;`pair_gap_min=30`(`nowcast.py:39-42`)⇒ 地板 ≈ 0.5°/h ≈
**55 km/h**——低于它的真实运动量化为零,亚像素位移诚实 no-op("below grid
resolution")。局部精细产品网格是 **0.1°**(`local_field.py:63`)但卫星运动
沿用全国 0.25° 重采样 ⇒ 局部产品对 <55 km/h 的层状系统平移无感,Stage C
只对急流卷云/飑线/台风生效。

**方案**:`cloud_motion`/`nowcast` 的重采样分辨率参数化(`regrid_deg`,全国
默认 0.25 不变);**局部产品**传 0.1° ⇒ 地板 = 0.1°/0.5 h ≈ **22 km/h**
(若同时把局部 pair 跨度放宽到 60 min ⇒ ~11 km/h,但帧龄变旧,时效性受损——
**建议先只改分辨率、保持 30 min pair**,11 km/h 版本视 22 km/h 的实测效果再议)。
局部域小(150 km 半径 ⇒ ~3°×3° bbox),satpy 0.1° 重采样成本可忽略;帧回溯/
边缘 de-wrap/新鲜度门逻辑全部复用。

**建议**:上述参数化 + 局部 0.1°/30 min。全国路径零变化。

**验收设计**:合成帧对(0.1° 网格上 0.15° 位移 ⇒ 检出且修正方向正确;同一
位移在 0.25° 网格 no-op——地板对照)、地板公式断言、局部产品端到端
(integration 标记,真卫星帧)。

**成本**:低-中(参数化 + 局部调用点;卫星 IO 已有)。

---

## 4. refine 下载量统计漏算 cube 字节

**现状**:`national_field.py:279-288` 顶层 `download_bytes` /
`additional_download_bytes` 只汇总 **surface** grids;refine 的
`cube_download_bytes`(PR-B 加的 `GFSSource.network_bytes` 记账,缓存命中不计)
单独放在 refine 子字典(`national_field.py:269`)。任何读顶层字段/日志"MB"的
消费者拿到的是 surface-only(live 数据:cube 630 MB vs surface 几十 MB——
**主项被漏了一个量级**)。

**方案**:顶层字段语义不动(向后兼容),新增:
- `download_bytes_total` = surface(既有)+ `cube_download_bytes`(refine 存在时);
- `download_breakdown = {"surface": …, "cube": …}`;
- 产品日志行统一打 total 并括注 breakdown。
缓存命中不计入(维持现语义,跨运行 warm rerun 应显示 ~0)。

**建议**:如上,纯记账。

**验收设计**:合成 source(标称字节数)断言 total/breakdown、无 refine 路径
total==surface、缓存命中不累计、metadata schema。

**成本**:低(十几行 + 测试)。

---

## 实施顺序建议(批准后)

**4 → 2 → 1 → 3**:先把量度修对(4,半天),再消假阴性(2,直接产品价值),
再校乐观值(1,依赖 2 定稿后的候选语义),最后卫星细网格(3,含 integration
验证,最重)。每项独立 story + `feat/<N>-…` 分支 + TDD,互不依赖可并行,
但 1 的分箱实现要等 2 的候选集语义定稿。
