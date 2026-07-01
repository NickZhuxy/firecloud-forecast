# 全国 Stage B 候选带精修 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对全国 Stage A screen 打分 `>= threshold` 的候选格点，按 `(valid-hour, tile)` 分组共享一块 GFS 压力 cube，跑 `score_point_with_cube` 等价的 50 km 2-D sunward 光追精修，用精修值覆盖候选格点。

**Architecture:** 新增纯计算引擎 `predictor/national_refine.py`（与 `local_field` 同构，键从「单中心」换成「valid-hour × tile」）；snapshot 由全国已取的地面场逐格合成（免联网）；引擎在 `build_national_field` 里放到 `refine=True` 且传入 `cube_source` 才执行，默认产品零回归；离线基准脚本增一档 `stage_b_refine` 证明收益。

**Tech Stack:** Python 3、numpy、pytest；`uv run --no-sync`；既有 `predictor/` 物理模块（`sunward_section.score_point_with_cube`、`rules.standard_predictor`、`spatial.build_sunward_path`）。

## Global Constraints

- 运行测试统一：`PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest <target> -q`。
- 全离线，不联网；任何真实 GFS 取数留下一 PR 并打 `integration` 标记（本 PR 不引入）。
- 提交信息用中文，**不加** `Co-Authored-By` 尾注（用户全局规则）。
- 默认产品零回归：`national_product` 不传 `cube_source`，`refinement.status == "configured_not_run"`，概率与现状逐位相等。
- 精修距离 `REFINE_SUNWARD_DISTANCES_KM = tuple(float(d) for d in range(0, 801, 50))`（50 km 列距）。
- snapshot 由地面场合成，`source_label="national-refine"`；`aod`/`visibility` 字段可缺失（取 `None`）。
- 候选判定 `screen_probability >= threshold`（默认 `0.50`）；valid-hour 复用 national 已算的 `selected_time`。
- cube 分组键 `(int(selected_time[cell]), floor(lat/tile_deg), floor(lon/tile_deg))`，`tile_deg` 默认 `5.0`；`max_cube_cells` 默认 `6000`（bbox 水平格数 = 度面积 / 0.25²）。

## File Structure

- `predictor/national_refine.py`（新）— 精修引擎：常量 `REFINE_SUNWARD_DISTANCES_KM`、`RefineResult`、内部 helper（`_PlaceholderSource`、`_event_datetime`、`_synthesize_snapshot`、`_candidate_groups`、`_group_bbox`、`_bbox_cell_count`）、公开 `refine_field(...)`。单一职责：把候选格点精修成概率场。
- `predictor/tests/test_national_refine.py`（新）— 引擎离线单元/保真/变形测试，自带合成 cube 夹具。
- `predictor/national_field.py`（改）— `build_national_field` 加 `cube_source=None` 参数与 refine 分支、metadata 计数。
- `predictor/tests/test_national_field.py`（改）— 加「refine 生效」「无 cube_source 零回归」两测。
- `research/experiments/nationalization_spike.py`（改）— 加 `_stage_b_refine_scores(...)` 与 `run()` 里 `stage_b_refine` 一档。
- `predictor/tests/test_nationalization_spike.py`（新）— 离线断言 refine 在合成场上优于 overview。

---

### Task 1: 引擎骨架 + snapshot 合成

**Files:**
- Create: `predictor/national_refine.py`
- Test: `predictor/tests/test_national_refine.py`

**Interfaces:**
- Produces:
  - `REFINE_SUNWARD_DISTANCES_KM: tuple[float, ...]`
  - `class RefineResult`（字段见下）
  - `class _PlaceholderSource`（`fetch` 抛 `NotImplementedError`）
  - `_event_datetime(value) -> datetime`
  - `_synthesize_snapshot(surface_fields: dict, j: int, i: int, event_time: datetime) -> WeatherSnapshot`

- [ ] **Step 1: 写失败测试**

