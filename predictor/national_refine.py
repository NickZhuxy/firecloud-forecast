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
