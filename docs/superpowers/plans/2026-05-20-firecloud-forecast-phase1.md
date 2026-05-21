# Firecloud Forecast Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 deliverable of firecloud-forecast — a Jupyter notebook that calls a rule-based `Predictor` and renders a fire-cloud-probability heatmap on a US map for any given date/time.

**Architecture:** A Python package `predictor/` exposes a `Predictor` protocol with a `RuleBasedPredictor` implementation composed of pluggable `ScoringRule` objects. Weather data comes from NOAA HRRR (CONUS, 3km) via the [Herbie](https://github.com/blaylockbk/Herbie) library, abstracted behind a `WeatherSource` protocol so the source can be swapped (GFS, Open-Meteo, etc.) without touching callers. A Jupyter notebook in `apps/notebook/` consumes the predictor and renders heatmaps via cartopy.

**Tech Stack:** Python 3.11+, uv (env), Herbie + xarray + cfgrib + eccodes (HRRR), astral (solar geometry), matplotlib + cartopy (maps), pytest (tests), Jupyter.

---

## Prerequisites (one-time)

- macOS: `brew install eccodes` (required by cfgrib to read GRIB2; verify with `which codes_info`).
- `uv` installed (`brew install uv` or `pipx install uv`).
- Python 3.11 available to uv (uv will install if needed).

## Final File Structure

```
firecloud-forecast/
├── README.md
├── pyproject.toml
├── .gitignore
├── .python-version
├── predictor/
│   ├── __init__.py
│   ├── score.py        # Forecast dataclass, Predictor protocol
│   ├── features.py     # Features dataclass, derive(), sun calc
│   ├── fetch.py        # WeatherSnapshot, WeatherSource protocol, HRRRSource, FakeSource
│   ├── rules.py        # ScoringRule protocol, 4 rule impls, RuleBasedPredictor
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_score.py
│       ├── test_features.py
│       ├── test_fetch.py
│       ├── test_rules.py
│       └── test_integration.py
├── research/
│   ├── README.md
│   ├── theory/         # 6 markdown skeleton files
│   ├── notebooks/      # exploratory notebooks (created opportunistically)
│   ├── observations/log.md
│   └── data/           # gitignored cache + .gitkeep
└── apps/
    ├── notebook/forecast-map.ipynb
    ├── web/README.md
    └── desktop/README.md
```

---

## Task 1: Project Bootstrap

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version`
- Create: `predictor/__init__.py`, `predictor/tests/__init__.py`
- Create: `research/data/.gitkeep`, `research/notebooks/.gitkeep`
- Create: `apps/notebook/.gitkeep`

- [ ] **Step 1.1: Create `pyproject.toml`**

```toml
[project]
name = "firecloud-forecast"
version = "0.1.0"
description = "Fire cloud (sunset glow) probability prediction"
requires-python = ">=3.11"
dependencies = [
    "herbie-data>=2024.8.0",
    "xarray>=2024.6.0",
    "cfgrib>=0.9.10",
    "numpy>=1.26",
    "pandas>=2.2",
    "matplotlib>=3.8",
    "cartopy>=0.23",
    "astral>=3.2",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "jupyter>=1.0",
    "ipykernel>=6.29",
]

[tool.uv]
package = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["predictor"]

[tool.pytest.ini_options]
testpaths = ["predictor/tests"]
markers = [
    "integration: marks tests requiring network (deselect with -m 'not integration')",
]
```

- [ ] **Step 1.2: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
build/
dist/

# Jupyter
.ipynb_checkpoints/

# OS
.DS_Store

# Project caches (HRRR downloads can be GBs)
research/data/cache/
research/data/raw/

# IDE
.vscode/
.idea/
```

- [ ] **Step 1.3: Create `.python-version`**

```
3.11
```

- [ ] **Step 1.4: Create empty package + test init files**

```bash
mkdir -p predictor/tests
touch predictor/__init__.py predictor/tests/__init__.py
mkdir -p research/{theory,notebooks,observations,data} apps/{notebook,web,desktop}
touch research/data/.gitkeep research/notebooks/.gitkeep apps/notebook/.gitkeep
```

- [ ] **Step 1.5: Resolve and lock the environment**

Run: `cd /Users/nickzhu/Desktop/Projects/firecloud-forecast && uv sync`
Expected: creates `.venv/`, downloads deps, writes `uv.lock`. If `cartopy` fails: ensure system has GEOS (`brew install geos proj`).

- [ ] **Step 1.6: Smoke-test pytest collection**

Run: `uv run pytest --collect-only`
Expected: `no tests ran` (exit 5 is OK at this stage — no tests yet).

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml .gitignore .python-version uv.lock \
        predictor/__init__.py predictor/tests/__init__.py \
        research/data/.gitkeep research/notebooks/.gitkeep apps/notebook/.gitkeep
git commit -m "chore: project bootstrap with uv, pytest config, package skeleton"
```

---

## Task 2: Core Types — `Forecast` and `Predictor` Protocol

**Files:**
- Create: `predictor/score.py`
- Create: `predictor/tests/test_score.py`

- [ ] **Step 2.1: Write failing test in `predictor/tests/test_score.py`**

```python
from datetime import datetime
from predictor.score import Forecast


def test_forecast_construction_and_str():
    f = Forecast(
        probability=0.62,
        components={"mid_high_cloud_presence": 0.8, "low_cloud_obstruction": 0.4},
        explanation="Decent canvas with some low cloud blocking",
        inputs={"cloud_low_pct": 20.0},
    )
    assert 0.0 <= f.probability <= 1.0
    assert "mid_high_cloud_presence" in f.components
    assert "Decent canvas" in f.explanation
    assert f.inputs["cloud_low_pct"] == 20.0


def test_forecast_inputs_defaults_to_empty_dict():
    f = Forecast(probability=0.1, components={}, explanation="")
    assert f.inputs == {}
```

- [ ] **Step 2.2: Run, expect failure**

Run: `uv run pytest predictor/tests/test_score.py -v`
Expected: `ModuleNotFoundError: No module named 'predictor.score'`

- [ ] **Step 2.3: Implement `predictor/score.py`**

```python
"""Public types for the predictor package."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Forecast:
    probability: float
    components: dict[str, float]
    explanation: str
    inputs: dict[str, Any] = field(default_factory=dict)


class Predictor(Protocol):
    def score(self, lat: float, lon: float, time: datetime) -> Forecast: ...
```

- [ ] **Step 2.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_score.py -v`
Expected: 2 passed.

- [ ] **Step 2.5: Commit**

```bash
git add predictor/score.py predictor/tests/test_score.py
git commit -m "feat(predictor): add Forecast dataclass and Predictor protocol"
```

---

## Task 3: `Features` Dataclass + Sun Geometry

**Files:**
- Create: `predictor/features.py`
- Create: `predictor/tests/test_features.py`
- Create: `predictor/tests/conftest.py`

- [ ] **Step 3.1: Write `predictor/tests/conftest.py` with a shared `base_features` fixture**

```python
from datetime import datetime, timezone
import pytest
from predictor.features import Features


@pytest.fixture
def base_features() -> Features:
    """A neutral Features instance individual tests can mutate via dataclasses.replace."""
    return Features(
        cloud_low_pct=10.0,
        cloud_mid_pct=50.0,
        cloud_high_pct=40.0,
        humidity_pct=60.0,
        solar_elevation_deg=2.0,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),  # ~19:30 EDT
        query_time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc),
        location=(42.36, -71.06),  # Boston
    )
```

- [ ] **Step 3.2: Write failing tests in `predictor/tests/test_features.py`**

```python
from datetime import datetime, timezone
from predictor.features import Features, compute_sun_info


def test_features_dataclass_holds_fields():
    f = Features(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60, solar_elevation_deg=2.0,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc),
        location=(42.36, -71.06),
    )
    assert f.cloud_high_pct == 40


def test_compute_sun_info_for_boston_late_may():
    # Boston sunset on 2026-05-20 is approximately 20:08 EDT = 00:08 UTC next day
    dt = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
    info = compute_sun_info(lat=42.36, lon=-71.06, dt=dt)
    assert "sunset" in info and "elevation" in info
    # Sunset should be on the queried local date; just sanity-check it's a datetime.
    assert isinstance(info["sunset"], datetime)
    # Elevation at the query time should be low (sun near horizon)
    assert -10.0 < info["elevation"] < 15.0
```

- [ ] **Step 3.3: Run, expect failure**

Run: `uv run pytest predictor/tests/test_features.py -v`
Expected: `ModuleNotFoundError: No module named 'predictor.features'`

- [ ] **Step 3.4: Implement `predictor/features.py`**

```python
"""Derived features used by scoring rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from astral import LocationInfo, Observer
from astral.sun import sun, elevation


@dataclass
class Features:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    solar_elevation_deg: float
    sunset_time: datetime
    query_time: datetime
    location: tuple[float, float]  # (lat, lon)


def compute_sun_info(lat: float, lon: float, dt: datetime) -> dict:
    """Return sunset time and solar elevation for the given location & instant.

    Both `dt` and the returned `sunset` are timezone-aware (UTC).
    """
    observer = Observer(latitude=lat, longitude=lon)
    s = sun(observer, date=dt.date(), tzinfo=dt.tzinfo)
    elev = elevation(observer, dateandtime=dt)
    return {"sunset": s["sunset"], "elevation": elev}


def derive(snapshot, lat: float, lon: float, time: datetime) -> Features:
    """Build a Features instance from a WeatherSnapshot + location + query time.

    `snapshot` is duck-typed — it must expose: cloud_low_pct, cloud_mid_pct,
    cloud_high_pct, humidity_pct.
    """
    sun_info = compute_sun_info(lat, lon, time)
    return Features(
        cloud_low_pct=snapshot.cloud_low_pct,
        cloud_mid_pct=snapshot.cloud_mid_pct,
        cloud_high_pct=snapshot.cloud_high_pct,
        humidity_pct=snapshot.humidity_pct,
        solar_elevation_deg=sun_info["elevation"],
        sunset_time=sun_info["sunset"],
        query_time=time,
        location=(lat, lon),
    )
```

- [ ] **Step 3.5: Run, expect pass**

Run: `uv run pytest predictor/tests/test_features.py -v`
Expected: 2 passed.

- [ ] **Step 3.6: Commit**

```bash
git add predictor/features.py predictor/tests/test_features.py predictor/tests/conftest.py
git commit -m "feat(predictor): add Features dataclass and sun-geometry helper"
```

---

## Task 4: Weather Types — `WeatherSnapshot`, `WeatherSource`, `FakeSource`

**Files:**
- Create: `predictor/fetch.py` (skeleton with types + FakeSource only — HRRR comes in Task 5)
- Create: `predictor/tests/test_fetch.py`

- [ ] **Step 4.1: Write failing test in `predictor/tests/test_fetch.py`**

```python
from datetime import datetime, timezone
from predictor.fetch import WeatherSnapshot, FakeSource


def test_weather_snapshot_fields():
    s = WeatherSnapshot(
        cloud_low_pct=20.0, cloud_mid_pct=40.0, cloud_high_pct=30.0,
        humidity_pct=55.0, source_label="fake", retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert s.cloud_low_pct == 20.0
    d = s.to_dict()
    assert d["cloud_mid_pct"] == 40.0
    assert d["source_label"] == "fake"


def test_fake_source_returns_canned_snapshot():
    canned = WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    src = FakeSource(canned)
    got = src.fetch(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 0, tzinfo=timezone.utc))
    assert got is canned
```

- [ ] **Step 4.2: Run, expect failure**

Run: `uv run pytest predictor/tests/test_fetch.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4.3: Implement `predictor/fetch.py` (types + FakeSource only)**

```python
"""Weather data acquisition.

Defines a WeatherSource protocol so callers can swap HRRR / GFS / OpenMeteo.
Real implementations live alongside FakeSource (used by tests).
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class WeatherSnapshot:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    source_label: str          # e.g. "hrrr@2026-05-20T18:00Z+f06"
    retrieved_at: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


class WeatherSource(Protocol):
    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot: ...


@dataclass
class FakeSource:
    """Test fixture — returns a pre-built WeatherSnapshot for any query."""
    snapshot: WeatherSnapshot

    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot:
        return self.snapshot
```

- [ ] **Step 4.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_fetch.py -v`
Expected: 2 passed.

- [ ] **Step 4.5: Commit**

```bash
git add predictor/fetch.py predictor/tests/test_fetch.py
git commit -m "feat(predictor): add WeatherSnapshot, WeatherSource protocol, FakeSource"
```

---

## Task 5: `HRRRSource` — HRRR via Herbie with Caching

This task downloads real HRRR GRIB2 files from AWS and extracts the variables we need. It splits the IO (Herbie download) from the pure transformation (xarray Dataset → WeatherSnapshot) so the pure half is unit-testable.

**Files:**
- Modify: `predictor/fetch.py` (add `HRRRSource`)
- Modify: `predictor/tests/test_fetch.py` (add unit + integration tests)

- [ ] **Step 5.1: Add a failing unit test for the pure xarray→snapshot transform**

Append to `predictor/tests/test_fetch.py`:

```python
import numpy as np
import xarray as xr
from datetime import datetime, timezone
from predictor.fetch import HRRRSource


def _fake_hrrr_clouds_dataset(lat_target=42.36, lon_target=-71.06):
    """Build a tiny 3x3 xarray Dataset shaped like a HRRR cloud-cover slice.

    cfgrib shortnames: hcc (high), mcc (middle), lcc (low).
    """
    # Build a 3x3 grid centered on target with ~0.05 deg spacing
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    hcc = np.array([[10, 20, 30], [40, 55, 60], [50, 50, 50]], dtype=float)
    mcc = np.array([[20, 30, 40], [50, 65, 70], [60, 60, 60]], dtype=float)
    lcc = np.array([[5, 8, 10], [12, 15, 20], [18, 22, 25]], dtype=float)
    return xr.Dataset(
        data_vars={
            "hcc": (("y", "x"), hcc),
            "mcc": (("y", "x"), mcc),
            "lcc": (("y", "x"), lcc),
        },
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def _fake_hrrr_rh_dataset(lat_target=42.36, lon_target=-71.06):
    lats = np.array([[lat_target + dy for _ in range(3)] for dy in [-0.05, 0.0, 0.05]])
    lons = np.array([[lon_target + dx for dx in [-0.05, 0.0, 0.05]] for _ in range(3)])
    rh = np.array([[50, 55, 60], [55, 62, 65], [60, 65, 70]], dtype=float)
    return xr.Dataset(
        data_vars={"r2": (("y", "x"), rh)},  # cfgrib often names 2m RH 'r2'
        coords={
            "latitude": (("y", "x"), lats),
            "longitude": (("y", "x"), lons),
        },
    )


def test_snapshot_from_datasets_picks_nearest_grid_point():
    clouds = _fake_hrrr_clouds_dataset()
    rh = _fake_hrrr_rh_dataset()
    snap = HRRRSource._snapshot_from_datasets(
        ds_clouds=clouds,
        ds_rh=rh,
        lat=42.36, lon=-71.06,
        run_label="hrrr@2026-05-20T18:00Z+f06",
        retrieved_at=datetime(2026, 5, 20, 18, 30, tzinfo=timezone.utc),
    )
    # Center grid point is the nearest; values should match the [1,1] cells.
    assert snap.cloud_high_pct == 55.0
    assert snap.cloud_mid_pct == 65.0
    assert snap.cloud_low_pct == 15.0
    assert snap.humidity_pct == 62.0
    assert snap.source_label == "hrrr@2026-05-20T18:00Z+f06"
```

- [ ] **Step 5.2: Run, expect failure**

Run: `uv run pytest predictor/tests/test_fetch.py::test_snapshot_from_datasets_picks_nearest_grid_point -v`
Expected: AttributeError or ImportError — `HRRRSource` not yet defined.

- [ ] **Step 5.3: Implement `HRRRSource` in `predictor/fetch.py`**

Append to `predictor/fetch.py`:

```python
from pathlib import Path
import numpy as np
import xarray as xr

# Note: herbie is heavy; import lazily inside fetch() so unit tests don't pay the cost.


class HRRRSource:
    """Fetch HRRR cloud cover + 2m RH for a single (lat, lon, time) query.

    HRRR is operational only for CONUS. Time should be UTC; we pick the most
    recent run cycle <= time and a forecast hour that lands closest to `time`.
    """

    DEFAULT_CACHE_DIR = Path("research/data/cache/hrrr")

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, lat: float, lon: float, time: "datetime") -> WeatherSnapshot:
        from herbie import Herbie
        from datetime import timezone, timedelta

        # Pick a recent HRRR cycle (HRRR runs hourly) and the right forecast hour.
        # Simple choice: use the run cycle 1 hour before `time`, fxx=1.
        if time.tzinfo is None:
            time = time.replace(tzinfo=timezone.utc)
        run_dt = time.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        fxx = 1

        H = Herbie(
            run_dt.strftime("%Y-%m-%d %H:%M"),
            model="hrrr",
            product="sfc",
            fxx=fxx,
            save_dir=self.cache_dir,
        )
        # Returns a list of 3 Datasets (one per cloud layer); merge into one.
        cloud_list = H.xarray(":(?:HCDC|MCDC|LCDC):")
        ds_clouds = xr.merge(cloud_list, compat="override")
        ds_rh = H.xarray(":RH:2 m above ground")

        run_label = f"hrrr@{run_dt.strftime('%Y-%m-%dT%HZ')}+f{fxx:02d}"
        return self._snapshot_from_datasets(
            ds_clouds=ds_clouds,
            ds_rh=ds_rh,
            lat=lat, lon=lon,
            run_label=run_label,
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _snapshot_from_datasets(
        ds_clouds: xr.Dataset,
        ds_rh: xr.Dataset,
        lat: float, lon: float,
        run_label: str,
        retrieved_at: "datetime",
    ) -> WeatherSnapshot:
        """Pure transform: pick the nearest grid point and assemble a snapshot."""
        # HRRR has 2D latitude/longitude arrays on (y, x); use simple Euclidean nearest.
        yi, xi = _nearest_grid_index(ds_clouds.latitude.values, ds_clouds.longitude.values, lat, lon)
        yi_rh, xi_rh = _nearest_grid_index(ds_rh.latitude.values, ds_rh.longitude.values, lat, lon)

        # cfgrib uses lower-case GRIB shortnames:
        #   HCDC -> 'hcc', MCDC -> 'mcc', LCDC -> 'lcc', RH at 2m -> 'r2'.
        hcc = float(ds_clouds["hcc"].isel(y=yi, x=xi).item())
        mcc = float(ds_clouds["mcc"].isel(y=yi, x=xi).item())
        lcc = float(ds_clouds["lcc"].isel(y=yi, x=xi).item())
        rh = float(ds_rh["r2"].isel(y=yi_rh, x=xi_rh).item())

        return WeatherSnapshot(
            cloud_low_pct=lcc,
            cloud_mid_pct=mcc,
            cloud_high_pct=hcc,
            humidity_pct=rh,
            source_label=run_label,
            retrieved_at=retrieved_at,
        )


def _nearest_grid_index(lat_arr: np.ndarray, lon_arr: np.ndarray, lat: float, lon: float) -> tuple[int, int]:
    """Return (yi, xi) of the grid point nearest (lat, lon) using squared Euclidean distance."""
    d2 = (lat_arr - lat) ** 2 + (lon_arr - lon) ** 2
    yi, xi = np.unravel_index(np.argmin(d2), d2.shape)
    return int(yi), int(xi)
```

- [ ] **Step 5.4: Run the unit test, expect pass**

Run: `uv run pytest predictor/tests/test_fetch.py -v -m "not integration"`
Expected: all unit tests pass (3 from earlier + 1 new).

- [ ] **Step 5.5: Add an integration test (marked, off by default)**

Append to `predictor/tests/test_fetch.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta


@pytest.mark.integration
def test_hrrr_source_real_fetch_for_boston(tmp_path):
    """Hits the network (AWS S3). Run manually with: pytest -m integration."""
    src = HRRRSource(cache_dir=tmp_path)
    # Pick a recent past time (HRRR keeps several days online).
    t = datetime.now(timezone.utc) - timedelta(hours=3)
    snap = src.fetch(lat=42.36, lon=-71.06, time=t)
    assert 0 <= snap.cloud_low_pct <= 100
    assert 0 <= snap.cloud_mid_pct <= 100
    assert 0 <= snap.cloud_high_pct <= 100
    assert 0 <= snap.humidity_pct <= 100
    assert snap.source_label.startswith("hrrr@")
```

- [ ] **Step 5.6: Run integration test manually once**

Run: `uv run pytest predictor/tests/test_fetch.py -v -m integration`
Expected: PASS (network call may take 30–90 seconds the first time as Herbie downloads + caches the GRIB2). If it fails, capture the error — common issues are missing `eccodes` (re-check `brew install eccodes`) or HRRR cycle not yet available (try a time 3+ hours in the past).

- [ ] **Step 5.7: Commit**

```bash
git add predictor/fetch.py predictor/tests/test_fetch.py
git commit -m "feat(predictor): HRRRSource via Herbie with nearest-grid lookup + caching"
```

---

## Task 6: Rule — `MidHighCloudPresence`

The first scoring rule. Fire clouds need mid/high cloud cover as a "canvas" for the low-angle light. Too little: no canvas. Too much: uniform overcast blocks the light entirely. Sweet spot is ~30–70%.

**Files:**
- Create: `predictor/rules.py` (skeleton + first rule)
- Create: `predictor/tests/test_rules.py`

- [ ] **Step 6.1: Write failing tests**

```python
# predictor/tests/test_rules.py
from dataclasses import replace
from predictor.rules import MidHighCloudPresence


def test_mid_high_cloud_zero_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=0, cloud_high_pct=0)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_full_cover_scores_zero(base_features):
    f = replace(base_features, cloud_mid_pct=100, cloud_high_pct=100)
    assert MidHighCloudPresence().evaluate(f) == 0.0


def test_mid_high_cloud_sweet_spot_scores_one(base_features):
    # Average mid+high = 50 → in [30, 70] plateau → 1.0
    f = replace(base_features, cloud_mid_pct=50, cloud_high_pct=50)
    assert MidHighCloudPresence().evaluate(f) == 1.0


def test_mid_high_cloud_low_end_ramp(base_features):
    # Avg = 15 → linear from 0 at 0% to 1 at 30%  → 0.5
    f = replace(base_features, cloud_mid_pct=10, cloud_high_pct=20)
    assert abs(MidHighCloudPresence().evaluate(f) - 0.5) < 1e-9
```

- [ ] **Step 6.2: Run, expect failure**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: ImportError on `predictor.rules`.

- [ ] **Step 6.3: Implement `predictor/rules.py` (skeleton + first rule)**

```python
"""Scoring rules and the rule-based predictor."""
from __future__ import annotations
from typing import Protocol
from predictor.features import Features


class ScoringRule(Protocol):
    name: str
    def evaluate(self, features: Features) -> float: ...   # returns 0.0–1.0


def _trapezoid(x: float, low0: float, low1: float, high1: float, high0: float) -> float:
    """Trapezoidal membership function.

    0 outside [low0, high0], 1 inside [low1, high1], linear ramps on each side.
    """
    if x <= low0 or x >= high0:
        return 0.0
    if low1 <= x <= high1:
        return 1.0
    if x < low1:
        return (x - low0) / (low1 - low0)
    return (high0 - x) / (high0 - high1)


class MidHighCloudPresence:
    """Reward 30–70% combined mid+high cloud cover (the 'canvas')."""
    name = "mid_high_cloud_presence"

    def evaluate(self, f: Features) -> float:
        avg = (f.cloud_mid_pct + f.cloud_high_pct) / 2.0
        return _trapezoid(avg, low0=0, low1=30, high1=70, high0=100)
```

- [ ] **Step 6.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: 4 passed.

- [ ] **Step 6.5: Commit**

```bash
git add predictor/rules.py predictor/tests/test_rules.py
git commit -m "feat(predictor): add MidHighCloudPresence scoring rule"
```

---

## Task 7: Rule — `LowCloudObstruction`

Low clouds at the western horizon physically block low-angle sunlight from reaching the mid/high cloud canvas. Penalty grows with low cloud cover; a small amount is acceptable.

**Files:**
- Modify: `predictor/rules.py`
- Modify: `predictor/tests/test_rules.py`

- [ ] **Step 7.1: Append failing tests**

```python
# Append to predictor/tests/test_rules.py
from predictor.rules import LowCloudObstruction


def test_low_cloud_zero_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=0)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_small_scores_one(base_features):
    f = replace(base_features, cloud_low_pct=15)
    assert LowCloudObstruction().evaluate(f) == 1.0


