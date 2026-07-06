"""Sunward vertical cross-section assembly (#18).

Turns the sunward sampling path (#12) plus a normalized vertical profile (#6) at
each path point into a distance × geometric-height field of RH, vertical
velocity, and temperature, with the diagnosed cloud layers (#10) carried per
column. This is the data a forecaster reads to see which moist layers, ascent
regions, and cloud decks the low-angle sunlight crosses on its way in.

Pure assembly: no network, no plotting. Interpolation is explicit (linear in
geometric height) and every cell outside a column's valid range — below the
terrain, above the profile top, or at an out-of-domain/profile-less point — is
masked (NaN + ``mask`` False), so consumers never mistake a gap for data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from predictor.profiles import NormalizedProfile
from predictor.spatial import SunwardPath


@dataclass
class SunwardCrossSection:
    distances_km: list[float]          # x axis (n)
    heights_m: list[float]             # y axis (m), ascending
    relative_humidity_pct: np.ndarray  # (m, n) height × distance; NaN where masked
    vertical_velocity_pa_s: np.ndarray
    temperature_k: np.ndarray
    mask: np.ndarray                   # (m, n) bool: True where the cell holds real data
    cloud_layers: list                 # per-column list of diagnosed CloudLayer
    observer: tuple[float, float]
    azimuth_deg: float
    target_time: datetime
    source_label: str | None = None
    # Per-column column AOD (FA-A2), aligned with ``distances_km``; None entries are
    # unknown columns, the whole attribute is None when no aerosol field was supplied.
    aerosol_optical_depth_per_column: list[float | None] | None = None
    # Per-column ground elevation (FA-G6), aligned with ``distances_km``; None
    # entries are unknown columns, the whole attribute is None when no elevation
    # provider was injected on the path.
    terrain_elevation_m_per_column: list[float | None] | None = None


def even_heights(max_m: float = 15000.0, count: int = 31) -> list[float]:
    """``count`` evenly-spaced heights from 0 to ``max_m`` (inclusive)."""
    if count < 2:
        return [0.0]
    step = max_m / (count - 1)
    return [round(i * step, 6) for i in range(count)]


_FIELDS = (
    ("relative_humidity_pct", "relative_humidity_pct"),
    ("vertical_velocity_pa_s", "vertical_velocity_pa_s"),
    ("temperature_k", "temperature_k"),
)


def build_cross_section(
    path: SunwardPath,
    profiles: list[NormalizedProfile | None],
    layers_per_point: list,
    *,
    heights_m: list[float] | None = None,
    aod_per_column: list[float | None] | None = None,
) -> SunwardCrossSection:
    """Assemble the cross-section from a path and a profile per sample.

    ``profiles[j]`` is the normalized column at ``path.samples[j]`` (or None when
    that point is out of domain / unavailable). ``layers_per_point[j]`` is the
    diagnosed cloud layers there. Each column is linearly interpolated onto the
    shared ``heights_m`` axis and masked outside its valid span. ``aod_per_column``
    (FA-A2), when given, is the column AOD per sample and must align with the path;
    it rides along on the cross-section for the per-column path-extinction trace.
    """
    samples = path.samples
    if not (len(profiles) == len(layers_per_point) == len(samples)):
        raise ValueError("profiles, layers_per_point and path samples must align")
    if aod_per_column is not None and len(aod_per_column) != len(samples):
        raise ValueError("aod_per_column and path samples must align")

    heights = list(heights_m) if heights_m is not None else even_heights()
    h_axis = np.asarray(heights, dtype=float)
    n_h, n_d = h_axis.size, len(samples)

    fields = {name: np.full((n_h, n_d), np.nan) for name, _ in _FIELDS}
    mask = np.zeros((n_h, n_d), dtype=bool)

    for j, (sample, profile) in enumerate(zip(samples, profiles)):
        if profile is None or not sample.in_domain:
            continue
        col_heights = np.asarray(profile.geometric_height_m, dtype=float)
        if col_heights.size == 0:
            continue
        terrain = sample.elevation_m if sample.elevation_m is not None else col_heights[0]
        # Valid where the height is within the profile span AND above the terrain.
        valid = (h_axis >= max(col_heights[0], terrain)) & (h_axis <= col_heights[-1])
        mask[:, j] = valid
        if not valid.any():
            continue
        for name, attr in _FIELDS:
            values = np.asarray(getattr(profile, attr), dtype=float)
            interp = np.interp(h_axis, col_heights, values)
            fields[name][valid, j] = interp[valid]

    source_label = next(
        (p.source_label for p in profiles if p is not None), None
    )
    return SunwardCrossSection(
        distances_km=[float(s.distance_km) for s in samples],
        heights_m=heights,
        relative_humidity_pct=fields["relative_humidity_pct"],
        vertical_velocity_pa_s=fields["vertical_velocity_pa_s"],
        temperature_k=fields["temperature_k"],
        mask=mask,
        cloud_layers=list(layers_per_point),
        observer=path.observer,
        azimuth_deg=path.azimuth_deg,
        target_time=path.target_time,
        source_label=source_label,
        aerosol_optical_depth_per_column=(
            list(aod_per_column) if aod_per_column is not None else None
        ),
        # FA-G6: ground elevation per sample rides along for the terrain trace;
        # all-None (no elevation provider) collapses to None so the no-terrain
        # path stays bit-identical.
        terrain_elevation_m_per_column=(
            [s.elevation_m for s in samples]
            if any(s.elevation_m is not None for s in samples)
            else None
        ),
    )
