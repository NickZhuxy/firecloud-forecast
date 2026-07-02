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

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

from predictor.clouds import CloudDiagnosisConfig, DEFAULT_CLOUD_CONFIG
from predictor.fetch import WeatherSnapshot
from predictor.rules import standard_predictor
from predictor.spatial import GFS_GRID_RES_DEG, build_sunward_path
from predictor.sunward_section import score_point_with_cube

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
    # Candidates dropped by the max_cells cost cap (they keep their screen
    # probability). Non-zero only when the cap actually bit; always logged.
    cells_skipped: int = 0


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


def _candidate_groups(
    candidate_mask, selected_time, lats, lons, tile_deg
) -> dict[tuple[int, int, int], list[tuple[int, int]]]:
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


def _group_bbox(
    cells, lats, lons, event_times, azimuth_deg, distances_km, margin_deg
) -> tuple[float, float, float, float]:
    # ``cells`` is always non-empty: it comes from a ``_candidate_groups`` value,
    # each built via ``setdefault(key, []).append(...)``. An empty list would yield
    # a degenerate inverted bbox, so callers must not bypass ``_candidate_groups``.
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
    max_cells: int | None = None,
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

    cells_skipped = 0
    if max_cells is not None:
        n_candidates = int(candidate_mask.sum())
        if n_candidates > max_cells:
            # Keep the highest-screen candidates (stable order → deterministic
            # under ties); the rest keep their screen probability. Never
            # silent: the cap is logged and reported via cells_skipped.
            flat = np.flatnonzero(candidate_mask)
            order = np.argsort(screen.ravel()[flat], kind="stable")[::-1]
            candidate_mask = candidate_mask.copy()
            candidate_mask.ravel()[flat[order[max_cells:]]] = False
            cells_skipped = n_candidates - max_cells
            logger.warning(
                "national refine capped: refining %d of %d candidates "
                "(max_cells=%d, %d keep their screen probability)",
                max_cells, n_candidates, max_cells, cells_skipped,
            )

    predictor = standard_predictor(_PlaceholderSource())
    groups = _candidate_groups(candidate_mask, selected_time, lats, lons, tile_deg)

    cubes_fetched = 0
    cells_refined = 0
    # Hour-major order: all of one valid hour's tile groups run back-to-back so
    # the hour's decoded dataset (~300 MB resident) can be released before the
    # next hour loads — peak memory stays ~one dataset instead of one per hour.
    # (Also makes the processing order fully deterministic.)
    release = getattr(cube_source, "release_cube", None)
    previous_hour: int | None = None
    for (hour_idx, _tj, _ti), cells in sorted(groups.items(), key=lambda kv: kv[0]):
        if release is not None and previous_hour is not None and hour_idx != previous_hour:
            release(valid_times[previous_hour])
        previous_hour = hour_idx
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

    if release is not None and previous_hour is not None:
        release(valid_times[previous_hour])

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
        cells_skipped=cells_skipped,
    )
