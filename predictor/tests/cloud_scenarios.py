"""Controlled cloud-diagnosis scenarios for offline regression testing (#7).

Each scenario is a hand-built ``NormalizedProfile`` plus the expected diagnosis
(layer count, base/top ranges, confidence direction). They guard threshold and
merge-rule changes against silent regressions without any network access.

IMPORTANT: if you change ``CloudDiagnosisConfig`` defaults in
``predictor/clouds.py``, you MUST revisit and update the expectations here —
``test_cloud_regression.py`` pins those defaults so a drift fails loudly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from predictor.profiles import NormalizedProfile

# A shared standard-ish column (hPa / geometric m / K).
LEVELS = np.array([950, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200.0])
HEIGHTS = np.array([540, 990, 1460, 1950, 3010, 4200, 5570, 7180, 9160, 10360, 11770.0])
TEMP = np.array([291, 288, 285, 281, 274, 267, 256, 243, 228, 220, 217.0])
N = LEVELS.size


def _profile(*, clw=None, ice=None, rh=None) -> NormalizedProfile:
    nan = np.full(N, np.nan)
    return NormalizedProfile(
        lat=31.0, lon=121.0,
        pressure_hpa=LEVELS.copy(),
        geometric_height_m=HEIGHTS.copy(),
        geopotential_height_m=HEIGHTS.copy(),
        temperature_k=TEMP.copy(),
        relative_humidity_pct=np.asarray(rh, float) if rh is not None else np.full(N, 30.0),
        dewpoint_k=TEMP - 10.0,
        specific_humidity_kg_kg=np.full(N, 0.001),
        u_wind_m_s=np.zeros(N), v_wind_m_s=np.zeros(N),
        vertical_velocity_pa_s=np.zeros(N),
        cloud_water_kg_kg=np.asarray(clw, float) if clw is not None else nan.copy(),
        cloud_ice_kg_kg=np.asarray(ice, float) if ice is not None else nan.copy(),
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="scenario", retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        missing=[],
    )


def _zeros():
    return np.zeros(N)


@dataclass
class LayerExpect:
    base_m: tuple[float, float]
    top_m: tuple[float, float]
    conf_max: float
    phase_hint: str | None = None
    source: str | None = None


@dataclass
class Scenario:
    name: str
    profile: NormalizedProfile
    n_layers: int
    layers: list[LayerExpect]


def _clear():
    return _profile(clw=_zeros(), ice=_zeros(), rh=np.full(N, 25.0))


def _thin_high_cirrus():
    ice = _zeros(); ice[8] = 1e-4   # single 300 hPa level (~9160 m)
    return _profile(clw=_zeros(), ice=ice)


def _low_stratus():
    clw = _zeros(); clw[0:2] = 1e-4  # 950–900 hPa (~540–990 m)
    return _profile(clw=clw, ice=_zeros())


def _multi_layer():
    clw = _zeros(); clw[4:6] = 1.2e-4   # 700–600 hPa deck
    ice = _zeros(); ice[8:10] = 5e-5    # 300–250 hPa cirrus
    return _profile(clw=clw, ice=ice)


def _deep_convective():
    clw = _zeros(); clw[2:9] = 1.5e-4   # 850→300 hPa column
    ice = _zeros(); ice[7:9] = 4e-5     # glaciated top
    return _profile(clw=clw, ice=ice)


def _missing_data_rh():
    rh = np.full(N, 30.0); rh[4:7] = 95.0  # condensate NaN → RH fallback band
    return _profile(rh=rh)


SCENARIOS: list[Scenario] = [
    Scenario("clear", _clear(), 0, []),
    Scenario(
        "thin_high_cirrus", _thin_high_cirrus(), 1,
        [LayerExpect(base_m=(7000, 8500), top_m=(9000, 10500), conf_max=0.6,
                     phase_hint="ice", source="condensate")],
    ),
    Scenario(
        "low_stratus", _low_stratus(), 1,
        [LayerExpect(base_m=(400, 700), top_m=(1000, 1600), conf_max=0.8,
                     phase_hint="liquid", source="condensate")],
    ),
    Scenario(
        "multi_layer", _multi_layer(), 2,
        [
            LayerExpect(base_m=(2000, 3000), top_m=(4500, 5200), conf_max=0.85, source="condensate"),
            LayerExpect(base_m=(7800, 8600), top_m=(10500, 11500), conf_max=0.85, source="condensate"),
        ],
    ),
    Scenario(
        "deep_convective", _deep_convective(), 1,
        [LayerExpect(base_m=(1000, 1600), top_m=(9000, 10000), conf_max=0.85, source="condensate")],
    ),
    Scenario(
        "missing_data_rh", _missing_data_rh(), 1,
        [LayerExpect(base_m=(2500, 4000), top_m=(4500, 5800), conf_max=0.5, source="rh")],
    ),
]
