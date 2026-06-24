# 全国场逐格日落多时间步评分 — 设计（#43）

Parent epic: #3 · Depends on: #19 · Branch: `codex/43-percell-sunset`

## 问题与目标

#19 用中国域中心日落对应的单一 GFS valid time 评分整个 73–136°E 区域。
同一张图上的东西部格点因此不是各自日落附近的大气态。#43 要恢复逐格日落语义，
同时保持全国场的一次解码/整场向量化优势：下载少量覆盖日落范围的整点 GFS 地面场，
逐格选择离该格日落最近的时次，拼成一个输入场后调用一次 `score_grid`。

## 设计

### 1. 日落时间场

新增 `predictor/sunset_grid.py`：

- 在目标 bbox 上构造包含边界的 4° 粗网格；粗格点用 Astral 计算 UTC 日落。
- 把 aware datetime 转为 Unix 秒，在经度方向、再在纬度方向做一维线性插值，得到
  双线性细网格；输出 `datetime64[s]`，明确表示 UTC，避免 object datetime 的内存成本。
- 粗网格会覆盖真实 GFS 裁剪轴；支持升/降序目标轴，但内部采样轴始终升序。
- 中国域不会遇到极昼/极夜；若 Astral 在边缘抛 `ValueError`，以当地太阳时 18:00
  （`18 - lon/15` UTC）作可复现降级值，避免整张图失败。
- 单元测试把若干非粗格点的插值结果和逐点 Astral 真值比较，容差 2 分钟。

### 2. GFS 时次覆盖与逐格选择

- 从粗日落场的最小/最大时间向外取整到 UTC 小时，生成连续整点 valid times；因此每格
  总有左右相邻时次，最近时次误差不超过 30 分钟。
- overlay 把与最终裁图相同的中国国境 mask 传给选时范围计算；0.5° 范围采样覆盖边界
  和内部极值，避免为矩形 bbox 中不可见的西北/东北角额外下载两个小时。矩形场仍完整
  评分，mask 只影响所需时次和报告的日落范围。
- `build_national_field(gfs_source, bbox, target_date)` 批量取得各 valid time；
  `GFSSource.fetch_surface_grids` 把全部小时固定到同一 GFS run，任一小时不可用时整批
  回退同一旧 run，避免跨 6 小时 cycle 边界形成虚假经向接缝。所有返回网格都按
  lat/lon 升序重排并校验坐标完全一致；不一致时明确报错，禁止静默拼接不同格点。
- 对每个格计算与 valid times 的绝对时间差并 `argmin`；恰好半小时时选择较早时次。
  云量、2m RH、能见度使用同一索引场选择，避免变量间时次错位。
- NaN 降级仍在选择后执行（RH 50%、能见度 25 km），最后只调用一次 `score_grid`。
  现有 `test_grid_score` 继续钉住标量规则 1e-9 等价；新增测试再把多时次逐格结果与逐点
  `RuleBasedPredictor` 比较到 1e-9。

### 3. 数据量和可观测性

`NationalField` 记录：

- `valid_times`、`sunset_range_utc`、`surface_fetches` 与相对旧单时次的
  `additional_surface_fetches`；
- 所有裁剪后数组的 `decoded_input_bytes` / `additional_decoded_input_bytes`；
- 按 Herbie inventory 的连续 GRIB message 分组复算 HTTP Range 字节数，统计
  `download_bytes` / `additional_download_bytes`。它表示本次所需原始 payload 规模；
  Herbie 已命中磁盘缓存时实际网络流量可以为 0，因此不能把它表述成实时网卡流量。

overlay 日志输出上述新增量、总运行时间和峰值内存；API 元数据改为
`valid_times_utc` 与 `sunset_range_utc`，不再伪造单一 `valid_utc`。评分语义变化后缓存版本
由 v3 升到 v4。

## 验收映射

- [x] 粗网格 Astral + 双线性插值得到逐格日落 UTC，误差测试 ≤ 2 分钟。
- [x] 获取覆盖中国日落范围（含 bbox 内部极值）的连续整点 GFS 时次。
- [x] 多时次固定同一 GFS model run，批量回退保持 cycle 一致。
- [x] 云/RH/能见度逐格选最近时次后向量化评分；平局规则和坐标校验有测试。
- [x] 多时次结果与逐点等价预测在 1e-9 内一致。
- [x] 记录新增时次数、解码字节及原始 GRIB Range payload 字节。
- [x] overlay 缓存 schema bump；离线全套与 live surface integration 通过。

## 非目标

- 不做 GFS 时间线性插值（需求是“最近日落时次”，且插值会改变离散云诊断语义）。
- 不引入 Zarr/分块持久缓存（#17）。
- 不改变 `score_grid` 的规则数学或地图配色。

## 2026-06-24 生产尺寸实测

真实 GFS 0.25°、bbox 17–54°N / 73–136°E、Natural Earth 中国国境：

- 37,697 格点；国境内日落范围 10:53:55–14:35:53Z；valid times 10–15Z（6 个，
  相对旧单时次 +5）。若错误使用整个矩形会取 09–16Z 共 8 个，国境 mask 避免 2 个。
- GRIB Range payload 35,191,577 bytes，新增 29,289,438 bytes；裁剪后解码输入
  9,066,576 bytes，新增 7,555,480 bytes。
- 端到端构场 141.642 s，`tracemalloc` 峰值 234.048 MB；概率有限且范围 [0, 1]。
