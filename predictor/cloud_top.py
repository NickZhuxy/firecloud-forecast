"""Satellite IR cloud-top retrieval and model-top correction (#15).

An opaque cloud radiates from its top at roughly its physical temperature, so an
IR window brightness temperature (Himawari B13 ≈10.4 µm / FY-4B AGRI ≈10.8 µm)
can be matched to the height on a temperature profile where T == Tb — the
satellite-observed cloud-top height. That corrects the model's vertical placement.

This module is the pure algorithm (no satellite I/O): given a brightness
temperature and a ``NormalizedProfile`` it returns a retrieval with confidence
and a human-readable reason, handling inversions (multiple solutions), clouds
colder than the sampled tropopause, near-isothermal layers, and the warmer-than-
surface "no opaque cloud" case. ``correct_cloud_top`` then reconciles the model
top with the retrieval, flagging likely thin / semi-transparent cloud.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from predictor.profiles import NormalizedProfile


@dataclass
class CloudTopRetrieval:
    height_m: float | None       # retrieved geometric cloud-top height (None = no opaque cloud)
    temperature_k: float         # the input brightness temperature
    confidence: float            # 0–1
    reason: str
    n_solutions: int             # profile crossings of Tb (>1 ⇒ inversion ambiguity)


@dataclass
class CloudTopCorrection:
    corrected_top_m: float
    confidence: float
    reason: str
    source: str                  # "satellite" | "model"


@dataclass(frozen=True)
class CloudTopConfig:
    clamp_confidence: float = 0.45      # Tb colder than the profile minimum
    inversion_confidence: float = 0.55  # multiple candidate heights
    base_confidence: float = 0.9        # clean single crossing
    no_cloud_confidence: float = 0.1    # Tb warmer than the surface
    # Below this lapse rate the height of a crossing is poorly constrained.
    weak_lapse_k_per_km: float = 3.0
    # If the satellite top sits this far below the model top, suspect a thin /
    # semi-transparent cloud (IR top biased low by sub-cloud radiance).
    semi_transparent_gap_m: float = 2000.0
    # Largest allowed offset between the satellite slot and the model valid time
    # before the observation is considered too stale to co-locate.
    max_time_gap_minutes: float = 30.0


DEFAULT_CLOUD_TOP_CONFIG = CloudTopConfig()


def retrieve_cloud_top(
    brightness_temp_k: float,
    profile: NormalizedProfile,
    config: CloudTopConfig = DEFAULT_CLOUD_TOP_CONFIG,
) -> CloudTopRetrieval:
    tb = float(brightness_temp_k)
    h = np.asarray(profile.geometric_height_m, dtype=float)
    t = np.asarray(profile.temperature_k, dtype=float)
    valid = np.isfinite(h) & np.isfinite(t)
    h, t = h[valid], t[valid]
    if h.size < 2:
        return CloudTopRetrieval(None, tb, 0.0, "profile too short to retrieve", 0)

    t_min, t_max = float(t.min()), float(t.max())

    # Warmer than the warmest (near-surface) level → no opaque cloud.
    if tb > t_max:
        return CloudTopRetrieval(
            None, tb, config.no_cloud_confidence,
            "brightness temp warmer than surface — no opaque cloud", 0,
        )
    # Colder than the coldest sampled level → top at/above the profile minimum.
    if tb < t_min:
        return CloudTopRetrieval(
            float(h[int(np.argmin(t))]), tb, config.clamp_confidence,
            "colder than profile minimum (deep/cirrus above sampled top)", 0,
        )

    # Collect every height where the profile temperature crosses Tb, with the
    # local lapse rate (K/km) at that crossing.
    crossings: list[tuple[float, float]] = []
    for i in range(h.size - 1):
        t0, t1, h0, h1 = t[i], t[i + 1], h[i], h[i + 1]
        if min(t0, t1) <= tb <= max(t0, t1):
            frac = 0.0 if t1 == t0 else (tb - t0) / (t1 - t0)
            height = h0 + frac * (h1 - h0)
            dh_km = max(abs(h1 - h0) / 1000.0, 1e-6)
            lapse = abs(t1 - t0) / dh_km
            crossings.append((height, lapse))

    # Merge near-duplicate crossings (Tb exactly equal to a shared node).
    crossings.sort()
    merged: list[tuple[float, float]] = []
    for height, lapse in crossings:
        if merged and abs(height - merged[-1][0]) < 1.0:
            continue
        merged.append((height, lapse))
    n = len(merged)

    if n == 0:  # numerical guard (shouldn't happen given the range checks)
        return CloudTopRetrieval(None, tb, config.no_cloud_confidence,
                                 "no profile crossing found", 0)

    # One clean crossing, or pick the highest candidate under an inversion.
    height, lapse = merged[-1] if n > 1 else merged[0]
    if n > 1:
        confidence = config.inversion_confidence
        reason = f"temperature inversion: {n} candidate heights, took the highest"
    else:
        confidence = config.base_confidence
        reason = "single profile crossing"
    if lapse < config.weak_lapse_k_per_km:
        confidence *= lapse / config.weak_lapse_k_per_km
        reason += "; near-isothermal layer (height weakly constrained)"

    return CloudTopRetrieval(float(height), tb, round(float(confidence), 3), reason, n)


def correct_cloud_top(
    model_top_m: float,
    retrieval: CloudTopRetrieval,
    config: CloudTopConfig = DEFAULT_CLOUD_TOP_CONFIG,
) -> CloudTopCorrection:
    """Reconcile a model-diagnosed cloud top with the satellite retrieval."""
    if retrieval.height_m is None:
        return CloudTopCorrection(
            float(model_top_m), retrieval.confidence,
            f"no satellite top ({retrieval.reason}); kept model top", "model",
        )
    gap = model_top_m - retrieval.height_m
    if gap > config.semi_transparent_gap_m:
        # IR top well below the model top: radiance from below a thin/semi-
        # transparent deck biases the retrieved top low. Adopt it but hedge.
        return CloudTopCorrection(
            float(retrieval.height_m), round(retrieval.confidence * 0.6, 3),
            "satellite top well below model top → possible thin/semi-transparent cloud",
            "satellite",
        )
    return CloudTopCorrection(
        float(retrieval.height_m), retrieval.confidence,
        "satellite-corrected top", "satellite",
    )


def infer_base_from_corrected_top(
    model_base_m: float,
    model_top_m: float,
    correction: CloudTopCorrection,
) -> float:
    """Propagate an adopted satellite top to the layer base (FA-C6, §4.2.1(1)).

    The manual's workflow identifies the layer by its IR top and then reads
    that layer's base — so when the top moves, the base moves with it. The
    model THICKNESS is the steadiest quantity the model has for the layer
    (an observed top offset cannot be attributed between "thickness wrong"
    and "base wrong", manual fig. 4.21 — preserving thickness is the neutral
    split), so ``base = corrected_top − model_thickness``. When the correction
    kept the model top, the base is kept too. Pure function; wiring into the
    live satellite path is #15's remaining work, not done here.
    """
    if correction.source != "satellite":
        return float(model_base_m)
    thickness_m = model_top_m - model_base_m
    return float(correction.corrected_top_m - thickness_m)


def _as_utc(time: datetime) -> datetime:
    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    return time.astimezone(timezone.utc)


def colocate_and_correct(
    brightness_temp_k: float | None,
    observation_time: datetime | None,
    model_valid_time: datetime,
    model_top_m: float,
    profile: NormalizedProfile,
    config: CloudTopConfig = DEFAULT_CLOUD_TOP_CONFIG,
) -> CloudTopCorrection:
    """Register a satellite IR pixel to the model column and correct the top.

    The pixel is accepted only when it carries a finite brightness temperature
    *and* its slot lies within ``config.max_time_gap_minutes`` of the model valid
    time. Otherwise the model top is kept unchanged — the safe fallback for a
    missing pixel (sensor gap, off-disk, masked) or an observation too stale to
    represent the forecast instant.
    """
    if brightness_temp_k is None or not np.isfinite(brightness_temp_k):
        return CloudTopCorrection(
            float(model_top_m), 0.0,
            "no satellite brightness temperature; kept model top", "model",
        )
    if observation_time is None:
        return CloudTopCorrection(
            float(model_top_m), 0.0,
            "satellite observation time unknown; kept model top", "model",
        )
    gap_min = abs(
        (_as_utc(observation_time) - _as_utc(model_valid_time)).total_seconds()
    ) / 60.0
    if gap_min > config.max_time_gap_minutes:
        return CloudTopCorrection(
            float(model_top_m), 0.0,
            f"satellite time gap {gap_min:.0f} min exceeds "
            f"{config.max_time_gap_minutes:.0f} min; kept model top",
            "model",
        )

    retrieval = retrieve_cloud_top(float(brightness_temp_k), profile, config)
    return correct_cloud_top(model_top_m, retrieval, config)
