"""Standardize a raw ``AtmosphericProfile`` into a ``NormalizedProfile`` (#6).

Unifies temperature/humidity/height from any source into a comparable,
plottable, diagnosable column:

- compute geometric height from geopotential height,
- compute RH and dewpoint from T, q, p (falling back to source RH where
  specific humidity is unavailable), clamped to physical ranges,
- sort levels strictly by geometric height, dropping unusable levels and
  collapsing duplicates.

All thermodynamics and constants live in ``predictor.thermo``.
"""
from __future__ import annotations

import numpy as np

from predictor import thermo
from predictor.profiles import PROFILE_VARS, AtmosphericProfile, NormalizedProfile


def normalize(profile: AtmosphericProfile) -> NormalizedProfile:
    pressure = np.asarray(profile.levels_hpa, dtype=float)
    gph = np.asarray(profile.geopotential_height_m, dtype=float)
    temperature = np.asarray(profile.temperature_k, dtype=float)

    geometric = thermo.geopotential_to_geometric_height(gph)

    # A level is usable only with a finite height (to sort) and temperature.
    usable = np.isfinite(geometric) & np.isfinite(temperature)
    order = np.where(usable)[0]
    order = order[np.argsort(geometric[order], kind="stable")]
    # Collapse duplicate heights, guaranteeing strict monotonicity.
    sorted_heights = geometric[order]
    keep = np.concatenate(([True], np.diff(sorted_heights) > 0)) if order.size else order
    idx = order[keep]

    def col(name: str) -> np.ndarray:
        return np.asarray(getattr(profile, name), dtype=float)[idx]

    pressure_k = pressure[idx]
    temperature_k = temperature[idx]
    q_k = col("specific_humidity_kg_kg")
    source_rh = col("relative_humidity_pct")

    # Canonical RH from q where available, else the source-reported RH.
    rh_from_q = thermo.specific_humidity_to_rh(q_k, temperature_k, pressure_k)
    rh = np.where(np.isfinite(q_k), rh_from_q, np.clip(source_rh, 0.0, 100.0))
    dewpoint = thermo.dewpoint_k(temperature_k, rh)

    other_vars = {
        name: col(name)
        for name in PROFILE_VARS
        if name not in ("temperature_k", "relative_humidity_pct", "specific_humidity_kg_kg", "geopotential_height_m")
    }

    return NormalizedProfile(
        lat=profile.lat,
        lon=profile.lon,
        pressure_hpa=pressure_k,
        geometric_height_m=geometric[idx],
        geopotential_height_m=gph[idx],
        temperature_k=temperature_k,
        relative_humidity_pct=rh,
        dewpoint_k=dewpoint,
        specific_humidity_kg_kg=q_k,
        run_time=profile.run_time,
        valid_time=profile.valid_time,
        source_label=profile.source_label,
        retrieved_at=profile.retrieved_at,
        missing=list(profile.missing),
        **other_vars,
    )
