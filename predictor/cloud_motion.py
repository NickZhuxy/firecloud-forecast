"""Satellite cloud-edge motion nowcasting and bounded model correction (#16).

Near sunset, consecutive IR-window frames (Himawari B13, the same
``BrightnessTempField`` produced for #15) reveal where the cloud edge actually is
and which way it is moving. This module is the pure algorithm (no satellite I/O):
given two or more co-gridded frames it estimates a displacement vector by
bounded-search cross-correlation of the cloud masks, classifies the regime
(steady advection vs developing convection, which advection models poorly), and
applies a *bounded* advective correction to a model cloud/probability field —
falling back to the untouched model when frames are missing, too far apart in
time, or the motion is ill-determined (no forced extrapolation).

I/O (pulling consecutive frames) stays in :mod:`predictor.satellite`; passive IR
does not constrain cloud base, so only the horizontal cloud edge is corrected.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from predictor.satellite import BrightnessTempField


@dataclass(frozen=True)
class CloudMotionConfig:
    cloud_bt_threshold_k: float = 273.0   # below this brightness temp = opaque cloud
    min_frame_gap_min: float = 5.0        # closer than this → motion is noise
    max_frame_gap_min: float = 40.0       # farther than this → motion unreliable
    max_search_px: int = 6                # cross-correlation search radius (pixels)
    max_displacement_deg: float = 2.0     # cap on the correction magnitude
    max_lead_hr: float = 2.0
    convective_bt_drop_k: float = 8.0     # mean cloud-top cooling → developing convection
    advective_confidence: float = 0.8
    convective_confidence: float = 0.4
    min_overlap_frac: float = 0.1         # weak cross-correlation overlap → lower confidence


DEFAULT_CLOUD_MOTION_CONFIG = CloudMotionConfig()


@dataclass
class MotionVector:
    du_deg_per_hr: float          # eastward displacement rate (deg lon / hr)
    dv_deg_per_hr: float          # northward displacement rate (deg lat / hr)
    speed_deg_per_hr: float
    regime: str                   # "advective" | "convective" | "none"
    confidence: float             # 0–1
    reason: str
    n_frames: int


@dataclass
class NowcastCorrection:
    model_field: np.ndarray       # the original model cloud/probability field
    corrected_field: np.ndarray   # after the bounded, confidence-weighted correction
    displacement_deg: tuple[float, float]   # (du, dv) actually applied (already bounded)
    confidence: float
    regime: str
    source: str                   # "satellite" | "model"
    reason: str


def cloud_mask(frame: BrightnessTempField, config: CloudMotionConfig = DEFAULT_CLOUD_MOTION_CONFIG) -> np.ndarray:
    """Boolean opaque-cloud mask: finite pixels colder than the IR threshold."""
    bt = np.asarray(frame.brightness_temp_k, dtype=float)
    return np.isfinite(bt) & (bt < config.cloud_bt_threshold_k)


def _no_motion(reason: str, n_frames: int) -> MotionVector:
    return MotionVector(0.0, 0.0, 0.0, "none", 0.0, reason, n_frames)


def estimate_motion(
    frames: list[BrightnessTempField],
    config: CloudMotionConfig = DEFAULT_CLOUD_MOTION_CONFIG,
) -> MotionVector:
    """Displacement vector + regime from consecutive co-gridded frames."""
    n = len(frames)
    if n < 2:
        return _no_motion("need ≥2 frames to estimate motion", n)

    ordered = sorted(frames, key=lambda f: f.observation_time)
    f0, f1 = ordered[0], ordered[-1]
    dt_hr = (f1.observation_time - f0.observation_time).total_seconds() / 3600.0
    gap_min = dt_hr * 60.0
    if gap_min < config.min_frame_gap_min or gap_min > config.max_frame_gap_min:
        return _no_motion(
            f"frame gap {gap_min:.0f} min outside "
            f"[{config.min_frame_gap_min:.0f}, {config.max_frame_gap_min:.0f}]",
            n,
        )

    lats = np.asarray(f0.lats, dtype=float)
    lons = np.asarray(f0.lons, dtype=float)
    m0 = cloud_mask(f0, config).astype(float)
    m1 = cloud_mask(f1, config).astype(float)
    if m0.sum() == 0 or m1.sum() == 0:
        return _no_motion("no opaque cloud in a frame", n)

    # Integer pixel shift of frame0 that best overlays frame1's cloud mask.
    (dy, dx), overlap = _best_shift(m0, m1, config.max_search_px)
    overlap_frac = overlap / min(m0.sum(), m1.sum())

    dlon = float(lons[1] - lons[0])   # > 0 (ascending)
    dlat = float(lats[1] - lats[0])   # < 0 (descending)
    du = (dx * dlon) / dt_hr          # +east
    dv = (dy * dlat) / dt_hr          # +north (dy>0 is south, dlat<0 → sign works out)
    speed = float(np.hypot(du, dv))

    bt_change = float(
        np.asarray(f1.brightness_temp_k)[cloud_mask(f1, config)].mean()
        - np.asarray(f0.brightness_temp_k)[cloud_mask(f0, config)].mean()
    )
    if bt_change < -config.convective_bt_drop_k:
        regime = "convective"
        confidence = config.convective_confidence
        reason = f"cloud tops cooled {bt_change:.0f} K → developing convection"
    else:
        regime = "advective"
        confidence = config.advective_confidence
        reason = "steady advection"

    if overlap_frac < config.min_overlap_frac:
        confidence *= overlap_frac / config.min_overlap_frac
        reason += "; weak cross-correlation overlap"

    return MotionVector(du, dv, speed, regime, round(min(1.0, confidence), 3), reason, n)


def _best_shift(m0: np.ndarray, m1: np.ndarray, max_shift: int) -> tuple[tuple[int, int], float]:
    """Integer (dy, dx) shift of ``m0`` maximizing overlap with ``m1``."""
    best_shift = (0, 0)
    best_score = -1.0
    for dy in range(-max_shift, max_shift + 1):
        rolled_y = np.roll(m0, dy, axis=0)
        for dx in range(-max_shift, max_shift + 1):
            score = float((np.roll(rolled_y, dx, axis=1) * m1).sum())
            if score > best_score:
                best_score = score
                best_shift = (dy, dx)
    return best_shift, best_score


def nowcast_correction(
    model_field: np.ndarray,
    model_lats: np.ndarray,
    model_lons: np.ndarray,
    motion: MotionVector,
    lead_time_hr: float,
    config: CloudMotionConfig = DEFAULT_CLOUD_MOTION_CONFIG,
) -> NowcastCorrection:
    """Apply a bounded, confidence-weighted advective correction to ``model_field``."""
    field = np.asarray(model_field, dtype=float)

    if motion.regime == "none" or motion.confidence <= 0.0:
        return NowcastCorrection(
            field, field.copy(), (0.0, 0.0), motion.confidence, motion.regime,
            "model", f"no usable motion ({motion.reason}); kept model field",
        )

    lead = float(np.clip(lead_time_hr, 0.0, config.max_lead_hr))
    du_total = motion.du_deg_per_hr * lead
    dv_total = motion.dv_deg_per_hr * lead

    # Bound the correction magnitude — nowcasting nudges, it does not extrapolate far.
    mag = float(np.hypot(du_total, dv_total))
    if mag > config.max_displacement_deg:
        scale = config.max_displacement_deg / mag
        du_total *= scale
        dv_total *= scale

    lats = np.asarray(model_lats, dtype=float)
    lons = np.asarray(model_lons, dtype=float)
    dlon = float(lons[1] - lons[0])   # > 0
    dlat = float(lats[1] - lats[0])   # < 0
    dcol = int(round(du_total / dlon))            # +east
    drow = int(round(dv_total / dlat))            # +north → negative row (dlat<0)
    advected = np.roll(np.roll(field, drow, axis=0), dcol, axis=1)

    # Confidence-weighted blend toward the advected edge (bounded probability nudge).
    corrected = field + motion.confidence * (advected - field)

    return NowcastCorrection(
        field, corrected, (float(du_total), float(dv_total)),
        motion.confidence, motion.regime, "satellite",
        f"bounded {motion.regime} correction over {lead:.1f} h",
    )
