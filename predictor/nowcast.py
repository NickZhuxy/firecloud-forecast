"""Stage C orchestration: satellite nowcast into the products (#84).

Wires the pure #16 algorithms (`cloud_motion`) into a product-facing stage:
a per-cell freshness gate (nowcasting is only physical within ~2 h of the
event), two Himawari B13 frames, one motion estimate, then a bounded
confidence-weighted correction applied band-by-band (Task 2). Every failure
on the satellite side — no eligible cells, S3 down, satpy missing, too few
frames, regime "none" — passes through with ``applied=False`` and the
product bit-identical to the un-nowcast run.

The only IO is the injected ``satellite_source``; everything else is pure,
so the default test suite covers this module with synthetic frames.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from predictor.cloud_motion import (
    DEFAULT_CLOUD_MOTION_CONFIG,
    CloudMotionConfig,
    MotionVector,
    estimate_motion,
)
from predictor.satellite import nearest_slot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NowcastStageConfig:
    enabled: bool = True
    # Mirrors CloudMotionConfig.max_lead_hr: cells whose event is further out
    # than this are not eligible — nowcasting nudges, it does not forecast.
    max_lead_hr: float = 2.0
    # Motion-pair spacing. At 0.25° pixels the velocity floor is one pixel per
    # pair gap: 10 min ⇒ 1.5°/hr (~165 km/h — real clouds quantize to zero,
    # observed live); 30 min ⇒ 0.5°/hr, inside CloudMotionConfig's [5, 40].
    pair_gap_min: int = 30
    slot_cadence_min: int = 10        # Himawari full-disk cadence (walk-back step)
    motion: CloudMotionConfig = field(default_factory=lambda: DEFAULT_CLOUD_MOTION_CONFIG)


DEFAULT_NOWCAST_CONFIG = NowcastStageConfig()


@dataclass
class NowcastStageResult:
    corrected_probability: np.ndarray   # full grid; == input outside corrected cells
    corrected_mask: np.ndarray          # bool — cells actually nudged
    motion: MotionVector | None
    applied: bool
    source: str                         # "satellite" | "model"
    reason: str
    lead_hr_range: tuple[float, float] | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lead_hours(event_times: np.ndarray, now: datetime) -> np.ndarray:
    """Per-cell hours from ``now`` to the event (negative = already past)."""
    events = np.asarray(event_times).astype("datetime64[s]").astype("int64")
    return (events - int(_as_utc(now).timestamp())) / 3600.0


def _passthrough(
    probability: np.ndarray,
    reason: str,
    motion: MotionVector | None = None,
    lead_hr_range: tuple[float, float] | None = None,
) -> NowcastStageResult:
    prob = np.asarray(probability, dtype=float)
    return NowcastStageResult(
        corrected_probability=prob.copy(),
        corrected_mask=np.zeros(prob.shape, dtype=bool),
        motion=motion,
        applied=False,
        source="model",
        reason=reason,
        lead_hr_range=lead_hr_range,
    )


def _fetch_frames(satellite_source, lats, lons, now: datetime, config: NowcastStageConfig):
    """Two consecutive *published* B13 frames near ``now``.

    The correlation search needs context beyond the model grid (±6 px at
    0.25° = 1.5°), so the frame bbox widens by 2°. Himawari L1b lands on S3
    with 10–20 min latency, so the nearest slot often 404s while earlier
    slots exist — walk back up to three slots for a published pair (the
    later frame of each pair is tried first to fail fast).
    """
    lat_min, lat_max = float(np.min(lats)) - 2.0, float(np.max(lats)) + 2.0
    lon_min, lon_max = float(np.min(lons)) - 2.0, float(np.max(lons)) + 2.0
    bbox = (lat_min, lat_max, lon_min, lon_max)
    newest = nearest_slot(_as_utc(now))
    last_exc: Exception | None = None
    for shift in range(3):
        later = newest - timedelta(minutes=config.slot_cadence_min * shift)
        earlier = later - timedelta(minutes=config.pair_gap_min)
        try:
            later_frame = satellite_source.fetch_brightness_temp(later, bbox=bbox)
            earlier_frame = satellite_source.fetch_brightness_temp(earlier, bbox=bbox)
        except Exception as exc:  # noqa: BLE001 — try the previous slot pair
            last_exc = exc
            continue
        return [earlier_frame, later_frame]
    raise last_exc if last_exc is not None else SatelliteUnavailable("no frames")


def stage_block(result: NowcastStageResult, prior_probability: np.ndarray) -> dict:
    """The product-metadata stats block for one nowcast run (#84).

    Shared by the national and local products so both JSON sidecars carry the
    same keys. Stats only — no grids — matching the products' metadata style.
    """
    prior = np.asarray(prior_probability, dtype=float)
    finite = prior[np.isfinite(prior)]
    return {
        "applied": result.applied,
        "source": result.source,
        "reason": result.reason,
        "regime": result.motion.regime if result.motion else None,
        "confidence": result.motion.confidence if result.motion else None,
        "motion_deg_per_hr": (
            [result.motion.du_deg_per_hr, result.motion.dv_deg_per_hr]
            if result.motion else None
        ),
        "cells_corrected": int(result.corrected_mask.sum()),
        "mean_abs_delta": (
            float(np.abs(
                result.corrected_probability[result.corrected_mask]
                - prior[result.corrected_mask]
            ).mean())
            if result.corrected_mask.any() else 0.0
        ),
        "lead_hr_range": list(result.lead_hr_range) if result.lead_hr_range else None,
        "physics_probability_range": {
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        },
    }


def apply_nowcast(
    probability: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    event_times: np.ndarray,
    satellite_source,
    *,
    now: datetime,
    config: NowcastStageConfig = DEFAULT_NOWCAST_CONFIG,
) -> NowcastStageResult:
    """Bounded satellite nudge for the cells whose event is within the window.

    ``event_times`` is an (ny, nx) datetime64 grid (a scalar event time is
    passed as a filled grid). Zero eligible cells return before any satellite
    IO, so a morning run for tonight's sunset costs nothing and changes
    nothing.
    """
    prob = np.asarray(probability, dtype=float)
    if not config.enabled:
        return _passthrough(prob, "nowcast disabled")

    leads = _lead_hours(event_times, now)
    eligible = (leads >= 0.0) & (leads <= config.max_lead_hr) & np.isfinite(prob)
    if not eligible.any():
        return _passthrough(prob, "no cells within nowcast window")
    lead_hr_range = (float(leads[eligible].min()), float(leads[eligible].max()))

    try:
        frames = _fetch_frames(satellite_source, lats, lons, now, config)
    except Exception as exc:  # noqa: BLE001 — satellite failures must never fail the product
        logger.warning("nowcast: satellite frames unavailable (%s) — keeping model field", exc)
        return _passthrough(prob, f"satellite frames unavailable: {exc}", lead_hr_range=lead_hr_range)

    motion = estimate_motion(frames, config.motion)
    if motion.regime == "none" or motion.confidence <= 0.0:
        return _passthrough(
            prob, f"no usable motion ({motion.reason})", motion=motion,
            lead_hr_range=lead_hr_range,
        )

    return _apply_banded_correction(
        prob, lats, lons, event_times, eligible, motion, now, config, lead_hr_range
    )


def _pixel_shift(displacement_deg, lats, lons) -> tuple[int, int]:
    """(drow, dcol) the roll inside ``nowcast_correction`` used on this grid."""
    du, dv = displacement_deg
    dlon = float(lons[1] - lons[0])
    dlat = float(lats[1] - lats[0])
    return int(round(dv / dlat)), int(round(du / dlon))


def _wrap_invalid_mask(shape, drow: int, dcol: int) -> np.ndarray:
    """Cells whose advected source wrapped around ``np.roll``'s boundary.

    ``nowcast_correction`` advects with a periodic roll; at the field edges the
    "upstream" data comes from the opposite side of the grid — wrong data, so
    those strips keep the model value and stay out of ``corrected_mask``.
    """
    invalid = np.zeros(shape, dtype=bool)
    if dcol > 0:
        invalid[:, :dcol] = True
    elif dcol < 0:
        invalid[:, dcol:] = True
    if drow > 0:
        invalid[:drow, :] = True
    elif drow < 0:
        invalid[drow:, :] = True
    return invalid


def _apply_banded_correction(
    prob, lats, lons, event_times, eligible, motion, now, config, lead_hr_range
) -> NowcastStageResult:
    """One bounded correction per event hour, written back to that band only.

    Eligible cells within one product span at most ~3 hourly bands (window is
    2 h); each band advects with its own lead so east-China cells minutes from
    sunset are nudged less than west-China cells two hours out.
    """
    from predictor.cloud_motion import nowcast_correction

    events_s = np.asarray(event_times).astype("datetime64[s]").astype("int64")
    band_hours = (events_s + 1800) // 3600      # nearest hour, epoch-hours
    now_s = int(_as_utc(now).timestamp())

    corrected = prob.copy()
    corrected_mask = np.zeros(prob.shape, dtype=bool)
    sub_pixel_only = True
    for band in np.unique(band_hours[eligible]):
        band_mask = eligible & (band_hours == band)
        lead_hr = max(0.0, (int(band) * 3600 - now_s) / 3600.0)
        corr = nowcast_correction(prob, lats, lons, motion, lead_hr, config.motion)
        if corr.source != "satellite":
            continue
        drow, dcol = _pixel_shift(corr.displacement_deg, lats, lons)
        if drow == 0 and dcol == 0:
            # Displacement below this grid's resolution: the "correction" is
            # the identity — claiming corrected cells would be dishonest.
            continue
        sub_pixel_only = False
        write = band_mask & ~_wrap_invalid_mask(prob.shape, drow, dcol)
        corrected[write] = corr.corrected_field[write]
        corrected_mask |= write

    if not corrected_mask.any():
        reason = (
            "cloud motion below grid resolution (0 px over pair gap)"
            if sub_pixel_only
            else "correction degenerate (edge guard removed every cell)"
        )
        return _passthrough(prob, reason, motion=motion, lead_hr_range=lead_hr_range)
    return NowcastStageResult(
        corrected_probability=corrected,
        corrected_mask=corrected_mask,
        motion=motion,
        applied=True,
        source="satellite",
        reason=f"bounded {motion.regime} correction (conf {motion.confidence:.1f})",
        lead_hr_range=lead_hr_range,
    )
