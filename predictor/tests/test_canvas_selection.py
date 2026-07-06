"""FA-C2 multi-criteria canvas selection (#88, manual §4.1.1).

The canvas pick follows the manual's 伊春 worked example — étage cover and
sunward boundary distance rank the diagnosed decks, with optical substance and
height as soft criteria — instead of "highest deck always wins". Invariants
from research/theory/fa-c2-canvas-layer-selection.md §4.
"""
import math

from predictor.clouds import CloudLayer, tier_from_height
from predictor.illumination import canvas_layer_from_diagnosis, select_canvas


def _layer(base, top, *, phase="ice", conf=0.8, tau=float("nan")):
    return CloudLayer(
        base, top, top - base, phase, conf, "condensate",
        signal_margin=10.0, optical_depth=tau,
    )


def _wisp_high():
    return _layer(7000, 8000, phase="ice", conf=0.5, tau=0.05)


def _solid_mid():
    return _layer(3500, 5500, phase="mixed", conf=0.8, tau=3.0)


# ---------------------------------------------------------------------------
# Acceptance case (audit §3.B): sparse cirrus must not outrank a solid deck.
# ---------------------------------------------------------------------------


def test_wisp_cirrus_does_not_beat_solid_mid_deck():
    layers = [_solid_mid(), _wisp_high()]
    canvas = canvas_layer_from_diagnosis(
        layers, cover_pct_by_tier={"mid": 80.0, "high": 5.0}
    )
    assert canvas is layers[0]


def test_dominant_cirrus_cover_keeps_high_canvas():
    # Flip the covers: a sky-wide (if sheer) cirrus veil IS the show.
    layers = [_solid_mid(), _wisp_high()]
    canvas = canvas_layer_from_diagnosis(
        layers, cover_pct_by_tier={"mid": 5.0, "high": 80.0}
    )
    assert canvas is layers[1]


# ---------------------------------------------------------------------------
# Direction law: raising a deck's étage cover never demotes it from canvas.
# ---------------------------------------------------------------------------


def test_raising_cover_never_demotes_from_canvas():
    layers = [_solid_mid(), _wisp_high()]
    was_canvas = False
    for high_cover in range(0, 101, 5):
        canvas = canvas_layer_from_diagnosis(
            layers, cover_pct_by_tier={"mid": 50.0, "high": float(high_cover)}
        )
        is_canvas = canvas is layers[1]
        assert not (was_canvas and not is_canvas), (
            f"high deck lost canvas when its cover rose to {high_cover}%"
        )
        was_canvas = is_canvas


# ---------------------------------------------------------------------------
# Étage precedence (#13 semantics kept): low cloud under a present mid/high
# deck is obstruction, not canvas; it becomes eligible only when nothing
# mid/high is present (manual §4.1.1 深圳 stratocumulus case).
# ---------------------------------------------------------------------------


def test_low_deck_never_outranks_present_mid_deck():
    low = _layer(800, 1500, phase="liquid", conf=0.9, tau=8.0)
    mid = _layer(3500, 4500, phase="mixed", conf=0.6, tau=1.0)
    canvas = canvas_layer_from_diagnosis(
        [low, mid], cover_pct_by_tier={"low": 95.0, "mid": 15.0}
    )
    assert canvas is mid


def test_low_deck_wins_when_mid_high_below_presence():
    low = _layer(800, 1500, phase="liquid", conf=0.9, tau=8.0)
    mid = _layer(3500, 4500, phase="mixed", conf=0.6, tau=1.0)
    canvas = canvas_layer_from_diagnosis(
        [low, mid], cover_pct_by_tier={"low": 95.0, "mid": 5.0}
    )
    assert canvas is low


def test_low_only_sky_keeps_low_canvas():
    low = _layer(1800, 2000 - 200, phase="liquid", conf=0.8)  # 深圳-like stratocumulus
    assert canvas_layer_from_diagnosis([low]) is low


# ---------------------------------------------------------------------------
# Height stays a (soft) preference: all else equal, the higher deck wins —
# the old behaviour survives as the degenerate equal-criteria case.
# ---------------------------------------------------------------------------


def test_equal_decks_prefer_higher():
    mid = _layer(3000, 4000, phase="ice", conf=0.8, tau=2.0)
    high = _layer(7000, 8000, phase="ice", conf=0.8, tau=2.0)
    canvas = canvas_layer_from_diagnosis(
        [mid, high], cover_pct_by_tier={"mid": 60.0, "high": 60.0}
    )
    assert canvas is high


def test_bare_layers_equal_substance_keeps_highest():
    # No covers/boundaries supplied and identical decks → same as the old rule.
    a = _layer(3000, 4000, phase="ice", conf=0.8)
    b = _layer(7000, 8000, phase="ice", conf=0.8)
    assert canvas_layer_from_diagnosis([a, b]) is b