`predictor/tests/test_national_refine.py`：
```python
"""Stage B refinement engine (#59), offline with a synthetic cube."""
from datetime import datetime, timezone

import numpy as np
import pytest

from predictor.national_refine import (
    REFINE_SUNWARD_DISTANCES_KM,
    RefineResult,
    _PlaceholderSource,
    _synthesize_snapshot,
)

_VALID = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)


def test_refine_distances_are_50km_steps_to_800():
    assert REFINE_SUNWARD_DISTANCES_KM[0] == 0.0
    assert REFINE_SUNWARD_DISTANCES_KM[-1] == 800.0
    assert all(
        b - a == 50.0
        for a, b in zip(REFINE_SUNWARD_DISTANCES_KM, REFINE_SUNWARD_DISTANCES_KM[1:])
    )


def test_placeholder_source_never_fetches():
    with pytest.raises(NotImplementedError):
        _PlaceholderSource().fetch(30.0, 120.0, _VALID)


def test_synthesize_snapshot_maps_surface_fields():
    surface = {
        "cloud_low_pct": np.array([[3.0, 4.0]]),
        "cloud_mid_pct": np.array([[55.0, 60.0]]),
        "cloud_high_pct": np.array([[10.0, 0.0]]),
        "humidity_pct": np.array([[48.0, 50.0]]),
        "visibility_m": np.array([[24000.0, np.nan]]),
        "aod": np.array([[0.12, np.nan]]),
    }
    snap = _synthesize_snapshot(surface, 0, 0, _VALID)
    assert snap.cloud_low_pct == 3.0
    assert snap.cloud_mid_pct == 55.0
    assert snap.humidity_pct == 48.0
    assert snap.visibility_m == 24000.0
    assert snap.aerosol_optical_depth == 0.12
    assert snap.source_label == "national-refine"
    # NaN optional fields collapse to None; missing keys tolerated.
    snap2 = _synthesize_snapshot(surface, 0, 1, _VALID)
    assert snap2.visibility_m is None
    assert snap2.aerosol_optical_depth is None
    snap3 = _synthesize_snapshot(
        {k: v for k, v in surface.items() if k not in ("aod", "visibility_m")}, 0, 0, _VALID
    )
    assert snap3.visibility_m is None
    assert snap3.aerosol_optical_depth is None
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: FAIL（`ModuleNotFoundError: predictor.national_refine`）。

- [ ] **Step 3: 写最小实现**

`predictor/national_refine.py`：
```python
"""Stage B: refine national screen candidates with the shared-cube 2-D ray trace (#59).

Stage A (national_physics.build_sunward_screen) is a cheap 1-D surface screen. Stage B
takes the cells it flags (screen probability >= threshold) and runs the *real* detailed
sunward physics on them — the same score_point_with_cube the single-point / local paths
use — sharing ONE GFS pressure cube across every candidate in a (valid-hour, tile) group.

Candidates at one valid hour form a meridional terminator stripe and the screen keeps few
cells, so cube count (one per non-empty hour×tile group) and per-cell ray traces stay
affordable. Snapshots are synthesized from the surface fields the national path already
fetched — no per-cell network round-trip.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from predictor.fetch import WeatherSnapshot

REFINE_SUNWARD_DISTANCES_KM: tuple[float, ...] = tuple(float(d) for d in range(0, 801, 50))


@dataclass
class RefineResult:
    refined_probability: np.ndarray   # (ny,nx): candidates=refined, else=screen
    refined_mask: np.ndarray          # (ny,nx) bool: cells that actually ran physics
    cells_refined: int
    cubes_fetched: int
    tiles: int
    tile_deg: float
    distances_km: tuple[float, ...]
    threshold: float


class _PlaceholderSource:
    """Satisfies standard_predictor's WeatherSource dependency without any IO.

    refine_field only calls predictor.score_snapshot (pure compute) with a snapshot it
    synthesized itself, so source.fetch is never reached.
    """

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        raise NotImplementedError("refine_field synthesizes snapshots; source.fetch is unused")


def _event_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(
        int(np.datetime64(value, "s").astype("datetime64[s]").astype("int64")),
        tz=timezone.utc,
    )


def _optional(surface_fields: dict, key: str, j: int, i: int) -> float | None:
    field = surface_fields.get(key)
    if field is None:
        return None
    value = float(np.asarray(field)[j, i])
    return value if np.isfinite(value) else None


def _synthesize_snapshot(surface_fields: dict, j: int, i: int, event_time: datetime) -> WeatherSnapshot:
    return WeatherSnapshot(
        cloud_low_pct=float(np.asarray(surface_fields["cloud_low_pct"])[j, i]),
        cloud_mid_pct=float(np.asarray(surface_fields["cloud_mid_pct"])[j, i]),
        cloud_high_pct=float(np.asarray(surface_fields["cloud_high_pct"])[j, i]),
        humidity_pct=float(np.asarray(surface_fields["humidity_pct"])[j, i]),
        source_label="national-refine",
        retrieved_at=event_time,
        sunset_time=event_time,
        visibility_m=_optional(surface_fields, "visibility_m", j, i),
        aerosol_optical_depth=_optional(surface_fields, "aod", j, i),
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add predictor/national_refine.py predictor/tests/test_national_refine.py
git commit -m "feat(predictor): #59 Stage B 引擎骨架 + snapshot 合成"
```

---

### Task 2: 候选分组 + cube bbox + guard

**Files:**
- Modify: `predictor/national_refine.py`
- Test: `predictor/tests/test_national_refine.py`

**Interfaces:**
- Consumes: Task 1 的 `_event_datetime`。
- Produces:
  - `_candidate_groups(candidate_mask, selected_time, lats, lons, tile_deg) -> dict[tuple[int,int,int], list[tuple[int,int]]]`（键 `(hour_idx, tile_j, tile_i)`，值候选 `(j,i)` 列表）
  - `_group_bbox(cells, lats, lons, event_times, azimuth_deg, distances_km, margin_deg) -> tuple[float,float,float,float]`
  - `_bbox_cell_count(bbox, res_deg=GFS_GRID_RES_DEG) -> int`

- [ ] **Step 1: 写失败测试**（追加到 `test_national_refine.py`）

```python
from predictor.national_refine import (
    _bbox_cell_count,
    _candidate_groups,
    _group_bbox,
)
from predictor.spatial import build_sunward_path


def test_candidate_groups_key_by_hour_and_tile():
    mask = np.array([[True, False], [True, True]])
    selected = np.array([[0, 0], [1, 0]])
    lats = np.array([24.0, 31.0])     # tiles 4, 6 at tile_deg=5
    lons = np.array([100.0, 118.0])   # tiles 20, 23
    groups = _candidate_groups(mask, selected, lats, lons, tile_deg=5.0)
    # (0,0) hour0 tile(4,20); (1,0) hour1 tile(6,20); (1,1) hour0 tile(6,23)
    assert groups[(0, 4, 20)] == [(0, 0)]
    assert groups[(1, 6, 20)] == [(1, 0)]
    assert groups[(0, 6, 23)] == [(1, 1)]
    assert (0, 4, 23) not in groups  # masked-out cell excluded


def test_group_bbox_covers_every_member_sunward_path():
    lats = np.array([30.0, 31.0])
    lons = np.array([118.0, 120.0])
    event_times = np.full((2, 2), np.datetime64(int(_VALID.timestamp()), "s"))
    cells = [(0, 0), (1, 1)]
    dist = (0.0, 100.0, 200.0)
    bbox = _group_bbox(cells, lats, lons, event_times, 270.0, dist, margin_deg=0.5)
    lat_min, lat_max, lon_min, lon_max = bbox
    for j, i in cells:
        for s in build_sunward_path(
            float(lats[j]), float(lons[i]), _VALID, azimuth_deg=270.0, distances_km=dist
        ).samples:
            assert lat_min <= s.lat <= lat_max
            assert lon_min <= s.lon <= lon_max


def test_bbox_cell_count_uses_quarter_degree():
    # 10° x 5° at 0.25° => 41 x 21 = 861 cells.
    assert _bbox_cell_count((20.0, 25.0, 100.0, 110.0)) == 41 * 21
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: FAIL（`ImportError: cannot import name '_candidate_groups'`）。

- [ ] **Step 3: 写最小实现**（追加到 `predictor/national_refine.py`；补 import）

顶部 import 增加：
```python
from predictor.spatial import GFS_GRID_RES_DEG, build_sunward_path
```

追加函数：
```python
def _candidate_groups(candidate_mask, selected_time, lats, lons, tile_deg):
    groups: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    ny, nx = candidate_mask.shape
    for j in range(ny):
        for i in range(nx):
            if not candidate_mask[j, i]:
                continue
            key = (
                int(selected_time[j, i]),
                math.floor(float(lats[j]) / tile_deg),
                math.floor(float(lons[i]) / tile_deg),
            )
            groups.setdefault(key, []).append((j, i))
    return groups


def _group_bbox(cells, lats, lons, event_times, azimuth_deg, distances_km, margin_deg):
    lat_min = lon_min = math.inf
    lat_max = lon_max = -math.inf
    for j, i in cells:
        path = build_sunward_path(
            float(lats[j]),
            float(lons[i]),
            _event_datetime(event_times[j, i]),
            azimuth_deg=azimuth_deg,
            distances_km=distances_km,
        )
        for s in path.samples:
            lat_min = min(lat_min, s.lat)
            lat_max = max(lat_max, s.lat)
            lon_min = min(lon_min, s.lon)
            lon_max = max(lon_max, s.lon)
    return (lat_min - margin_deg, lat_max + margin_deg, lon_min - margin_deg, lon_max + margin_deg)


def _bbox_cell_count(bbox, res_deg: float = GFS_GRID_RES_DEG) -> int:
    lat_min, lat_max, lon_min, lon_max = bbox
    ny = int(math.ceil((lat_max - lat_min) / res_deg)) + 1
    nx = int(math.ceil((lon_max - lon_min) / res_deg)) + 1
    return ny * nx
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: 提交**

```bash
git add predictor/national_refine.py predictor/tests/test_national_refine.py
git commit -m "feat(predictor): #59 候选按 hour×tile 分组 + cube bbox + guard"
```

---

### Task 3: `refine_field` 引擎 + 保真/变形测试

**Files:**
- Modify: `predictor/national_refine.py`
- Test: `predictor/tests/test_national_refine.py`

**Interfaces:**
- Consumes: Task 1/2 全部 helper；`sunward_section.score_point_with_cube`、`rules.standard_predictor`、`clouds.DEFAULT_CLOUD_CONFIG`。
- Produces:
  - `refine_field(cube_source, lats, lons, screen_probability, event_times, selected_time, valid_times, surface_fields, *, threshold=0.50, tile_deg=5.0, distances_km=REFINE_SUNWARD_DISTANCES_KM, margin_deg=0.5, azimuth_deg=None, config=DEFAULT_CLOUD_CONFIG, aod_fn=None, max_cube_cells=6000) -> RefineResult`

- [ ] **Step 1: 写失败测试**（追加到 `test_national_refine.py`；含合成 cube 夹具）

```python
from predictor.national_refine import refine_field
from predictor.profiles import AtmosphericCube
from predictor.rules import standard_predictor
from predictor.sunward_section import score_point_with_cube

_LEVELS = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
_GPH = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
_TEMP = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
_Q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])
_MID = np.array([0.0, 0.0, 5e-4, 5e-4, 0.0, 0.0])


def _cube(low_cloud=np.zeros(6)) -> AtmosphericCube:
    lats = np.arange(26.0, 34.01, 0.5)
    lons = np.arange(112.0, 122.01, 0.5)
    nz, ny, nx = _LEVELS.size, lats.size, lons.size

    def grid(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=_LEVELS,
        temperature_k=grid(_TEMP), relative_humidity_pct=grid(np.full(nz, 30.0)),
        specific_humidity_kg_kg=grid(_Q), geopotential_height_m=grid(_GPH),
        u_wind_m_s=grid(np.zeros(nz)), v_wind_m_s=grid(np.zeros(nz)),
        vertical_velocity_pa_s=grid(np.zeros(nz)),
        cloud_water_kg_kg=grid(_MID + low_cloud), cloud_ice_kg_kg=grid(np.zeros(nz)),
        run_time=_VALID, valid_time=_VALID, source_label="gfs@test", retrieved_at=_VALID,
        missing=[],
    )


class _FakeCubeSource:
    def __init__(self, cube):
        self._cube = cube
        self.calls = 0

    def fetch_cube(self, bbox, time):
        self.calls += 1
        return self._cube


def _surface(shape, low=0.0):
    return {
        "cloud_low_pct": np.full(shape, low),
        "cloud_mid_pct": np.full(shape, 55.0),
        "cloud_high_pct": np.full(shape, 0.0),
        "humidity_pct": np.full(shape, 50.0),
        "visibility_m": np.full(shape, 25000.0),
    }


def _grids():
    lats = np.array([28.0, 30.0])
    lons = np.array([118.0, 120.0])
    event_times = np.full((2, 2), np.datetime64(int(_VALID.timestamp()), "s"))
    selected_time = np.zeros((2, 2), dtype=int)
    return lats, lons, event_times, selected_time


def test_refine_only_candidates_change_others_keep_screen():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.8]])
    src = _FakeCubeSource(_cube())
    res = refine_field(
        src, lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=(0.0, 100.0, 200.0),
    )
    assert isinstance(res, RefineResult)
    assert res.refined_probability[0, 1] == 0.1   # non-candidate unchanged
    assert res.refined_probability[1, 0] == 0.1
    assert res.refined_mask.tolist() == [[True, False], [False, True]]
    assert res.cells_refined == 2


def test_refine_one_cube_per_group():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.9], [0.9, 0.9]])   # 4 candidates, same tile+hour
    src = _FakeCubeSource(_cube())
    res = refine_field(
        src, lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, tile_deg=50.0, distances_km=(0.0, 100.0, 200.0),
    )
    assert src.calls == 1           # ONE shared cube
    assert res.cubes_fetched == 1
    assert res.tiles == 1
    assert res.cells_refined == 4


def test_refined_cell_equals_standalone_score_point_with_cube():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    cube = _cube()
    surface = _surface((2, 2))
    dist = (0.0, 100.0, 200.0)
    res = refine_field(
        _FakeCubeSource(cube), lats, lons, screen, ev, sel, (_VALID,), surface,
        threshold=0.5, distances_km=dist,
    )
    predictor = standard_predictor(_PlaceholderSource())
    snap = _synthesize_snapshot(surface, 0, 0, _VALID)
    expected = score_point_with_cube(
        predictor, cube, snap, 28.0, 118.0, _VALID, distances_km=dist
    ).probability
    assert res.refined_probability[0, 0] == expected


def test_refine_guard_rejects_oversize_cube():
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    with pytest.raises(ValueError, match="max_cube_cells"):
        refine_field(
            _FakeCubeSource(_cube()), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
            threshold=0.5, distances_km=(0.0, 100.0, 200.0), max_cube_cells=5,
        )


def test_refine_westward_low_cloud_lowers_probability():
    # Metamorphic: obstruction must enter through the CUBE (diagnosed/sunward obstruction
    # outranks the snapshot's low cloud in LowCloudObstruction), so perturb cube low cloud.
    lats, lons, ev, sel = _grids()
    screen = np.array([[0.9, 0.1], [0.1, 0.1]])
    dist = (0.0, 100.0, 200.0)
    clear = refine_field(
        _FakeCubeSource(_cube()), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=dist,
    ).refined_probability[0, 0]
    low = np.array([8e-4, 8e-4, 0.0, 0.0, 0.0, 0.0])   # add 925/850 hPa cloud water
    obstructed = refine_field(
        _FakeCubeSource(_cube(low_cloud=low)), lats, lons, screen, ev, sel, (_VALID,), _surface((2, 2)),
        threshold=0.5, distances_km=dist,
    ).refined_probability[0, 0]
    assert obstructed < clear
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: FAIL（`ImportError: cannot import name 'refine_field'`）。

- [ ] **Step 3: 写最小实现**（追加到 `predictor/national_refine.py`；补 import）

顶部 import 增加：
```python
from predictor.clouds import CloudDiagnosisConfig, DEFAULT_CLOUD_CONFIG
from predictor.rules import standard_predictor
from predictor.sunward_section import score_point_with_cube
```

追加函数：
```python
def refine_field(
    cube_source,
    lats,
    lons,
    screen_probability,
    event_times,
    selected_time,
    valid_times,
    surface_fields,
    *,
    threshold: float = 0.50,
    tile_deg: float = 5.0,
    distances_km=REFINE_SUNWARD_DISTANCES_KM,
    margin_deg: float = 0.5,
    azimuth_deg: float | None = None,
    config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
    aod_fn=None,
    max_cube_cells: int = 6000,
) -> RefineResult:
    """Refine screen candidates (screen >= threshold) with the shared-cube 2-D ray trace.

    Candidates are grouped by (valid-hour index, tile); each group fetches ONE cube
    covering its members' sunward paths and scores every member against it via
    score_point_with_cube. Non-candidate cells keep their screen probability.
    """
    screen = np.asarray(screen_probability, dtype=float)
    refined = screen.copy()
    refined_mask = np.zeros(screen.shape, dtype=bool)
    candidate_mask = np.isfinite(screen) & (screen >= threshold)

    predictor = standard_predictor(_PlaceholderSource())
    groups = _candidate_groups(candidate_mask, selected_time, lats, lons, tile_deg)

    cubes_fetched = 0
    cells_refined = 0
    for (hour_idx, _tj, _ti), cells in groups.items():
        bbox = _group_bbox(cells, lats, lons, event_times, azimuth_deg, distances_km, margin_deg)
        if _bbox_cell_count(bbox) > max_cube_cells:
            raise ValueError(
                f"refine cube bbox {bbox} exceeds max_cube_cells={max_cube_cells}; "
                f"reduce tile_deg or tighten the candidate threshold"
            )
        cube = cube_source.fetch_cube(bbox, valid_times[hour_idx])
        cubes_fetched += 1
        for j, i in cells:
            event_time = _event_datetime(event_times[j, i])
            snapshot = _synthesize_snapshot(surface_fields, j, i, event_time)
            forecast = score_point_with_cube(
                predictor,
                cube,
                snapshot,
                float(lats[j]),
                float(lons[i]),
                event_time,
                distances_km=distances_km,
                azimuth_deg=azimuth_deg,
                config=config,
                aod_fn=aod_fn,
            )
            refined[j, i] = forecast.probability
            refined_mask[j, i] = True
            cells_refined += 1

    spatial_tiles = {(tj, ti) for (_h, tj, ti) in groups}
    return RefineResult(
        refined_probability=refined,
        refined_mask=refined_mask,
        cells_refined=cells_refined,
        cubes_fetched=cubes_fetched,
        tiles=len(spatial_tiles),
        tile_deg=tile_deg,
        distances_km=tuple(float(d) for d in distances_km),
        threshold=threshold,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_refine.py -q`
Expected: PASS（11 passed）。

- [ ] **Step 5: 提交**

```bash
git add predictor/national_refine.py predictor/tests/test_national_refine.py
git commit -m "feat(predictor): #59 refine_field 精修引擎 + 保真/变形不变量"
```

---

### Task 4: 接线到 `build_national_field`（开关后，零回归）

**Files:**
- Modify: `predictor/national_field.py`
- Test: `predictor/tests/test_national_field.py`

**Interfaces:**
- Consumes: `national_refine.refine_field`。
- Produces: `build_national_field(gfs_source, bbox, target_date, *, domain_mask=None, solar_event=SolarEvent.SUNSET, physics_config=None, cube_source=None)`（新增末位 `cube_source`）。metadata `physics["refinement"]` 在实跑后含 `status="run", cells_refined, cubes_fetched, tiles, tile_deg`。

- [ ] **Step 1: 写失败测试**（追加到 `test_national_field.py`）

```python
def _refine_cube():
    from predictor.profiles import AtmosphericCube

    levels = np.array([925.0, 850.0, 700.0, 500.0, 400.0, 300.0])
    gph = np.array([750.0, 1500.0, 3000.0, 5500.0, 7200.0, 9000.0])
    temp = np.array([283.0, 278.0, 270.0, 255.0, 245.0, 233.0])
    q = np.array([3e-3, 2e-3, 1e-3, 3e-4, 1e-4, 5e-5])
    mid = np.array([0.0, 0.0, 5e-4, 5e-4, 0.0, 0.0])
    lats = np.arange(18.0, 42.01, 1.0)
    lons = np.arange(96.0, 122.01, 1.0)
    nz, ny, nx = levels.size, lats.size, lons.size

    def g(col):
        return np.broadcast_to(np.asarray(col, float)[:, None, None], (nz, ny, nx)).copy()

    return AtmosphericCube(
        lats=lats, lons=lons, levels_hpa=levels,
        temperature_k=g(temp), relative_humidity_pct=g(np.full(nz, 30.0)),
        specific_humidity_kg_kg=g(q), geopotential_height_m=g(gph),
        u_wind_m_s=g(np.zeros(nz)), v_wind_m_s=g(np.zeros(nz)),
        vertical_velocity_pa_s=g(np.zeros(nz)),
        cloud_water_kg_kg=g(mid), cloud_ice_kg_kg=g(np.zeros(nz)),
        run_time=_T, valid_time=_T, source_label="gfs-cube@test", retrieved_at=_T, missing=[],
    )


class _FakeCubeSource:
    def __init__(self, cube):
        self._cube = cube
        self.calls = 0

    def fetch_cube(self, bbox, time):
        self.calls += 1
        return self._cube


def test_refine_runs_with_cube_source_and_updates_metadata():
    gfs = _FakeGFS(_grid(low=5.0, mid=55.0, high=40.0))
    src = _FakeCubeSource(_refine_cube())
    cfg = NationalPhysicsConfig(enabled=True, refine=True, refine_threshold=0.0)
    field = build_national_field(gfs, _BBOX, _DATE, physics_config=cfg, cube_source=src)

    ref = field.physics["refinement"]
    assert ref["status"] == "run"
    assert ref["enabled"] is True
    assert ref["cells_refined"] >= 1
    assert ref["cubes_fetched"] == src.calls >= 1
    assert "tiles" in ref and "tile_deg" in ref


def test_refine_no_op_without_cube_source_is_zero_regression():
    cfg = NationalPhysicsConfig(enabled=True, refine=True)   # refine requested, no cube_source
    field = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE, physics_config=cfg)
    assert field.physics["refinement"]["status"] == "configured_not_run"

    baseline = build_national_field(_FakeGFS(_grid()), _BBOX, _DATE)   # screen-only default
    np.testing.assert_array_equal(field.probability, baseline.probability)
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_field.py -q`
Expected: FAIL（`build_national_field() got an unexpected keyword argument 'cube_source'`）。

- [ ] **Step 3: 写最小实现**

`predictor/national_field.py` 顶部 import 增加：
```python
from predictor.national_refine import refine_field
```

签名加末位参数（`predictor/national_field.py:108-116`）：
```python
def build_national_field(
    gfs_source,
    bbox,
    target_date: date,
    *,
    domain_mask=None,
    solar_event=SolarEvent.SUNSET,
    physics_config: NationalPhysicsConfig | None = None,
    cube_source=None,
) -> NationalField:
```

在 `probability = score_grid(inputs)`（约 `:227`）之后、`decoded_sizes = ...`（约 `:229`）之前，插入 refine 分支：
```python
        probability = score_grid(inputs)

        if config.enabled and config.refine and cube_source is not None:
            result = refine_field(
                cube_source,
                lats,
                lons,
                probability,
                sunsets,
                selected_time,
                valid_times,
                selected_fields,
                threshold=config.refine_threshold,
                distances_km=config.refine_distances_km,
            )
            probability = result.refined_probability
            physics["refinement"].update(
                status="run",
                cells_refined=result.cells_refined,
                cubes_fetched=result.cubes_fetched,
                tiles=result.tiles,
                tile_deg=result.tile_deg,
            )
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_national_field.py predictor/tests/test_national_product.py -q`
Expected: PASS（既有 national 测试全绿 + 2 新测通过）。

- [ ] **Step 5: 提交**

```bash
git add predictor/national_field.py predictor/tests/test_national_field.py
git commit -m "feat(predictor): #59 refine 接线 build_national_field（开关后零回归）"
```

---

### Task 5: 基准升级 `stage_b_refine` + 回归测试

**Files:**
- Modify: `research/experiments/nationalization_spike.py`
- Create: `predictor/tests/test_nationalization_spike.py`

**Interfaces:**
- Consumes: `national_refine.refine_field`；spike 既有 `_grid`、`_synthetic_cube`、`_diagnosed_1d_scores`、`_metrics`、`_for_each_cell`、`_low/mid/high_cloud_pct`、`_humidity_pct`、`_visibility_m`、`_aod`、`_aod_fn`、`AZIMUTH_DEG`、`VALID_TIME`、`TRUTH_DISTANCES_KM`。
- Produces: `_stage_b_refine_scores(grid, cube, screen, threshold=0.50) -> tuple[np.ndarray, float, float]`；`run()["candidates"]` 多一项 `name="stage_b_refine"`。

- [ ] **Step 1: 写失败测试**

`predictor/tests/test_nationalization_spike.py`：
```python
"""Offline regression: Stage B refine must beat overview on the synthetic field (#59)."""
import importlib.util
import pathlib


def _load_spike():
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "research" / "experiments" / "nationalization_spike.py"
    spec = importlib.util.spec_from_file_location("nationalization_spike", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_b_refine_beats_overview():
    spike = _load_spike()
    result = spike.run()
    by_name = {c["name"]: c for c in result["candidates"]}
    assert "stage_b_refine" in by_name
    overview = by_name["current_overview_grid_score"]
    refine = by_name["stage_b_refine"]
    assert refine["mae"] < overview["mae"]
    assert refine["f1"] >= overview["f1"]
    assert refine["fp"] <= overview["fp"]
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_nationalization_spike.py -q`
Expected: FAIL（`assert 'stage_b_refine' in {...}`，KeyError/AssertionError）。

- [ ] **Step 3: 写最小实现**

`research/experiments/nationalization_spike.py` 顶部 import 增加：
```python
from predictor.national_refine import refine_field
```

在 `_diagnosed_1d_scores` 之后追加：
```python
def _stage_b_refine_scores(
    grid: GridSpec, cube: AtmosphericCube, screen: np.ndarray, threshold: float = 0.50
) -> tuple[np.ndarray, float, float]:
    surface = {
        key: np.empty(grid.shape, dtype=float)
        for key in ("cloud_low_pct", "cloud_mid_pct", "cloud_high_pct", "humidity_pct", "visibility_m", "aod")
    }
    for j, i, lat, lon in _for_each_cell(grid):
        surface["cloud_low_pct"][j, i] = _low_cloud_pct(lat, lon)
        surface["cloud_mid_pct"][j, i] = _mid_cloud_pct(lat, lon)
        surface["cloud_high_pct"][j, i] = _high_cloud_pct(lat, lon)
        surface["humidity_pct"][j, i] = _humidity_pct(lat, lon)
        surface["visibility_m"][j, i] = _visibility_m(lat, lon)
        surface["aod"][j, i] = _aod(lat, lon)

    event_times = np.full(grid.shape, np.datetime64(int(VALID_TIME.timestamp()), "s"))
    selected_time = np.zeros(grid.shape, dtype=int)

    class _FixedCubeSource:
        def __init__(self, cube):
            self.cube = cube

        def fetch_cube(self, bbox, time):
            return self.cube

    distances = tuple(float(d) for d in range(0, 801, 50))
    t0 = time.perf_counter()
    result = refine_field(
        _FixedCubeSource(cube),
        grid.lats,
        grid.lons,
        screen,
        event_times,
        selected_time,
        (VALID_TIME,),
        surface,
        threshold=threshold,
        distances_km=distances,
        azimuth_deg=AZIMUTH_DEG,
        aod_fn=_aod_fn,
        tile_deg=1000.0,
        max_cube_cells=20000,
    )
    seconds = time.perf_counter() - t0
    refine_fraction = result.cells_refined / grid.size
    cost = 0.18 + refine_fraction * (len(distances) / len(TRUTH_DISTANCES_KM))
    return result.refined_probability, seconds, cost
```

在 `run()` 里 `tiered_1d_screen` 循环之后、`return {...}` 之前，插入：
```python
    refine_pred, refine_s, refine_cost = _stage_b_refine_scores(grid, cube, diagnosed)
    candidates.append(_metrics("stage_b_refine", refine_pred, truth, refine_s, refine_cost))
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest predictor/tests/test_nationalization_spike.py -q`
Expected: PASS（1 passed）。

同时人工核对基准输出含新档（可选）：
Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python research/experiments/nationalization_spike.py`
Expected: 输出 JSON 的 `candidates` 含 `"name": "stage_b_refine"`，其 `mae` 远低于 `current_overview_grid_score`。

- [ ] **Step 5: 提交**

```bash
git add research/experiments/nationalization_spike.py predictor/tests/test_nationalization_spike.py
git commit -m "feat(research): #59 基准增 stage_b_refine 档证明精修收益"
```

---

### Task 6: 全量回归 + 覆盖率

**Files:**（无新增，验证收尾）

- [ ] **Step 1: 全量测试**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest -q`
Expected: 全绿（不含 `integration` 标记的网络测试按项目惯例跳过或不选）。

- [ ] **Step 2: 覆盖率不低于地板**

Run: `PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest --cov=predictor --cov-report=term-missing -q`
Expected: `predictor/national_refine.py` 覆盖率高（>90%），项目总覆盖率不低于既有地板。若 `national_refine.py` 有未覆盖分支，补测再跑。

- [ ] **Step 3: 提交（若有补测）**

```bash
git add -A
git commit -m "test(predictor): #59 Stage B 覆盖率补齐"
```

---

## Self-Review

**1. Spec coverage:**
- 引擎 `refine_field` + 分组/bbox/guard → Task 1/2/3 ✓
- snapshot 由地面场合成免联网 → Task 1 `_synthesize_snapshot` ✓
- 每 hour×tile 一块共享 cube → Task 3 `test_refine_one_cube_per_group` ✓
- 保真不变量（候选 == 单独 `score_point_with_cube`）→ Task 3 ✓
- 变形性质（西向低云 → 概率降）→ Task 3（经 cube 扰动，已按 `LowCloudObstruction` 层级修正）✓
- guard 超 `max_cube_cells` 抛错 → Task 3 ✓
- 接线开关后 + 零回归 → Task 4 两测 ✓
- 基准 `stage_b_refine` + #59 数字 → Task 5 ✓
- 覆盖率地板 → Task 6 ✓

**2. Placeholder scan:** 无 TBD/TODO；每个代码步给出完整代码与确切命令/期望。✓

**3. Type consistency:** `refine_field` 签名在 Task 3 定义、Task 4/5 按同名同序调用；`RefineResult` 字段（`refined_probability/refined_mask/cells_refined/cubes_fetched/tiles/tile_deg/distances_km/threshold`）在 Task 1 定义、Task 3 填充、Task 4/5 读取一致；`_synthesize_snapshot(surface_fields, j, i, event_time)` 四参一致；`cube_source.fetch_cube(bbox, time)` Protocol 一致。✓

**风险备注（供执行者留意）:** Task 3 变形测试依赖 `LowCloudObstruction` 的层级（cube 诊断遮挡 > 截面 > snapshot 低云），故扰动加在 cube 低层 `cloud_water_kg_kg`；若合成 cube 的低层含水量阈值不触发诊断云层，改用更大值（如 `2e-3`）确保 `obstructed < clear`。