def test_low_cloud_full_scores_zero(base_features):
    f = replace(base_features, cloud_low_pct=100)
    assert LowCloudObstruction().evaluate(f) == 0.0


def test_low_cloud_mid_range_linear(base_features):
    # Linear ramp from 1.0 at 20% to 0.0 at 100% → at 60% should be 0.5
    f = replace(base_features, cloud_low_pct=60)
    assert abs(LowCloudObstruction().evaluate(f) - 0.5) < 1e-9
```

- [ ] **Step 7.2: Run, expect failure**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: ImportError on `LowCloudObstruction`.

- [ ] **Step 7.3: Append `LowCloudObstruction` to `predictor/rules.py`**

```python
class LowCloudObstruction:
    """Penalize low cloud cover that blocks sunlight from reaching the canvas.

    Score 1.0 up to 20%, linear ramp to 0.0 by 100%.
    """
    name = "low_cloud_obstruction"

    def evaluate(self, f: Features) -> float:
        if f.cloud_low_pct <= 20:
            return 1.0
        return max(0.0, 1.0 - (f.cloud_low_pct - 20) / 80.0)
```

- [ ] **Step 7.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: 8 passed.

- [ ] **Step 7.5: Commit**

```bash
git add predictor/rules.py predictor/tests/test_rules.py
git commit -m "feat(predictor): add LowCloudObstruction scoring rule"
```

---

## Task 8: Rule — `SolarAngleAtSunset`

Fire clouds occur near sunset (or sunrise). This rule downweights queries far from the local sunset time, so the predictor doesn't claim noon-time fire clouds.

**Files:**
- Modify: `predictor/rules.py`
- Modify: `predictor/tests/test_rules.py`

- [ ] **Step 8.1: Append failing tests**

```python
# Append to predictor/tests/test_rules.py
from datetime import datetime, timezone, timedelta
from predictor.rules import SolarAngleAtSunset


