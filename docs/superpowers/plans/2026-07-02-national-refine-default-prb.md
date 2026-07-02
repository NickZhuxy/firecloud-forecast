# #59 PR-B：全国精修默认生效 + 三级概率透明化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Stage B 精修在 `firecloud` 全国产品里默认生效（共享一个 `GFSSource`），把 model/screen/refined 三级概率透明化到 metadata 与 PNG，加成本护栏与 cube 下载记账，并用真实 GFS 缓存样本补一档 `integration` 基准。

**Architecture:** 引擎（`national_refine.refine_field`）与开关（`build_national_field(..., physics_config, cube_source)`）在 PR-A 已建好并验证（live：1419 候选 → 686 保留，见 followup 计划 §7）。本 PR 只做五件事：把 `refined_mask` 从 `RefineResult` 透传到 `NationalField`；metadata/渲染消费它；`refine_field` 加 `max_cells` 上限（保高分候选、log 截断量）；`GFSSource` 记压力子集网络字节；`generate_product` 默认把共享 source 同时当 `cube_source` 传入（fake source 无 `fetch_cube` 时自动退化为零回归路径）。

**Tech Stack:** Python 3.11 · numpy · matplotlib(Agg) · pytest(monkeypatch/caplog) · herbie/cfgrib（仅 integration 档触网）

## Global Constraints

- 测试命令（全量离线档）：`PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest -m "not integration" -q`
- integration 档：同上但 `-m integration -k <name>`；必须 `@pytest.mark.integration` 且缓存缺失时 skip 而非 fail
- `pytest --cov` 在本环境不可用（numpy double-load）——覆盖率按测试清单论证
- 保护测试必须始终绿：`test_refine_no_op_without_cube_source_is_zero_regression`、`test_refined_cell_equals_standalone_score_point_with_cube`
- 提交信息中文、**不加 Co-Authored-By**；TDD：每个任务先写失败测试
- 项目惯例：不静默截断——任何上限截断必须 `logger.warning` + metadata 可见
- 分支 `feat/59-refine-default`（自 `feat/59-national-field-upgrade` 切出）；PR base 为 `feat/59-national-field-upgrade`，若 #81 已合并则 rebase 到 main

---

### Task 1: `refined_mask` 透传到 `NationalField`

**Files:**
- Modify: `predictor/national_field.py`（`NationalField` dataclass ~L27-44；refine 分支 ~L231-251；构造 ~L272）
- Test: `predictor/tests/test_national_field.py`（复用既有 `_FakeGFS`/`_grid`/`_refine_cube`/`_FakeCubeSource`/`_BBOX`/`_DATE`）

**Interfaces:**
- Consumes: `RefineResult.refined_mask: np.ndarray (ny,nx) bool`（已存在）
- Produces: `NationalField.refined_mask: np.ndarray | None`（默认 None；仅 refine 实际运行时非 None）

- [ ] **Step 1: 写失败测试**（追加到 test_national_field.py 的 refine 测试区）

```python
def test_refine_exposes_refined_mask():
    gfs = _FakeGFS(_grid(low=5.0, mid=55.0, high=40.0))
    src = _FakeCubeSource(_refine_cube())
    cfg = NationalPhysicsConfig(enabled=True, refine=True, refine_threshold=0.0)
    field = build_national_field(gfs, _BBOX, _DATE, physics_config=cfg, cube_source=src)

    assert field.refined_mask is not None
    assert field.refined_mask.shape == field.probability.shape
    assert int(field.refined_mask.sum()) == field.physics["refinement"]["cells_refined"]


def test_refined_mask_is_none_without_refine():
    field = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE)
    assert field.refined_mask is None
```

- [ ] **Step 2: 跑测试确认失败**：`… -m pytest predictor/tests/test_national_field.py -q -k refined_mask`，预期 `TypeError/AttributeError: refined_mask`
- [ ] **Step 3: 实现**：`NationalField` 末尾加字段 `refined_mask: np.ndarray | None = None`（放在 `physics` 之后）；`build_national_field` 在 `physics = None` 旁初始化 `refined_mask = None`，refine 分支里 `refined_mask = result.refined_mask`，构造 `NationalField(..., refined_mask=refined_mask)`
- [ ] **Step 4: 跑测试确认通过**（同 Step 2 命令 + 全量档）
- [ ] **Step 5: Commit**：`feat(predictor): #59 refined_mask 透传到 NationalField`

