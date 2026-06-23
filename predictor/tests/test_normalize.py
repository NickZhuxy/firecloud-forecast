"""Unit tests for profile normalization (#6)."""
from datetime import datetime, timezone

import numpy as np

from predictor import thermo
from predictor.normalize import NormalizedProfile, normalize
from predictor.profiles import PROFILE_VARS, AtmosphericProfile


def _raw_profile(**overrides) -> AtmosphericProfile:
    """A deliberately messy raw profile: unsorted, a duplicate, a NaN-height level."""
    n = 5
    levels = np.array([850.0, 700.0, 700.0, 500.0, 300.0])
    gph = np.array([1500.0, 3000.0, 3000.0, 5800.0, np.nan])  # 300 hPa height missing
    t = np.array([288.0, 281.0, 281.0, 270.0, 250.0])
    q = np.array([0.008, 0.005, 0.005, 0.001, 0.0002])
    fields = {var: np.full(n, 0.0) for var in PROFILE_VARS}
    fields["temperature_k"] = t
    fields["specific_humidity_kg_kg"] = q
    fields["geopotential_height_m"] = gph
    fields["relative_humidity_pct"] = np.full(n, 42.0)  # source RH (fallback path)
    fields.update(overrides)
    return AtmosphericProfile(
        lat=31.0, lon=121.0, levels_hpa=levels,
        run_time=datetime(2026, 6, 23, 0, tzinfo=timezone.utc),
        valid_time=datetime(2026, 6, 23, 6, tzinfo=timezone.utc),
        source_label="gfs@2026-06-23T00Z+f06",
        retrieved_at=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
        missing=["cloud_ice_kg_kg"],
        **fields,
    )


def test_normalize_sorts_dedupes_and_drops_missing_levels():
    norm = normalize(_raw_profile())
    assert isinstance(norm, NormalizedProfile)
    # NaN-height (300 hPa) dropped; duplicate 700 collapsed → 3 strict levels.
    assert norm.pressure_hpa.tolist() == [850.0, 700.0, 500.0]
    assert np.all(np.diff(norm.geometric_height_m) > 0)  # strictly increasing


def test_geometric_height_exceeds_geopotential_aloft():
    norm = normalize(_raw_profile())
    # 500 hPa level: geopotential 5800 m → geometric slightly larger.
    i = norm.pressure_hpa.tolist().index(500.0)
    assert norm.geometric_height_m[i] > norm.geopotential_height_m[i]
    assert norm.geometric_height_m[i] == thermo.geopotential_to_geometric_height(5800.0)


def test_rh_and_dewpoint_in_physical_range():
    norm = normalize(_raw_profile())
    assert np.all((norm.relative_humidity_pct >= 0) & (norm.relative_humidity_pct <= 100))
    assert np.all(norm.dewpoint_k <= norm.temperature_k + 1e-6)
    # RH at 850 hPa is computed from q, T, p (not the 42% source fallback).
    expected = thermo.specific_humidity_to_rh(0.008, 288.0, 850.0)
    assert norm.relative_humidity_pct[0] == float(expected)


def test_rh_falls_back_to_source_when_specific_humidity_missing():
    raw = _raw_profile(specific_humidity_kg_kg=np.full(5, np.nan))
    norm = normalize(raw)
    assert np.allclose(norm.relative_humidity_pct, 42.0)


def test_metadata_and_missing_preserved():
    norm = normalize(_raw_profile())
    assert norm.source_label == "gfs@2026-06-23T00Z+f06"
    assert norm.missing == ["cloud_ice_kg_kg"]
    assert norm.lat == 31.0 and norm.lon == 121.0