def test_solar_angle_at_sunset_peaks_within_30min(base_features):
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(minutes=15))
    assert SolarAngleAtSunset().evaluate(f) == 1.0


def test_solar_angle_far_from_sunset_scores_zero(base_features):
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(hours=4))
    assert SolarAngleAtSunset().evaluate(f) == 0.0


def test_solar_angle_ramp_45_min_before(base_features):
    # 45 min before sunset → halfway through the [30, 60] ramp → 0.5
    sunset = datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc)
    f = replace(base_features, sunset_time=sunset, query_time=sunset - timedelta(minutes=45))
    assert abs(SolarAngleAtSunset().evaluate(f) - 0.5) < 1e-9
```

- [ ] **Step 8.2: Run, expect failure**

- [ ] **Step 8.3: Append `SolarAngleAtSunset` to `predictor/rules.py`**

```python
class SolarAngleAtSunset:
    """Score how close the query time is to the local sunset.

    1.0 within ±30 min of sunset; linear ramp to 0 by ±60 min; 0 beyond.
    """
    name = "solar_angle"

    def evaluate(self, f: Features) -> float:
        diff_min = abs((f.query_time - f.sunset_time).total_seconds()) / 60.0
        if diff_min <= 30:
            return 1.0
        if diff_min >= 60:
            return 0.0
        return (60 - diff_min) / 30.0
