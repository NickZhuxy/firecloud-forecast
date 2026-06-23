"""Multi-layer cloud diagnosis from a normalized vertical profile (#10).

Replaces fixed low/mid/high representative heights with the real vertical
structure, so illumination geometry and obstruction logic can use diagnosed
cloud bases and tops.

Diagnostic order (per the story):
1. Prefer condensate (liquid + ice mixing ratio) as the cloud signal.
2. When condensate is unavailable, fall back to an RH threshold — at lower
   confidence — using vertical continuity.
3. Interpolate the threshold-crossing height at layer edges and merge layers
   separated by a short gap.
4. Separate the remaining runs into layers, each with a phase hint and the
   diagnostic source.

Thresholds and merge rules live in ``CloudDiagnosisConfig`` with provenance.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from predictor.profiles import NormalizedProfile


@dataclass
class CloudLayer:
    base_m: float
    top_m: float
    thickness_m: float
    phase_hint: str    # "liquid" | "ice" | "mixed"
    confidence: float  # 0–1
    source: str        # "condensate" | "rh"
    # Peak in-layer signal as a multiple of the detection threshold (≥1 inside a
    # layer). Near 1 means the layer barely crossed the threshold (edge case);
    # large means a robust detection. NaN when unset. Consumed by #11.
    signal_margin: float = float("nan")


@dataclass(frozen=True)
class CloudDiagnosisConfig:
    # ~1 mg/kg cloud-condensate cutoff; common threshold for "cloud present" in
    # reanalysis/NWP QC (well above clear-air numerical noise).
    condensate_threshold_kg_kg: float = 1e-6
    # RH proxy for cloud when no condensate is reported. 90% is a conservative
    # large-scale cloud onset value (model diagnostic RH-cloud schemes use 85–100%).
    rh_threshold_pct: float = 90.0
    # Layers separated by less than this vertical gap are treated as one.
    merge_gap_m: float = 300.0
    # Pressure levels below the surface carry extrapolated values; ignore them.
    min_geometric_height_m: float = 0.0
    # Phase hint cutoffs for the RH fallback (no condensate to weigh).
    ice_temp_k: float = 258.15      # < −15 °C → glaciated
    liquid_temp_k: float = 273.15   # > 0 °C → liquid
    # Confidence priors.
    condensate_confidence: float = 0.8
    rh_confidence: float = 0.5
    single_level_factor: float = 0.6   # one level → weak vertical support
    open_edge_factor: float = 0.9      # layer runs to the profile edge → unknown extent


DEFAULT_CLOUD_CONFIG = CloudDiagnosisConfig()


def diagnose_clouds(
    profile: NormalizedProfile, config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG
) -> list[CloudLayer]:
    h = np.asarray(profile.geometric_height_m, dtype=float)
    keep = np.isfinite(h) & (h >= config.min_geometric_height_m)
    h = h[keep]
    if h.size == 0:
        return []

    temp = np.asarray(profile.temperature_k, dtype=float)[keep]
    rh = np.asarray(profile.relative_humidity_pct, dtype=float)[keep]
    clw = np.asarray(profile.cloud_water_kg_kg, dtype=float)[keep]
    ice = np.asarray(profile.cloud_ice_kg_kg, dtype=float)[keep]

    condensate_available = np.isfinite(clw).any() or np.isfinite(ice).any()
    if condensate_available:
        signal = np.nan_to_num(clw) + np.nan_to_num(ice)
        threshold = config.condensate_threshold_kg_kg
        source = "condensate"
    else:
        signal = np.nan_to_num(rh)
        threshold = config.rh_threshold_pct
        source = "rh"

    cloudy = signal >= threshold
    n = h.size

    # Build raw layers with interpolated edges, then merge those separated by a
    # gap (next base − previous top) shorter than merge_gap_m.
    # Condensate is a step signal (≈0 → in-cloud value): a near-zero threshold
    # crossing would pin the edge onto the adjacent clear level and inflate
    # thickness, so use a half-gap midpoint. RH ramps smoothly, so interpolate.
    step_like = source == "condensate"
    raw: list[list] = []  # [i0, i1, base, top]
    for i0, i1 in _true_spans(cloudy):
        base = _interp_base(h, signal, threshold, i0, step_like)
        top = _interp_top(h, signal, threshold, i1, n, step_like)
        raw.append([i0, i1, base, top])

    merged: list[list] = []
    for layer in raw:
        if merged and layer[2] - merged[-1][3] < config.merge_gap_m:
            merged[-1][1] = layer[1]   # extend span end
            merged[-1][3] = layer[3]   # extend top
        else:
            merged.append(layer)

    layers: list[CloudLayer] = []
    for i0, i1, base, top in merged:
        peak = float(np.max(signal[i0:i1 + 1]))
        layers.append(
            CloudLayer(
                base_m=float(base),
                top_m=float(top),
                thickness_m=float(top - base),
                phase_hint=_phase_hint(clw[i0:i1 + 1], ice[i0:i1 + 1], temp[i0:i1 + 1], source, config),
                confidence=_confidence(i0, i1, n, source, config),
                source=source,
                signal_margin=peak / threshold if threshold else float("nan"),
            )
        )
    return layers


def _true_spans(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index ranges of contiguous True runs."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(mask) - 1))
    return spans


def _interp_base(h: np.ndarray, signal: np.ndarray, threshold: float, i0: int, step_like: bool) -> float:
    if i0 == 0:
        return h[0]
    if step_like:
        return (h[i0 - 1] + h[i0]) / 2.0
    s_below, s_in = signal[i0 - 1], signal[i0]
    if s_in == s_below:
        return h[i0]
    frac = np.clip((threshold - s_below) / (s_in - s_below), 0.0, 1.0)
    return h[i0 - 1] + frac * (h[i0] - h[i0 - 1])


def _interp_top(h: np.ndarray, signal: np.ndarray, threshold: float, i1: int, n: int, step_like: bool) -> float:
    if i1 == n - 1:
        return h[i1]
    if step_like:
        return (h[i1] + h[i1 + 1]) / 2.0
    s_in, s_above = signal[i1], signal[i1 + 1]
    if s_in == s_above:
        return h[i1]
    frac = np.clip((s_in - threshold) / (s_in - s_above), 0.0, 1.0)
    return h[i1] + frac * (h[i1 + 1] - h[i1])


def _phase_hint(clw_span, ice_span, temp_span, source, config) -> str:
    cw = float(np.nansum(clw_span))
    ci = float(np.nansum(ice_span))
    if source == "condensate" and (cw + ci) > 0:
        ice_fraction = ci / (cw + ci)
        if ice_fraction > 0.7:
            return "ice"
        if ice_fraction < 0.3:
            return "liquid"
        return "mixed"
    mean_t = float(np.nanmean(temp_span))
    if mean_t < config.ice_temp_k:
        return "ice"
    if mean_t > config.liquid_temp_k:
        return "liquid"
    return "mixed"


def _confidence(i0: int, i1: int, n: int, source: str, config: CloudDiagnosisConfig) -> float:
    conf = config.condensate_confidence if source == "condensate" else config.rh_confidence
    if i0 == i1:
        conf *= config.single_level_factor
    if i0 == 0 or i1 == n - 1:
        conf *= config.open_edge_factor
    return round(float(np.clip(conf, 0.0, 1.0)), 3)
