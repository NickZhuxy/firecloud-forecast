# CLI 阶段进度 + 报错人话化 设计稿(#105 Story A+C)

> 状态:**待 Nick 过审**。epic [#105](https://github.com/NickZhuxy/firecloud-forecast/issues/105) 三痛点里的"盲(看不到进展)"+"吓人(看不懂的报错)"。
> 提速(Story B 气压数据并行)是独立设计,**不在本稿**。

## 1. 问题(实测)

bare `firecloud` 冷缓存慢链路跑:CLI 全程只在最后 `print` 出图路径,中间十几分钟
静默;`generate_product` 里任何异常直接冒泡成**裸 traceback**;自动重试用
`_retry_transient` 打 `logger.warning("... transient error (attempt 1/3): ReadTimeoutError(HTTPSConnectionPool(...))")`
——完整异常 repr 刷屏,用户读起来就是"报错了/不稳定"。40 分钟零产出且不知道
发生了什么,就是这三条叠加的结果。

## 2. 范围

- **A. 阶段进度框架**:CLI 拥有顶层框架(计划 → 每产品头 → 每产品结果+耗时 → 总结),
  内层阶段行复用/补齐模块 INFO。
- **C. 报错人话化**:重试日志压成一行;每产品 try/except + 分类建议;意外异常兜底。
- **D 的最小切片**:每产品独立 try/except,单产品失败不拖垮整批(日落挂了仍出日出)。
  完整韧性(部分成功的元数据标注等)留给 epic 后续。

**不在本稿**:Story B(并行下载,提速主杠杆,另设计);#104(单文件下载心跳,已实现待审)
是本稿内层下载行的下层,互补。

## 3. 设计 A:CLI 顶层框架 + 稀疏阶段行

**机制:logging + print,不穿透回调**。顶层框架是核心用户输出 → `print()`(始终显示);
内层阶段行是 `logger.info`(可被 `--quiet` 压掉,保留框架)。理由:回调穿透
`generate_product`→`build_national_field`→`gfs` 四层,改动面大且侵入签名;而 INFO
机制已接好,CLI 只需在**它已经掌握的边界**(产品循环)加框架。

CLI `main()` 产品循环:

```
firecloud —— 2026-07-07 · 日落+日出 · 全国
计划:2 个产品 × [地面/精修/卫星/渲染]  ·  缓存:冷  ·  预计 ~10–20 分钟(取决于网速)

[1/2] 国家日落图
  下载 GFS 地面场 (6 时次)… ✓ 8s        ← 复用 gfs.py 现有 INFO
  下载气压立体数据 f19: 34/89 MB (0.15 MB/s, ~6分)  ← 复用 #104 心跳
  精修 686 个候选格… ✓ 42s              ← 补:refine 起止行
  卫星临近订正… ✓(或"跳过:距日落 >2h")   ← 补:nowcast 起止行
  渲染… ✓
[1/2] ✓ output/2026-07-07/firecloud-cn-...png  ·  4分12s

[2/2] 国家日出图 …

总结:2/2 出图  ·  总耗时 9分3s  ·  下载 630MB
```

- **缓存冷热**:检查目标 cycle 的 cube/surface 缓存目录是否已有分片
  (`research/data/cache/gfs/...`);冷=需下载,热=秒级。
- **总下载量**:接 #102 设计稿第 4 项 `download_bytes_total`(surface + cube);
  若那项未落地,先用 `GFSSource.network_bytes` 汇总兜底。

## 4. 设计 C:报错分三类

1. **恢复性重试**(`_retry_transient` 内):`logger.warning` 从完整异常 repr 改成
   `⟳ 网络超时,自动重试 (2/3)…`(异常类型归一到"网络超时/连接中断",完整 repr
   降到 DEBUG 供排查)。
2. **终端失败**(`GFSUnavailable` 等已知):CLI 每产品 try/except 捕获,打中文摘要
   + 可操作建议:
   ```
   ✗ 日落图失败:NOAA 数据源连不上(已自动重试 3 次)
     多半是网络或 NOAA 源临时问题,不是你的操作。
     → 稍后重跑(已下载的分片会复用,不会重下)
     → 或加 --no-refine 先出粗图(跳过气压立体数据)
   ```
   然后 **continue 到下一产品**(D 最小切片)。
3. **意外异常**(未预期):兜底一句"出错了,通常不是你的操作问题",技术细节压一行;
   完整 traceback 藏在 `--verbose` 后(默认不吓人,排查可开)。

**退出码**:全部产品失败 → 非零;部分成功 → 0 但总结里标注 "1/2 失败"。

## 5. 开放决策(请 Nick 拍板)

**ETA 的诚实度**。你批准的预览里有"预计 ~15 分钟"。我的实现建议:**只在冷缓存时**
显示一个**粗区间**("~10–20 分钟,取决于网速")+ 缓存冷热标签,**不做**全程实时
倒计时——因为慢链路波动大(实测 110–190 KB/s),假精确的倒计时错了反而更伤信任;
真正的实时粒度由 #104 的**单文件** ETA 提供(那个是诚实的,基于已落盘字节)。
若你想要全程倒计时,我可以按已下/总字节推,但会经常跳变。**默认按粗区间做,除非你要倒计时。**

## 6. 验证设计(先写失败测试;全离线)

CLI 用假 source(不碰网络)驱动:
1. **成功路径**:假 source 出图 ⟹ stdout 含计划行、每产品头、阶段行、结果行、总结行
   (钉关键字与顺序)。
2. **终端失败**:假 source 抛 `GFSUnavailable` ⟹ 中文摘要 + 建议关键字("稍后重跑"/
   "--no-refine")、**continue 到下一产品**、退出码语义。
3. **意外异常**:假 source 抛 `RuntimeError` ⟹ 兜底句 + 无裸 traceback(除非 --verbose)。
4. **重试行**:`_retry_transient` 触发 ⟹ 日志是 `重试 (2/3)` 单行,无异常 repr。
5. **缓存冷热**:tmp 缓存目录空/满 ⟹ 头部标签冷/热正确。
6. **回归**:现有 `test_cli.py` 全绿(print 的 image:/metadata: 行保持)。

## 7. 变更清单

- `predictor/cli.py`:顶层框架 print、每产品 try/except 分类、`--quiet`/`--verbose`、
  缓存冷热探测、总结行。
- `predictor/gfs.py`:`_retry_transient` 日志压成人话行(完整 repr → DEBUG);
  补 refine/nowcast/render 阶段起止 INFO(在 national_field/national_product 的自然接缝)。
- `predictor/national_product.py` / `national_field.py`:阶段边界 INFO 行(若现无)。
- 不动:算法、下载逻辑、#104 心跳、Story B 并行。

## 8. 拆 story 建议

本稿可作**一个** story(A+C+D最小切片,都在 CLI 层,一次 TDD 交付),或拆成
C(报错,更小更快)+ A(进度)两个 PR。**建议合成一个**——它们共享 CLI 循环的
try/except 骨架,拆开反而重复搭架子。