```

- [ ] **Step 8.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: 11 passed.

- [ ] **Step 8.5: Commit**

```bash
git add predictor/rules.py predictor/tests/test_rules.py
git commit -m "feat(predictor): add SolarAngleAtSunset scoring rule"
```

---

## Task 9: Rule — `HumidityFactor`

A moderate amount of moisture supports cloud formation and aerosol-scattering color; too dry means no clouds, too wet usually means precipitating overcast.

**Files:**
- Modify: `predictor/rules.py`
- Modify: `predictor/tests/test_rules.py`

- [ ] **Step 9.1: Append failing tests**

```python
# Append to predictor/tests/test_rules.py
from predictor.rules import HumidityFactor


def test_humidity_sweet_spot(base_features):
    f = replace(base_features, humidity_pct=60)
    assert HumidityFactor().evaluate(f) == 1.0


def test_humidity_too_dry(base_features):
    f = replace(base_features, humidity_pct=10)
    assert HumidityFactor().evaluate(f) == 0.0


def test_humidity_too_wet(base_features):
    f = replace(base_features, humidity_pct=100)
    assert HumidityFactor().evaluate(f) == 0.0
```

- [ ] **Step 9.2: Run, expect failure**

- [ ] **Step 9.3: Append `HumidityFactor` to `predictor/rules.py`**

```python
class HumidityFactor:
    """Reward middling humidity (40–80%); penalize extremes."""
    name = "humidity"

    def evaluate(self, f: Features) -> float:
        return _trapezoid(f.humidity_pct, low0=20, low1=40, high1=80, high0=95)