---

### Task 2: 三级概率 metadata（model / screen / refined）

**Files:**
- Modify: `predictor/national_product.py`（`_metadata` ~L393-442）
- Test: `predictor/tests/test_national_product.py`（复用 `_field()` 夹具）

**Interfaces:**
- Consumes: `NationalField.refined_mask`、`NationalField.physics`
- Produces: metadata 顶层键 `"probability_levels": {"model": int, "screen": int, "refined": int}`——语义：physics 未启用→全部 model；启用未精修→有限格全为 screen；精修运行→refined=mask 数、screen=有限格−refined

- [ ] **Step 1: 写失败测试**

```python
def test_metadata_probability_levels_three_cases():
    generated = datetime(2026, 6, 22, 12, tzinfo=timezone.utc)
    base = _field()                                    # physics=None
    meta = national_product._metadata(base, date(2026, 6, 22), "x.png", generated)
    finite = int(np.isfinite(base.probability).sum())
    assert meta["probability_levels"] == {"model": finite, "screen": 0, "refined": 0}

    screened = replace(base, physics={"screen": {"enabled": True}})
    meta = national_product._metadata(screened, date(2026, 6, 22), "x.png", generated)
    assert meta["probability_levels"] == {"model": 0, "screen": finite, "refined": 0}

    mask = np.zeros_like(base.probability, dtype=bool)
    mask[0, 0] = True
    refined = replace(screened, refined_mask=mask)
    meta = national_product._metadata(refined, date(2026, 6, 22), "x.png", generated)
    assert meta["probability_levels"] == {"model": 0, "screen": finite - 1, "refined": 1}
```

（文件头需 `from dataclasses import replace`、`import numpy as np`——已有则复用）

- [ ] **Step 2: 确认失败**（KeyError: 'probability_levels'）
- [ ] **Step 3: 实现**：`_metadata` 里在 `"probability_range"` 之后加：

```python
    n_finite = int(finite.size)
    n_refined = (
        int(np.asarray(field.refined_mask, dtype=bool).sum())
        if field.refined_mask is not None else 0
    )
    if field.physics is None:
        levels = {"model": n_finite, "screen": 0, "refined": 0}
    else:
        levels = {"model": 0, "screen": n_finite - n_refined, "refined": n_refined}
    metadata["probability_levels"] = levels
```

（注意 `metadata` dict 字面量构造完成后再赋键，或直接写进字面量均可，保持既有风格）
- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**：`feat(predictor): #59 metadata 三级概率计数（model/screen/refined）`

---

### Task 3: PNG 标注精修格点

**Files:**
- Modify: `predictor/national_product.py`（`plot_sunsetwx_product` ~L307-390）
- Test: `predictor/tests/test_national_product.py`

**Interfaces:**
- Consumes: `NationalField.refined_mask`、既有 `country_path`（裁剪）、底部 caption `fig.text(0.045, 0.07, ...)`
- Produces: 精修格中心的小点散点层（clip 到国界）；caption 追加 `· N cells ray-trace refined`

- [ ] **Step 1: 写失败测试**

```python
def test_plot_marks_refined_cells_and_caption():
    field = _field()
    mask = np.zeros_like(field.probability, dtype=bool)
    mask[1, 1] = mask[2, 3] = True
    field = replace(field, refined_mask=mask, physics={"refinement": {"status": "run"}})
    fig = national_product.plot_sunsetwx_product(
        field, date(2026, 6, 22), _context(), generated_at=_GENERATED
    )
    ax = fig.axes[0]
    sizes = [len(c.get_offsets()) for c in ax.collections]
    assert 2 in sizes                                   # 两个精修格 → 2 个散点
    assert any("ray-trace refined" in t.get_text() for t in fig.texts)


def test_plot_without_mask_adds_no_scatter():
    fig = national_product.plot_sunsetwx_product(
        _field(), date(2026, 6, 22), _context(), generated_at=_GENERATED
    )
    assert all(len(c.get_offsets()) == 0 for c in fig.axes[0].collections if hasattr(c, "get_offsets"))
```

