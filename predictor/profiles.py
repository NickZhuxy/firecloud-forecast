"""Vertical atmospheric-profile data types.

Pure data model with no acquisition dependency, so downstream consumers
(profile normalization, cloud-layer diagnosis) can operate on it without
importing Herbie/GFS machinery. ``GFSSource`` in ``predictor.gfs`` produces
these; tests construct them directly.

``AtmosphericProfile`` is a single vertical column; ``AtmosphericCube`` is a
bbox-cropped region grid of the same variables. Per-level gaps are stored as
NaN; variables absent from the source entirely are listed in ``missing``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime

import numpy as np

# The per-level variables carried by both Profile and Cube, in canonical order.
# Each maps to one array (1-D for a profile, 3-D ``(nz, ny, nx)`` for a cube).
PROFILE_VARS: tuple[str, ...] = (
    "temperature_k",
    "relative_humidity_pct",
    "specific_humidity_kg_kg",
    "geopotential_height_m",
    "u_wind_m_s",
    "v_wind_m_s",
    "vertical_velocity_pa_s",
    "cloud_water_kg_kg",
    "cloud_ice_kg_kg",
)


@dataclass
class AtmosphericProfile:
    """A single vertical column at one grid point and valid time."""

    lat: float
    lon: float
    levels_hpa: np.ndarray  # descending pressure (high pressure / low altitude first)
    temperature_k: np.ndarray
    relative_humidity_pct: np.ndarray
    specific_humidity_kg_kg: np.ndarray
    geopotential_height_m: np.ndarray
    u_wind_m_s: np.ndarray
    v_wind_m_s: np.ndarray
    vertical_velocity_pa_s: np.ndarray
    cloud_water_kg_kg: np.ndarray
    cloud_ice_kg_kg: np.ndarray
    run_time: datetime
    valid_time: datetime
    source_label: str
    retrieved_at: datetime
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, np.ndarray):
                out[f.name] = value.tolist()
            elif isinstance(value, datetime):
                out[f.name] = value.isoformat()
            else:
                out[f.name] = value
        return out


@dataclass
class AtmosphericCube:
    """A bbox-cropped region grid: one value per (level, lat, lon)."""

    lats: np.ndarray  # 1-D (ny)
    lons: np.ndarray  # 1-D (nx)
    levels_hpa: np.ndarray  # 1-D (nz)
    temperature_k: np.ndarray  # (nz, ny, nx); remaining vars share this shape
    relative_humidity_pct: np.ndarray
    specific_humidity_kg_kg: np.ndarray
    geopotential_height_m: np.ndarray
    u_wind_m_s: np.ndarray
    v_wind_m_s: np.ndarray
    vertical_velocity_pa_s: np.ndarray
    cloud_water_kg_kg: np.ndarray
    cloud_ice_kg_kg: np.ndarray
    run_time: datetime
    valid_time: datetime
    source_label: str
    retrieved_at: datetime
    missing: list[str] = field(default_factory=list)

    def profile_at(self, lat: float, lon: float) -> AtmosphericProfile:
        """Extract the nearest-grid-point column as an ``AtmosphericProfile``."""
        yi = _nearest_index(self.lats, lat)
        xi = _nearest_lon_index(self.lons, lon)
        columns = {
            var: np.asarray(getattr(self, var))[:, yi, xi] for var in PROFILE_VARS
        }
        return AtmosphericProfile(
            lat=float(self.lats[yi]),
            lon=float(self.lons[xi]),
            levels_hpa=np.asarray(self.levels_hpa),
            run_time=self.run_time,
            valid_time=self.valid_time,
            source_label=self.source_label,
            retrieved_at=self.retrieved_at,
            missing=list(self.missing),
            **columns,
        )


def _nearest_index(coord: np.ndarray, value: float) -> int:
    """Index of the entry in a 1-D coordinate array closest to ``value``."""
    return int(np.argmin(np.abs(np.asarray(coord) - value)))


def _nearest_lon_index(lons: np.ndarray, lon: float) -> int:
    """Nearest longitude index, tolerant of 0–360 vs ±180 and the 0/360 seam."""
    diff = np.abs((np.asarray(lons) - lon + 180.0) % 360.0 - 180.0)
    return int(np.argmin(diff))