```

- [ ] **Step 9.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: 14 passed.

- [ ] **Step 9.5: Commit**

```bash
git add predictor/rules.py predictor/tests/test_rules.py
git commit -m "feat(predictor): add HumidityFactor scoring rule"
```

---

## Task 10: `RuleBasedPredictor`

Composes a list of `ScoringRule` objects with a weight map and combiner. Implements `Predictor.score()`.

**Files:**
- Modify: `predictor/rules.py`
- Modify: `predictor/tests/test_rules.py`

- [ ] **Step 10.1: Append failing tests**

```python
# Append to predictor/tests/test_rules.py
from datetime import datetime, timezone
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.rules import (
    RuleBasedPredictor,
    MidHighCloudPresence,
    LowCloudObstruction,
    SolarAngleAtSunset,
    HumidityFactor,
)


def _make_fake_source():
    snap = WeatherSnapshot(
        cloud_low_pct=10.0, cloud_mid_pct=50.0, cloud_high_pct=40.0,
        humidity_pct=60.0, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    return FakeSource(snap)


def test_predictor_returns_forecast_with_named_components():
    p = RuleBasedPredictor(
        rules=[MidHighCloudPresence(), LowCloudObstruction(), HumidityFactor()],
        weights={"mid_high_cloud_presence": 1.0, "low_cloud_obstruction": 1.0, "humidity": 1.0},
        source=_make_fake_source(),
    )
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    assert set(f.components.keys()) == {"mid_high_cloud_presence", "low_cloud_obstruction", "humidity"}
    assert 0.0 <= f.probability <= 1.0
    assert f.explanation  # non-empty


def test_predictor_default_combiner_is_weighted_average():
    rule = MidHighCloudPresence()
    p = RuleBasedPredictor(rules=[rule], weights={rule.name: 2.0}, source=_make_fake_source())
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    # Single rule → probability equals that rule's score regardless of weight magnitude.
    assert f.probability == f.components["mid_high_cloud_presence"]


def test_predictor_unset_weight_defaults_to_one():
    """A rule with no entry in `weights` should still contribute with weight 1.0."""
    p = RuleBasedPredictor(
        rules=[MidHighCloudPresence(), HumidityFactor()],
        weights={"mid_high_cloud_presence": 3.0},  # humidity weight omitted
        source=_make_fake_source(),
    )
    f = p.score(lat=42.36, lon=-71.06, time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc))
    # Both rules score 1.0 for this fake snapshot → weighted avg = 1.0.
    assert f.probability == 1.0
```

- [ ] **Step 10.2: Run, expect failure**

- [ ] **Step 10.3: Append `RuleBasedPredictor` and combiner to `predictor/rules.py`**

```python
from typing import Callable
from predictor.fetch import WeatherSource
from predictor.features import derive
from predictor.score import Forecast