（`_context()`/`_GENERATED` 若无同名夹具，按 `test_plot_is_complete_sunsetwx_scientific_product` 的现行构造方式内联）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**：在 `image.set_clip_path(country_path)` 之后：

```python
    if field.refined_mask is not None and field.refined_mask.any():
        jj, ii = np.nonzero(field.refined_mask)
        refined_dots = ax.scatter(
            np.asarray(field.lons)[ii], np.asarray(field.lats)[jj],
            s=2.5, marker=".", color="#1a1a1a", alpha=0.55,
            linewidths=0, zorder=3,
        )
        refined_dots.set_clip_path(country_path)
```

底部 caption 改为条件拼接：

```python
    refined_note = (
        f" · {int(field.refined_mask.sum()):,} cells ray-trace refined"
        if field.refined_mask is not None and field.refined_mask.any() else ""
    )
    fig.text(0.045, 0.07,
        f"{field.n_points:,} grid cells · gate × modifier algorithm{refined_note} · "
        f"generated {generated.isoformat()}", ...)   # 其余参数不变
```

- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**：`feat(predictor): #59 PNG 标注精修格点 + caption 计数`

---

### Task 4: 成本护栏 `max_cells`（保高分候选，log 截断）

**Files:**
- Modify: `predictor/national_refine.py`（`RefineResult`、`refine_field`；文件头加 `import logging` + `logger = logging.getLogger(__name__)`）
- Modify: `predictor/national_physics.py`（`NationalPhysicsConfig` 加 `max_refine_cells: int | None = 4000`）
- Modify: `predictor/national_field.py`（refine 调用传 `max_cells=config.max_refine_cells`；metadata 加 `cells_skipped`）
- Test: `predictor/tests/test_national_refine.py`、`test_national_field.py`

**Interfaces:**
- Produces: `refine_field(..., max_cells: int | None = None)`；`RefineResult.cells_skipped: int = 0`；metadata `physics.refinement.cells_skipped`
- 语义：候选数 > max_cells 时按 screen 概率降序保留前 max_cells 个（ties 按扁平索引，确定性），其余保持 screen 值；`logger.warning` 报被跳过数

- [ ] **Step 1: 写失败测试**（test_national_refine.py，复用该文件既有 cube/fields 夹具风格）

```python
def test_max_cells_caps_refinement_keeping_top_candidates(caplog):
    # 构造 screen 概率梯度可控的场景：候选 N 个、cap=2，
    # 断言 cells_refined==2、cells_skipped==N-2、被精修的是 screen 最高的两格、
    # 未精修候选保持 screen 值不变，且 caplog 里有 "capped" 警告。
    ...

def test_max_cells_none_refines_everything():
    # max_cells=None（默认）→ 行为与现状完全一致，cells_skipped==0
    ...
```

（实现细节：测试体按该文件既有 `refine_field(...)` 直调用例展开——见 `test_refined_cell_equals_standalone_score_point_with_cube` 的夹具；此处两用例必须写完整可运行代码后再进 Step 2）
- [ ] **Step 2: 确认失败**（TypeError: unexpected keyword 'max_cells'）
- [ ] **Step 3: 实现**：`refine_field` 在 `candidate_mask` 计算后：

```python
    cells_skipped = 0
    if max_cells is not None:
        n_candidates = int(candidate_mask.sum())
        if n_candidates > max_cells:
            flat = np.flatnonzero(candidate_mask)
            order = np.argsort(screen.ravel()[flat], kind="stable")[::-1]
            candidate_mask = candidate_mask.copy()
            candidate_mask.ravel()[flat[order[max_cells:]]] = False
            cells_skipped = n_candidates - max_cells
            logger.warning(
                "national refine capped: refining %d of %d candidates "
                "(max_cells=%d, %d skipped keep their screen probability)",
                max_cells, n_candidates, max_cells, cells_skipped,
            )
```

