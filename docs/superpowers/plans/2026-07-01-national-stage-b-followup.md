# #59 全国 Stage B — 后续工作交接（live 验证 → PR-B）

> 交接文档，自包含。面向接手的 agent：先读本文，再按 §2 跑验证，最后按 §5 做 PR-B。
> 写于 2026-07-01。分支 `codex/59-national-field-upgrade`，PR **[#80](https://github.com/NickZhuxy/firecloud-forecast/pull/80)** 已开（Stage A + Stage B PR-A）。

## 0. TL;DR

Stage B 精修**引擎**已建好、测试全绿、并入 PR #80，但它在生产产品里**是休眠的**（`national_product` 不传 `cube_source`）。下一步分两段：

1. **先验证**（§2）：在**有网机器**上跑 `research/experiments/live_refine_validation.py`，量真实全国 refine 的 wall-time / 下载量 / 候选与精修格数。沙箱无外网，跑不了。
2. **再建 PR-B**（§5）：把 live `GFSSource()` cube 取数接进 `national_product` 默认路径，让精修真正生效 + 三级概率渲染，并用真实 GFS 缓存样本补基准。成本模型见 §3（已离线确立，不必重测）。

## 1. 现状（已完成）

- **Stage A** — `national_physics.build_sunward_screen`：地面场 1-D 日向 screen，接进 `grid_score` 的 `sunward_illumination` gate。（分支既有）
- **Stage B PR-A（本次）** — `predictor/national_refine.py`：`refine_field(...)` 对 screen 候选（`prob >= threshold`）按 `(valid-hour, tile)` 分组，每组一块共享 GFS 压力 cube，逐候选点 `score_point_with_cube` 跑完整 2-D 光追；snapshot 由已取地面场合成（免联网）。接进 `build_national_field` 开关后（`refine=True` + `cube_source`），**默认零回归**。
- 离线合成基准 `nationalization_spike.py::stage_b_refine`：overview→refine 的 MAE `0.6892→0.0053`、F1 `0.08→1.0`、FP `92→0`。
- 全量非集成套件 **560 passed**。设计/计划：`docs/superpowers/specs/2026-07-01-national-stage-b-refinement-design.md`、`docs/superpowers/plans/2026-07-01-national-stage-b-refinement.md`。

## 2. 立即任务：live-GFS 验证（在有网机器上）

沙箱无外网出口（DNS 解析 `noaa-gfs-bdp-pds.s3.amazonaws.com` 失败）。在**用户自己的 Terminal**（非 Claude 沙箱）里跑：

```bash
cd /Users/nickzhu/Desktop/Projects/firecloud-forecast
PYTHONPATH=. uv run --no-sync python research/experiments/live_refine_validation.py \
  --date 2026-06-30 --event sunset --bbox 20 42 100 122 --threshold 0.50
```

- 脚本对同一 bbox/日期跑两次 `build_national_field`：screen-only 与 refine-on（共享一个 `GFSSource` 当 cube_source）。
- 第一次会下载 GFS GRIB（压力 cube ~180MB/周期），几分钟；之后走磁盘缓存 `research/data/cache/gfs/`。
- 想更省：缩小 bbox（例如长三角 `--bbox 28 34 116 122`），候选/周期更少。
- 若报 `GFSUnavailable`：把 `--date` 换成最近一两天（GFS 通常留 ~10 天）。

**要采集的输出**（脚本已打印）：`[screen]/[refine]` 各自的 `wall`、`peak_mem`、`dl_MB`、`>=0.50 frac`；`[refine]` 的 `cells_refined / cubes_fetched / tiles`；`[delta]` 的 `cells_moved / mean|Δ| / max|Δ|` 与 `screen>=0.50 -> refine>=0.50`。把这些贴回来定 PR-B 参数。

## 3. 已确立的成本模型（离线实测 + 代码核实，不必重测）

从磁盘上历史真实 GFS 缓存（`research/data/cache/gfs/pressure/`）直接用 cfgrib 读，得到：

- GFS 压力子集是**全球场 `721×1440`（0.25°）**，变量 `gh,t,r,q,w,u,v`；每层每变量 `4.1MB`。
- 完整压力 cube **下载 ≈ 180MB/周期**（磁盘实测 10/19/190MB 佐证）。
- **GRIB 按消息全球下载**：`fetch_cube` 的 bbox 只在客户端裁剪，**不减少下载**；bbox 只决定内存里 `AtmosphericCube` 的大小与逐格算力局部性。
- `GFSSource._ds_cache` 按 `(run_dt, fxx)` 缓存解码数据集（`gfs.py:346-355`）→ **传同一个 `GFSSource` 实例时，同周期的多个 tile 只下载一次**。

**推论**：总下载 ≈ `180MB × 跨越的 GFS 周期数`（全国日落窗口 ~1–3h ≈ 1–2 周期 ⇒ ~180–360MB，一次性，之后磁盘命中）。与 tile 数**无关**。

## 4. 验证结果如何指导决策

- `dl_MB` / `cubes_fetched`：确认"每周期一次下载"是否成立（`cubes_fetched` 会等于有候选的 hour×tile 组数，但下载因 `_ds_cache` 去重到周期级——核对 refine 那次的 `dl_MB` 是否 ≈ `180MB × 周期数` 而非 `× tiles`）。
- `refine wall - screen wall`：精修净增耗时。若过大，考虑：调大 `tile_deg`（更少 tile = 更少 cube 内存/裁剪，下载不变）、或收紧 `threshold`（少精修格点）、或只精修高价值候选。
- `[delta] cells_moved / mean|Δ|`：精修相对 screen 的真实修正幅度与空间分布——判断收益是否值得默认开启。
- `peak_mem`：确认单块全球 GRIB 解码（~180MB→内存）+ bbox 裁剪的峰值可接受。

## 5. PR-B 范围与设计约束（spec 的"不在 PR-A"部分）

目标：让精修在 `firecloud` 全国产品里**默认生效**，并把三级概率透明化。

必做：
1. **接 live cube 取数**：`national_product` 构造**一个共享 `GFSSource()`** 作为 `cube_source` 传给 `build_national_field(..., physics_config=NationalPhysicsConfig(enabled=True, refine=True), cube_source=<shared>)`。**务必共享同一实例**（见 §3，否则同周期每 tile 重下 180MB）。
   - 可选优化：因下载与 bbox 无关，可"每周期取一块全国 cube、逐 tile 裁剪"，与当前 per-tile `fetch_cube`（共享缓存下）等价但更直观。
2. **三级概率 metadata / 渲染**：区分 `model`(overview) / `screen`(Stage A) / `refined`(Stage B)；PNG 上标注哪些格点被精修（`RefineResult.refined_mask` 已提供）。
3. **真实 GFS 缓存样本基准**：把 §2 的一次成功运行的 cube 存成 fixture，给 `nationalization_spike`（或新回归）加一个 `integration` 标记的真实样本档，兑现 spec 的 #59 验收（重叠抽样点相对 25km 单点真值的 MAE/P90）。
4. **成本护栏**：给全国 refine 设可配置上限（复用/扩展 `max_cube_cells`，或加"最多精修 N 格 / 最多 M 周期"），并 `log` 被截断的量（项目惯例：不静默截断）。

可选/后续：
- 安全带 `0.30..0.50` 候选也精修（spec 提及；先看验证的 FP/FN 再定）。
- **Stage C 卫星 nowcast**：接 `cloud_motion.nowcast_correction`，对近 1–2h 云边界做有限幅度修正，metadata 增 `satellite_corrected_probability`。

约束/不变量（沿用 PR-A）：
- 默认路径零回归的保护测试 `test_refine_no_op_without_cube_source_is_zero_regression` 必须保持绿。
- 候选精修值 == 同一 cube 单独 `score_point_with_cube`（`test_refined_cell_equals_standalone_score_point_with_cube`）。
- 网络测试打 `integration` 标记；提交信息中文、**不加 `Co-Authored-By`**；测试命令 `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest -m "not integration" -q`。
- 注意 `pytest --cov` 在本环境整体不可用（numpy double-load）；覆盖率按测试清单论证。

## 6. 指针

- 引擎：`predictor/national_refine.py`；接线：`predictor/national_field.py`（`build_national_field` 的 refine 分支 + `cube_source`）。
- cube 取数：`predictor/gfs.py`（`GFSSource.fetch_cube` / `_ds_cache` / `DEFAULT_CACHE_DIR = research/data/cache/gfs`）。
- 单点物理内核：`predictor/sunward_section.py::score_point_with_cube`；局部同构参考：`predictor/local_field.py`。
- 验证脚本：`research/experiments/live_refine_validation.py`（本次新增）。
- 合成基准：`research/experiments/nationalization_spike.py`。
- 研究路线：`research/theory/intelligent-nationalization-spike-58.md`。
- 记忆（`~/.claude/projects/.../memory/`）：`firecloud-issue-59-status`、`firecloud-desktop-tcc`、`firecloud-pytest-cov-broken`、`firecloud-agile-workflow`、`firecloud-metric-philosophy`。

## 7. §2 验证结果（2026-07-02,用户本机实测)——已完成

命令与 §2 完全一致(`--date 2026-06-30 --event sunset --bbox 20 42 100 122 --threshold 0.50`)。

```
[screen ] wall=  10.3s  peak_mem=  30.2MB  grid=(89, 89)  >=0.50 frac=0.179  surface_fetches=4  dl_MB=23.5
[refine ] wall=1180.4s  peak_mem=1035.9MB  grid=(89, 89)  >=0.50 frac=0.087  surface_fetches=4  dl_MB=23.5
[refine ] status=run cells_refined=1419 cubes_fetched=31 tiles=23 tile_deg=5.0
[delta  ] cells_moved=1133  mean|Δ|=0.0594  max|Δ|=1.0000  screen>=0.50=1419 -> refine>=0.50=686
```

按 §4 逐条解读:

- **每周期一次下载成立**:31 个 (hour,tile) cube 组、23 个 tile,实际只下载了 3 块 t06z 压力子集(f005/f006/f007,各 ≈210MB,字节数与 idx 精确相符)+1 块回退周期 t00z f011。`_ds_cache` 去重到 (run,fxx) 级,与 tile 数无关,§3 成本模型确认。
- **[refine] 的 `dl_MB=23.5` 只计了地面场**——cube 下载字节未接入 `download_bytes` 记账(PR-B 待补的小口子)。真实压力下载 ≈ 210MB × 周期数。
- **refine 收益显著且方向正确**:screen 的 1419 个 ≥0.50 候选精修后只剩 686(-52%),≥0.50 面积占比 0.179→0.087——与离线合成基准"screen 系统性偏乐观、refine 压 FP"一致。mean|Δ|=0.059、max|Δ|=1.0(有格点完全翻转)。**值得默认开启**。
- **wall 1180s 几乎全是网络**:本次网络极不稳定(多次 200MB range GET 中途断),纯计算部分(cube 已落盘后 1419 格完整单点物理 + 31 次裁剪)估算 ≈ 0.3–0.6s/格。周期子集落盘后重跑走磁盘缓存,预计 ~10min 内。
- **peak_mem ≈ 1.04GB**:3–4 个全球 721×1440 数据集同时驻留 `_ds_cache` 所致,开发机可接受;PR-B 建议按周期用完即释放或全国先裁一块再逐 tile 切。

**过程中发现并修复的真实 bug**(commit `be4cfa0`,已在分支):herbie 子集下载断连会留半截 GRIB,且 download/xarray 只按"文件存在"判缓存 → 半截文件永久毒化缓存,首次验证运行死于只剩 [15..1] hPa 平流层顶的 f007 子集(37MB/210MB)。修复:`_download_dataset` 先落盘、对照 idx inventory 期望字节数校验、不符删除并按 transient 重试;顺带让压力子集从此保留磁盘缓存。三次运行共治愈 7 次真实截断(含 3 个历史遗留毒化文件,其中一个自 6 月起就潜伏在缓存里)。**PR-B 注意**:同样的静默截断风险存在于 surface/cover 子集路径(更小、概率低,但会以 NaN 空洞形式出现),建议 PR-B 顺手加同款校验。

对 §5 PR-B 参数的建议:`tile_deg=5.0` 保持(内存/裁剪合理);`threshold=0.50` 起步(1419 格 ≈ 10min 计算,可接受;若要更快可收紧或加 max-cells 护栏并 log 截断量);下载成本按"≈210MB × 跨越周期数、一次性、之后磁盘命中"宣传。