def weighted_average(components: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted average with default weight 1.0 for missing keys."""
    total_w = 0.0
    acc = 0.0
    for name, value in components.items():
        w = weights.get(name, 1.0)
        acc += w * value
        total_w += w
    return acc / total_w if total_w > 0 else 0.0


class RuleBasedPredictor:
    def __init__(
        self,
        rules: list[ScoringRule],
        weights: dict[str, float] | None = None,
        source: WeatherSource | None = None,
        combiner: Callable[[dict[str, float], dict[str, float]], float] = weighted_average,
    ):
        if source is None:
            raise ValueError("RuleBasedPredictor requires a WeatherSource")
        self.rules = rules
        self.weights = weights or {}
        self.source = source
        self.combiner = combiner

    def score(self, lat: float, lon: float, time) -> Forecast:
        snapshot = self.source.fetch(lat, lon, time)
        feats = derive(snapshot, lat, lon, time)
        components = {r.name: r.evaluate(feats) for r in self.rules}
        prob = self.combiner(components, self.weights)
        return Forecast(
            probability=prob,
            components=components,
            explanation=self._explain(components, prob),
            inputs=snapshot.to_dict(),
        )

    def _explain(self, components: dict[str, float], prob: float) -> str:
        pieces = [f"{k}={v:.2f}" for k, v in components.items()]
        return f"Composite={prob:.2f} from " + ", ".join(pieces)
```

- [ ] **Step 10.4: Run, expect pass**

Run: `uv run pytest predictor/tests/test_rules.py -v`
Expected: 17 passed.

- [ ] **Step 10.5: Commit**

```bash
git add predictor/rules.py predictor/tests/test_rules.py
git commit -m "feat(predictor): add RuleBasedPredictor composing scoring rules"
```

---

## Task 11: End-to-End Smoke Test

One pytest that wires the whole pipeline together with a `FakeSource` to make sure the public surface works as advertised, independent of any one module's internals.

**Files:**
- Create: `predictor/tests/test_integration.py`

- [ ] **Step 11.1: Write the test**

```python
"""End-to-end smoke test using FakeSource (no network)."""
from datetime import datetime, timezone, timedelta
from predictor.fetch import FakeSource, WeatherSnapshot
from predictor.rules import (
    RuleBasedPredictor,
    MidHighCloudPresence, LowCloudObstruction,
    SolarAngleAtSunset, HumidityFactor,
)


def _default_predictor(snapshot: WeatherSnapshot) -> RuleBasedPredictor:
    return RuleBasedPredictor(
        rules=[
            MidHighCloudPresence(),
            LowCloudObstruction(),
            SolarAngleAtSunset(),
            HumidityFactor(),
        ],
        weights={
            "mid_high_cloud_presence": 2.0,
            "low_cloud_obstruction": 2.0,
            "solar_angle": 1.5,
            "humidity": 1.0,
        },
        source=FakeSource(snapshot),
    )


def test_high_probability_scenario():
    """A 'beautiful sunset' configuration near sunset should score high."""
    snap = WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=50,
        humidity_pct=60, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    p = _default_predictor(snap)
    # Boston, just before local sunset on a late-May day:
    t = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)  # ~20:00 EDT
    f = p.score(lat=42.36, lon=-71.06, time=t)
    assert f.probability > 0.7, f"Expected high, got {f.probability}: {f.explanation}"


def test_low_probability_scenario_overcast_at_noon():
    """Heavy low cloud + far from sunset → low score."""
    snap = WeatherSnapshot(
        cloud_low_pct=95, cloud_mid_pct=10, cloud_high_pct=5,
        humidity_pct=95, source_label="fake",
        retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    p = _default_predictor(snap)
    t = datetime(2026, 5, 20, 16, 0, tzinfo=timezone.utc)  # noon EDT
    f = p.score(lat=42.36, lon=-71.06, time=t)
    assert f.probability < 0.2, f"Expected low, got {f.probability}: {f.explanation}"
```

- [ ] **Step 11.2: Run all tests**

Run: `uv run pytest -v -m "not integration"`
Expected: all green (~19 tests).

- [ ] **Step 11.3: Commit**

```bash
git add predictor/tests/test_integration.py
git commit -m "test(predictor): end-to-end smoke test for high/low scenarios"
```

---

## Task 12: Research Notes Scaffolding

Skeleton markdown files with section headings only — the user fills in content as they research. Every file ends with a `## 对预测规则的启示` section that anchors back to `predictor/rules.py`.

**Files:**
- Create: `research/README.md`
- Create: `research/theory/00-index.md`
- Create: `research/theory/cloud-physics.md`
- Create: `research/theory/atmospheric-optics.md`
- Create: `research/theory/solar-geometry.md`
- Create: `research/theory/aerosols-and-color.md`
- Create: `research/theory/formation-conditions.md`

- [ ] **Step 12.1: Create `research/README.md`**

```markdown
# Research — 火烧云研究板块

研究板块的产出是知识，最终目的是反哺 `predictor/rules.py`。

## 目录

- `theory/` — 原理笔记，每篇一个主题
- `notebooks/` — 探索性 Jupyter notebook，验证假设、看数据
- `observations/log.md` — 自己的火烧云观察日志，将来用作 ML 训练集
- `data/` — 原始/中间数据，大文件 gitignore

## 工作流

```
读资料 / 观察一次火烧云
    ↓
theory/ 新增/更新一篇笔记
    ↓
predictor/rules.py 新增 ScoringRule 或调权重
    ↓
predictor/tests/ 加单测
    ↓
apps/notebook/forecast-map.ipynb 重跑看效果
    ↓
对照 observations/log.md 验证
```
```

- [ ] **Step 12.2: Create `research/theory/00-index.md`**

```markdown
# Theory 索引

| 文件 | 主题 | 对应规则 |
|---|---|---|
| [cloud-physics.md](cloud-physics.md) | 云的分层与覆盖 | MidHighCloudPresence, LowCloudObstruction |
| [atmospheric-optics.md](atmospheric-optics.md) | 瑞利 vs 米氏散射 | （间接，多条） |
| [solar-geometry.md](solar-geometry.md) | 日落几何与光程 | SolarAngleAtSunset |
| [aerosols-and-color.md](aerosols-and-color.md) | 气溶胶对火烧云色彩的影响 | （未来扩展） |
| [formation-conditions.md](formation-conditions.md) | 火烧云形成的综合条件 | （总览） |
```

- [ ] **Step 12.3: Create the 5 theory skeleton files**

Each file has the same structure (replace `<TOPIC>` accordingly):

```markdown
# <TOPIC>

> 一句话概括这篇笔记要回答什么问题。

## 概念

（写下核心定义、原理）

## 关键变量

（哪些气象/物理量与这个机制相关，怎么测量）

## 资料来源

- 

## 对预测规则的启示

（这部分知识如何转化为 `predictor/rules.py` 中的某条 `ScoringRule`？）
```

Create:
- `research/theory/cloud-physics.md` (topic: 云的分层与覆盖)
- `research/theory/atmospheric-optics.md` (topic: 瑞利散射与米氏散射)
- `research/theory/solar-geometry.md` (topic: 日落几何与大气光程)
- `research/theory/aerosols-and-color.md` (topic: 气溶胶对色彩的影响)
- `research/theory/formation-conditions.md` (topic: 火烧云形成的综合条件)

- [ ] **Step 12.4: Commit**

```bash
git add research/README.md research/theory/
git commit -m "docs(research): scaffold theory notes index + 5 skeleton files"
```

---

## Task 13: Observation Log Template

**Files:**
- Create: `research/observations/log.md`

- [ ] **Step 13.1: Create the file**

```markdown
# 火烧云观察日志

倒序追加。每条记录将来用作 ML 训练集，所以字段越规整越好。

## 模板

```markdown
## YYYY-MM-DD（早晨日出 / 傍晚日落）
- 地点：城市, 州/省（lat, lon 可选）
- 时间：HH:MM（当地时区）
- 评级：N/5（1=无、5=极致）
- 颜色：橙 / 红 / 粉 / 紫 / ...（可多选）
- 云况：高云 / 中云 / 低云 比例和形态
- 能见度：清澈 / 雾霾 / ...
- PM2.5：μg/m³（若有）
- 预测器给的分：0.XX（哪几条规则贡献多少）
- 备注 / 偏差分析：模型在哪里失准了？
- 照片：[link or filename]
```

---

```

- [ ] **Step 13.2: Commit**

```bash
git add research/observations/log.md
git commit -m "docs(research): observation log template"
```

---

## Task 14: Apps Placeholders

**Files:**
- Create: `apps/web/README.md`
- Create: `apps/desktop/README.md`

- [ ] **Step 14.1: Write `apps/web/README.md`**

```markdown
# apps/web — 阶段二占位

Phase 2 Web app 占位。计划：

- 后端：FastAPI 包装 `predictor.score()`
- 前端：React + Mapbox/Leaflet 渲染概率热力图
- 部署：Vercel / Fly.io

详见 `docs/superpowers/specs/` 中阶段二的设计文档（待写）。
```

- [ ] **Step 14.2: Write `apps/desktop/README.md`**

```markdown
# apps/desktop — 阶段三占位

Phase 3 Desktop / Mobile app 占位。计划：

- Tauri（Rust + Web 前端），复用阶段二的前端
- 本地缓存 HRRR 数据，离线可用

详见 `docs/superpowers/specs/` 中阶段三的设计文档（待写）。
```

- [ ] **Step 14.3: Commit**

```bash
git add apps/web/README.md apps/desktop/README.md
git commit -m "docs(apps): placeholder READMEs for phase 2 (web) and phase 3 (desktop)"
```

---

## Task 15: Forecast Notebook (`apps/notebook/forecast-map.ipynb`)

The phase 1 deliverable: a notebook that takes a date/time + bbox, runs `RuleBasedPredictor` over a coarse grid of points, and draws a heatmap on a CONUS map.

**Files:**
- Create: `apps/notebook/forecast-map.ipynb`

This is a Jupyter notebook, so each "step" below is one cell. Use `jupytext` or build it cell-by-cell via the Jupyter UI.

- [ ] **Step 15.1: Cell 1 — Imports**

```python
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from predictor.fetch import HRRRSource
from predictor.rules import (
    RuleBasedPredictor,
    MidHighCloudPresence, LowCloudObstruction,
    SolarAngleAtSunset, HumidityFactor,
)
```

- [ ] **Step 15.2: Cell 2 — Configuration**

```python
# --- Config: edit me ---
QUERY_TIME = datetime.now(timezone.utc) + timedelta(hours=1)  # next hour, UTC
BBOX = (-125.0, 25.0, -67.0, 49.0)  # (lon_min, lat_min, lon_max, lat_max) — CONUS
GRID_RES = 1.5  # degrees between sample points (coarse; finer = slow)
```

- [ ] **Step 15.3: Cell 3 — Build predictor**

```python
source = HRRRSource(cache_dir=Path("../../research/data/cache/hrrr"))
predictor = RuleBasedPredictor(
    rules=[
        MidHighCloudPresence(),
        LowCloudObstruction(),
        SolarAngleAtSunset(),
        HumidityFactor(),
    ],
    weights={
        "mid_high_cloud_presence": 2.0,
        "low_cloud_obstruction": 2.0,
        "solar_angle": 1.5,
        "humidity": 1.0,
    },
    source=source,
)
```

- [ ] **Step 15.4: Cell 4 — Build the grid and score each point**

```python
lon_min, lat_min, lon_max, lat_max = BBOX
lons = np.arange(lon_min, lon_max + GRID_RES, GRID_RES)
lats = np.arange(lat_min, lat_max + GRID_RES, GRID_RES)

LON, LAT = np.meshgrid(lons, lats)
PROB = np.full_like(LON, np.nan, dtype=float)

# Note: HRRRSource caches Herbie downloads, so the first cell is slow,
# subsequent cells fast. For a single run cycle, every grid point hits the
# same GRIB2 file.
for j, lat in enumerate(lats):
    for i, lon in enumerate(lons):
        try:
            forecast = predictor.score(lat=float(lat), lon=float(lon), time=QUERY_TIME)
            PROB[j, i] = forecast.probability
        except Exception as e:
            # Outside HRRR domain or grid mismatch → leave NaN
            PROB[j, i] = np.nan
```

- [ ] **Step 15.5: Cell 5 — Map the heatmap**

```python
fig = plt.figure(figsize=(12, 7))
ax = plt.axes(projection=ccrs.LambertConformal(central_longitude=-96))
ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
ax.add_feature(cfeature.STATES, linewidth=0.4)
ax.add_feature(cfeature.BORDERS, linewidth=0.4)

mesh = ax.pcolormesh(
    LON, LAT, PROB,
    transform=ccrs.PlateCarree(),
    cmap="magma", vmin=0, vmax=1, shading="auto",
)
cbar = plt.colorbar(mesh, ax=ax, orientation="horizontal", pad=0.04, fraction=0.05)
cbar.set_label("Fire-cloud probability")

ax.set_title(f"Firecloud forecast — {QUERY_TIME.isoformat()}")
plt.show()
```

- [ ] **Step 15.6: Cell 6 — Inspect highest- and lowest-scoring points**

```python
flat = PROB.flatten()
valid = ~np.isnan(flat)
order = np.argsort(flat[valid])
ranked_lats = LAT.flatten()[valid][order]
ranked_lons = LON.flatten()[valid][order]
ranked_probs = flat[valid][order]

print("Bottom 3 cells:")
for k in range(3):
    print(f"  ({ranked_lats[k]:.2f}, {ranked_lons[k]:.2f}) → {ranked_probs[k]:.2f}")

print("\nTop 3 cells:")
for k in range(1, 4):
    print(f"  ({ranked_lats[-k]:.2f}, {ranked_lons[-k]:.2f}) → {ranked_probs[-k]:.2f}")

# Detailed explanation for the top point
top_lat, top_lon = float(ranked_lats[-1]), float(ranked_lons[-1])
top_forecast = predictor.score(top_lat, top_lon, QUERY_TIME)
print("\nTop point detail:")
print(f"  {top_forecast.explanation}")
print(f"  inputs: {top_forecast.inputs}")
```

- [ ] **Step 15.7: Verify the notebook runs end-to-end**

Run: `uv run jupyter nbconvert --to notebook --execute apps/notebook/forecast-map.ipynb --output forecast-map-executed.ipynb`
Expected: succeeds without errors. (Network call to HRRR happens during execution; allow ~1–2 minutes.) If it works, delete the `-executed` artifact.

- [ ] **Step 15.8: Commit**

```bash
rm -f apps/notebook/forecast-map-executed.ipynb
git add apps/notebook/forecast-map.ipynb
git commit -m "feat(apps): phase 1 forecast-map notebook rendering CONUS heatmap"
```

---

## Task 16: Top-Level README + Obsidian Symlink

**Files:**
- Create: `README.md`
- Action: Create symlink in Obsidian vault

- [ ] **Step 16.1: Write `README.md`**

```markdown
# Firecloud Forecast

火烧云（sunset glow / 朝霞晚霞）概率预测。两个板块：研究 + 应用。

**当前阶段：Phase 1 — Jupyter notebook 在美国本土地图上画概率热力图。**

后续：Phase 2（Web app）→ Phase 3（Desktop app）。

## 板块

- `research/` — 气象/光学原理笔记、探索 notebook、观察日志
- `predictor/` — 可复用的 Python 包：`Forecast`, `Predictor`, `ScoringRule`, `RuleBasedPredictor`, `HRRRSource`
- `apps/` — 展示层：notebook（已实现）、web 与 desktop（占位）
- `docs/superpowers/` — 设计文档与实现计划

## 快速开始

### 系统依赖（macOS）

```bash
brew install eccodes geos proj
```

### Python 环境

```bash
uv sync
```

### 跑测试

```bash
uv run pytest -m "not integration"        # 单元测试
uv run pytest -m integration              # 真实 HRRR 网络测试（手动跑）
```

### 跑 Phase 1 notebook

```bash
uv run jupyter lab apps/notebook/forecast-map.ipynb
```

顶部 cell 改 `QUERY_TIME` / `BBOX` / `GRID_RES`，依次 run all。

## Obsidian 集成

项目目录通过软链接接入 Obsidian vault：

```bash
ln -s /Users/nickzhu/Desktop/Projects/firecloud-forecast \
      "/Users/nickzhu/Documents/Nick's Second Brain/Projects/firecloud-forecast"
```

Markdown 笔记享有 wikilinks / graph view 等能力；`.ipynb` / `.py` 在 Obsidian 中不被解析但可见。

## 设计文档

- 阶段一设计：[docs/superpowers/specs/2026-05-20-firecloud-forecast-design.md](docs/superpowers/specs/2026-05-20-firecloud-forecast-design.md)
- 阶段一实现计划：[docs/superpowers/plans/2026-05-20-firecloud-forecast-phase1.md](docs/superpowers/plans/2026-05-20-firecloud-forecast-phase1.md)
```

- [ ] **Step 16.2: Create the Obsidian symlink**

**Before running:** the Obsidian vault has its own CLAUDE.md at `/Users/nickzhu/Documents/Nick's Second Brain/CLAUDE.md` that may have vault-specific rules. If running this step in a new session, load that file first.

```bash
mkdir -p "/Users/nickzhu/Documents/Nick's Second Brain/Projects"
ln -s /Users/nickzhu/Desktop/Projects/firecloud-forecast \
      "/Users/nickzhu/Documents/Nick's Second Brain/Projects/firecloud-forecast"
ls -la "/Users/nickzhu/Documents/Nick's Second Brain/Projects/firecloud-forecast"
```

Expected: `ls` shows the symlink resolving to the project folder.

- [ ] **Step 16.3: Commit**

```bash
git add README.md
git commit -m "docs: top-level README with setup, run, and Obsidian-link instructions"
```

- [ ] **Step 16.4: Final verification**

Run all unit tests: `uv run pytest -m "not integration" -v`
Expected: all green, ~19 tests.

Run notebook smoke test: `uv run jupyter nbconvert --to notebook --execute apps/notebook/forecast-map.ipynb --output /tmp/exec-check.ipynb && rm /tmp/exec-check.ipynb`
Expected: succeeds.

---

## Self-Review

**Spec coverage** — each spec section mapped to a task:

| Spec section | Task(s) |
|---|---|
| 顶层目录结构 | 1, 12, 14, 16 |
| `Forecast` / `Predictor` 协议 | 2 |
| `Features` + 太阳几何 | 3 |
| `WeatherSnapshot` / `WeatherSource` 抽象 | 4 |
| HRRRSource via Herbie + 缓存 | 5 |
| 4 条初始 ScoringRule | 6, 7, 8, 9 |
| RuleBasedPredictor 组装 | 10 |
| 测试策略（单元 + 端到端） | 2–11 |
| 研究板块 5–10 篇笔记 | 12 |
| 观察日志 log.md | 13 |
| apps/web, apps/desktop 占位 | 14 |
| apps/notebook 阶段一交付 | 15 |
| README + 环境搭建 | 16 |
| Obsidian 软链接 | 16 |

**Placeholder scan** — searched for "TBD", "TODO", "..." (outside code blocks), "implement later", "similar to": no matches outside intentional spec-level `...` in type stubs.

**Type consistency** — cross-checked names:
- `Forecast(probability, components, explanation, inputs)` — defined Task 2, used Tasks 10, 11, 15
- `Features` fields — defined Task 3, accessed by all rules in Tasks 6–9
- `WeatherSnapshot(cloud_low_pct, cloud_mid_pct, cloud_high_pct, humidity_pct, source_label, retrieved_at)` — defined Task 4, used Tasks 5, 10, 11
- `WeatherSource.fetch(lat, lon, time) -> WeatherSnapshot` — same signature across `FakeSource` (Task 4) and `HRRRSource` (Task 5)
- Rule class names (`MidHighCloudPresence`, `LowCloudObstruction`, `SolarAngleAtSunset`, `HumidityFactor`) — consistent across Tasks 6–11 and 15

No type mismatches found.