`RefineResult` 加 `cells_skipped: int = 0` 并在 return 填入；`national_field.py` refine 调用加 `max_cells=config.max_refine_cells`，`physics["refinement"].update(..., cells_skipped=result.cells_skipped)`；`NationalPhysicsConfig` 加字段。
- [ ] **Step 4: 确认通过 + 全量档（含保护测试）**
- [ ] **Step 5: Commit**：`feat(predictor): #59 refine 成本护栏 max_cells——保高分候选并 log 截断量`

---

### Task 5: cube 网络下载记账

**Files:**
- Modify: `predictor/gfs.py`（`_verified_subset_download` 改为 `GFSSource` 方法并记账；4 个调用点改 `self._verified_subset_download(...)`）
- Modify: `predictor/national_field.py`（refine 前后取 `cube_source.network_bytes.get("pressure", 0)` 差值）
- Test: `predictor/tests/test_gfs.py`（复用 `_SubsetHerbie`/`_patched_source`）、`test_national_field.py`

**Interfaces:**
- Produces: `GFSSource.network_bytes: dict[str, int]`（键 = what："pressure"/"surface"/"cover"；只累计**真实发生下载**的字节，磁盘缓存命中不计）；metadata `physics.refinement.cube_download_bytes: int | None`（cube_source 无 `network_bytes` 属性时为 None——fake 源）
- 保持：`_verified_subset_download` 返回值（expected bytes）与截断删除+重试语义完全不变

- [ ] **Step 1: 写失败测试**

```python
def test_network_bytes_counts_downloads_not_cache_hits(monkeypatch, tmp_path):
    path = tmp_path / "subset__gfs.f006"
    fake = _SubsetHerbie(path, payload_sizes=[300])
    src = _patched_source(monkeypatch, tmp_path, fake)
    src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)
    assert src.network_bytes["pressure"] == _SubsetHerbie.EXPECTED_BYTES
    src._ds_cache.clear()                       # 强制重走磁盘（文件已完整）
    src._load_dataset(datetime(2026, 6, 23, 0, tzinfo=timezone.utc), 6)
    assert src.network_bytes["pressure"] == _SubsetHerbie.EXPECTED_BYTES  # 不变
```

test_national_field.py：`test_refinement_metadata_reports_cube_download_bytes`——`_FakeCubeSource` 加 `network_bytes = {"pressure": 0}` 变体断言差值进 metadata；无属性变体断言 `cube_download_bytes is None`。
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**：方法化 + `__init__` 里 `self.network_bytes: dict[str, int] = {}`；下载前判定 `was_complete = local.exists() and local.stat().st_size == expected`（expected 非 None 时），`herbie.download` 后若 `not was_complete and expected is not None`：`self.network_bytes[what] = self.network_bytes.get(what, 0) + expected`。national_field refine 分支包一层前后差值，`hasattr` 判 None。
- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**：`feat(predictor): #59 GFS 网络字节记账,refine metadata 报 cube 下载量`

---

### Task 6: `generate_product` 默认接线 + CLI `--no-refine`

**Files:**
- Modify: `predictor/national_product.py`（`generate_product` ~L537-556）
- Modify: `predictor/cli.py`（argparse + national 调用点）
- Test: `predictor/tests/test_national_product.py`（扩展 `test_generate_product_reuses_national_field_with_converted_bbox_and_mask` 的 monkeypatch 模式）

**Interfaces:**
- Produces: `generate_product(..., refine: bool = True)`；共享同一实例：`cube_source = src if (refine and hasattr(src, "fetch_cube")) else None`（§3 成本模型：共享 `_ds_cache` 才能做到每周期一次下载）；`physics_config=NationalPhysicsConfig(enabled=True, refine=refine)`
- fake source（无 `fetch_cube`）→ `cube_source=None` → 走零回归路径，全部既有单测天然离线
- CLI：`--no-refine` → `refine=False`（帮助文案注明：首跑每时次下载 ~210MB 压力数据，之后走磁盘缓存）

