# 诊断结构 vs Open-Meteo 云量一致性 — 设计 (#35)

Parent epic: #4 (integration) · Branch: `codex/35-gfs-cover-coherence`
来源:PR #34(#31)review 的 out-of-scope 跟进。决策:**拉 GFS 云量(CFR)做二次源**。

## 问题

`MidHighCloudPresence`(weight-2 gate)与 `CloudCoverSweetSpot` 用 Open-Meteo
覆盖率。当 GFS 诊断出高云画布、Open-Meteo 却报该层 ~0% 时,评分被 Open-Meteo
归零,与诊断结构矛盾。

## 设计(同源化:GFS 结构 + GFS 覆盖率)

- **`predictor/gfs.py`**:`fetch_cloud_cover(lat, lon, valid_time) -> EtageCloudCover`
  拉 GFS 自带的三档云量 `LCDC/MCDC/HCDC`(与 HRRR 同 shortname:lcc/mcc/hcc),
  最近格点。`_cover_from_dataset` 鲁棒取值(squeeze 残余维),且**三档全缺时
  raise**(让调用方回退 Open-Meteo,而非静默 0% 误把 gate 归零)。复用
  `_load_with_fallback`(loader 参数化)+ 独立 `_cover_cache`。
- **`predictor/features.py`**:`derive(cloud_layers=, cloud_cover=)`。有诊断 +
  GFS 覆盖时,`diagnosed_mid_high_cover_pct = max(MCDC, HCDC)`(**与 canvas tier
  无关**——低层 canvas 不会抹掉 GFS 自报的中/高云),`canvas_cloud_pct` 显示
  canvas 档自身覆盖率。
- **`predictor/rules.py`**:`_canvas_cover` 优先 `diagnosed_mid_high_cover_pct`,
  否则 snapshot `max(mid, high)`;`MidHighCloudPresence`/`CloudCoverSweetSpot`
  都走它。`score_snapshot(..., cloud_cover=)` 透传。
- **`app/server.py`**:`_diagnose_cloud_cover`(异常吞掉→None),仅在已诊断出
  layers 时取(单点详情路径);全国网格不触碰。

## Review 关键修复(workflow-backed code review)

- **Blocker**:原设计用"canvas tier 覆盖率",低层 canvas → 0.0 → 覆盖 snapshot
  真实中/高云 → 把 weight-2 gate 归零。改为 GFS `max(MCDC, HCDC)`,与 tier 解耦。
- 鲁棒性:`.item()` 改 ravel 取值;三档全缺 raise → 安全回退。

## 已知取舍 / 跟进

- 详情路径(GFS 同源)与全国网格(Open-Meteo 快路径)在 GFS/Open-Meteo 分歧点
  可能给出不同分数——这是有意的"详情更准、网格更快"分工(同 #30)。
- structure 与 cover 各自一次 `_load_with_fallback`,理论上极端情况下(其中一个
  在主 cycle 解析失败而回退)可能取自不同 cycle;二者同源同文件、缓存便宜,实际
  几乎不发生,作为次要事项记录。

## 验收

- [x] GFS 自报覆盖率解决与 Open-Meteo 的分歧(presence 不再被误归零)
- [x] 低层 canvas 仍能看到 GFS 中/高云(回归测试)
- [x] 无 GFS 覆盖 / 无诊断时回退 snapshot,行为不变(现有测试通过)
- [x] 243 passed, 3 deselected