def test_single_layer_is_always_canvas():
    only = _layer(7000, 9000)
    assert canvas_layer_from_diagnosis([only]) is only
    # Even when its own étage cover reads zero (cross-field disagreement),
    # a single diagnosed deck stays the canvas rather than yielding None.
    assert (
        canvas_layer_from_diagnosis([only], cover_pct_by_tier={"high": 0.0}) is only
    )
    assert canvas_layer_from_diagnosis([]) is None


# ---------------------------------------------------------------------------
# Boundary distance (manual 伊春: "高云边界比中云边界近,所以直接看中云").
# ---------------------------------------------------------------------------


def test_yichun_configuration_prefers_mid():
    # HCDC < MCDC AND the high deck's sunward boundary is nearer → mid canvas,
    # even though the high deck would win on height alone.
    mid = _layer(3500, 5500, phase="mixed", conf=0.8, tau=2.0)
    high = _layer(7000, 8000, phase="ice", conf=0.8, tau=2.0)
    canvas = canvas_layer_from_diagnosis(
        [mid, high],
        cover_pct_by_tier={"mid": 70.0, "high": 30.0},
        boundary_km_by_tier={"mid": 166.0, "high": 60.0},
    )
    assert canvas is mid


def test_extending_boundary_never_demotes_from_canvas():
    mid = _layer(3500, 5500, phase="ice", conf=0.8, tau=2.0)
    high = _layer(7000, 8000, phase="ice", conf=0.8, tau=2.0)
    was_canvas = False
    for boundary in range(0, 801, 50):
        canvas = canvas_layer_from_diagnosis(
            [mid, high],
            cover_pct_by_tier={"mid": 60.0, "high": 60.0},
            boundary_km_by_tier={"mid": 200.0, "high": float(boundary)},
        )
        is_canvas = canvas is high
        assert not (was_canvas and not is_canvas), (
            f"high deck lost canvas when its boundary moved out to {boundary} km"
        )
        was_canvas = is_canvas


# ---------------------------------------------------------------------------
# Robustness: NaN/None-safe, deterministic ties.
# ---------------------------------------------------------------------------


def test_missing_and_nan_data_is_safe():
    layers = [
        _layer(800, 1500, phase="liquid", conf=float("nan")),
        _layer(3500, 4500, phase="mixed", conf=0.6),        # τ NaN
        _layer(7000, 8000, phase="ice", conf=0.5, tau=0.2),
    ]
    # Covers missing some tiers, boundaries partially given: must return a
    # deterministic layer, never raise, never produce a NaN ordering.
    canvas = canvas_layer_from_diagnosis(
        layers,
        cover_pct_by_tier={"high": 40.0},
        boundary_km_by_tier={"mid": 100.0},
    )
    assert canvas in layers[1:]  # low ineligible: mid/high present
    repeat = canvas_layer_from_diagnosis(
        layers,
        cover_pct_by_tier={"high": 40.0},
        boundary_km_by_tier={"mid": 100.0},
    )
    assert repeat is canvas


def test_exact_tie_breaks_to_higher_base():
    lower = _layer(6500, 7500, phase="ice", conf=0.8, tau=1.0)
    upper = _layer(8000, 9000, phase="ice", conf=0.8, tau=1.0)
    # Same tier → same cover; same τ/conf; same (missing) boundary. The only
    # asymmetry left is the height preference, so the upper deck must win and
    # keep winning regardless of input order.
    for layers in ([lower, upper], [upper, lower]):
        assert canvas_layer_from_diagnosis(
            [l for l in layers], cover_pct_by_tier={"high": 50.0}
        ) is upper


# ---------------------------------------------------------------------------
# Selection report (Features/detail exposure): per-candidate criteria.
# ---------------------------------------------------------------------------


def test_select_canvas_reports_candidates():
    low = _layer(800, 1500, phase="liquid", conf=0.9, tau=8.0)
    mid = _solid_mid()
    high = _wisp_high()
    selection = select_canvas(
        [low, mid, high],
        cover_pct_by_tier={"low": 90.0, "mid": 80.0, "high": 5.0},
        boundary_km_by_tier={"mid": 166.0, "high": 60.0},
    )
    assert selection.layer is mid
    assert len(selection.candidates) == 3

    by_layer = {id(c.layer): c for c in selection.candidates}
    assert by_layer[id(low)].eligible is False       # étage precedence
    assert by_layer[id(mid)].eligible is True
    assert by_layer[id(mid)].is_canvas is True
    assert by_layer[id(high)].is_canvas is False
    # Criteria terms are recorded, finite, and within their design ranges.
    for cand in selection.candidates:
        assert cand.tier == tier_from_height(cand.layer.base_m)
        for term in (cand.cover_term, cand.substance_term,
                     cand.height_term, cand.extent_term):
            assert math.isfinite(term) and 0.0 <= term <= 1.0
        assert math.isfinite(cand.score)
    # The winning score is the max among eligible candidates.
    eligible = [c for c in selection.candidates if c.eligible]
    assert max(eligible, key=lambda c: c.score).layer is mid


def test_select_canvas_empty_and_none_safe():
    selection = select_canvas([])
    assert selection.layer is None
    assert selection.candidates == []