- [ ] **Step 1: 写失败测试**：monkeypatch `national_product.build_national_field` 捕获 kwargs——`GFSSource` 打桩为带 `fetch_cube` 属性的对象时 `cube_source is source` 且 `physics_config.refine is True`；`refine=False` 时 `cube_source is None`；CLI 测试:monkeypatch `generate_product` 捕获 `refine` kwarg,`--no-refine` → False,默认 → True
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**（generate_product 主体）：

```python
    src = source or GFSSource()
    cube_source = src if (refine and hasattr(src, "fetch_cube")) else None
    field = build_national_field(
        src, (south, north, west, east), target_date,
        domain_mask=lambda lats, lons: geometry_mask(context.country, lats, lons),
        solar_event=solar_event,
        physics_config=NationalPhysicsConfig(enabled=True, refine=refine),
        cube_source=cube_source,
    )
```

- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**：`feat(predictor): #59 全国产品默认开启精修(共享 GFSSource),CLI 加 --no-refine`

---

### Task 7: 真实缓存样本 `integration` 基准

**Files:**
- Create: `predictor/tests/test_national_refine_integration.py`

**Interfaces:**
- Consumes: 磁盘缓存 `research/data/cache/gfs/`（§2 验证已留 2026-06-30 的完整压力子集 f005/f006/f007）；`build_national_field` + 共享 `GFSSource`；单点真值 = 同坐标 `score_point_with_cube`（自取点周边 cube，即单点产品路径）
- Produces: `@pytest.mark.integration` 基准：长三角 bbox `(28, 34, 116, 122)`、2026-06-30 sunset、threshold 0.50；抽样 ≤12 个精修格，断言 `cells_refined ≥ 1`、相对单点真值 `MAE ≤ 0.02`、`P90|Δ| ≤ 0.05`；缓存不在时 `pytest.skip`

- [ ] **Step 1: 写测试**（骨架，完整断言与夹具在执行时按上述数字落地；skip 判据 = `Path("research/data/cache/gfs/pressure/gfs/20260630")` 下无 ≥190MB 的 `subset_*` 文件）
- [ ] **Step 2: 跑 integration 档确认通过**：`… -m pytest -m integration -k national_refine -q`（有缓存 → 实跑；无网亦可，全部走磁盘）
- [ ] **Step 3: 跑全量离线档确认 deselect**（不进默认套件）
- [ ] **Step 4: Commit**：`test(predictor): #59 真实 GFS 缓存样本的精修回归基准(integration)`

---

### Task 8: 收尾——live 冒烟 + 文档回写

- [ ] `PYTHONPATH=. uv run --no-sync firecloud --date 2026-06-30 --event sunset --output <scratch>`：确认默认 refine 生效（日志出现 pressure subset 进度行 / cached 行；metadata `refinement.status == "run"`、`probability_levels.refined > 0`；PNG 有精修点标注）
- [ ] `--no-refine` 冒烟：metadata `status == "configured_not_run"`
- [ ] followup 计划 §5 各必做项打勾回写一行结果；更新记忆 `firecloud-issue-59-status`
- [ ] Commit：`docs(plan): #59 PR-B 完成回写`；push；开 PR（base 见 Global Constraints）

## Self-Review

- **Spec 覆盖**：§5.1 接线共享实例=Task 6；§5.2 三级概率 metadata+渲染=Task 2+3；§5.3 真实样本基准=Task 7;§5.4 成本护栏+log=Task 4;§7 提到的 dl 记账口子=Task 5 ✓;可选项(0.30..0.50 安全带、Stage C)明确不做 ✓
- **占位符**:Task 4/7 的测试体标注了"执行时落地完整代码"——保留为有意验收数字与夹具指引的半展开(执行者即本会话,上下文在手);其余任务代码完整 ✓
- **类型一致性**:`refined_mask: np.ndarray | None`、`max_cells: int | None`、`cells_skipped: int`、`network_bytes: dict[str, int]`、`refine: bool = True` 全文一致 ✓
