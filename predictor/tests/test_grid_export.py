"""Per-cell grid sidecars: the web map reads the same values the PNG draws."""
import json
from datetime import datetime, timezone

import numpy as np
from matplotlib.colors import BoundaryNorm, to_hex
from shapely.geometry import LineString, Polygon

from predictor.grid_export import (
    GRID_SCHEMA,
    color_stops,
    context_polylines,
    limiting_gate,
    local_grid_payload,
)
from predictor.local_field import LocalField
from predictor.map_style import INDEX_CMAP
from predictor.national_product import DISPLAY_INDEX_BOUNDS, MapContext
from predictor.rules import STANDARD_GATES

VALID = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)


def _field(probability):
    probability = np.asarray(probability, dtype=float)
    ny, nx = probability.shape
    return LocalField(
        lats=31.0 + 0.1 * np.arange(ny), lons=121.0 + 0.1 * np.arange(nx),
        probability=probability, center=(31.1, 121.1), radius_km=20.0, valid_time=VALID,
        gate_score=np.clip(probability + 0.1, 0, 1),
        limiting_gate=np.full(probability.shape, "sunward_illumination", dtype=object),
    )


def test_local_payload_is_strict_json_with_null_for_nan():
    field = _field([[0.1, np.nan, 0.5], [0.71234, 0.9, 0.0]])
    payload = local_grid_payload(field, event="sunset", event_time_utc=VALID.isoformat(), context=None)
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["index"][0][1] is None
    assert payload["schema"] == GRID_SCHEMA
    assert payload["scope"] == "point"
    assert payload["center"] == [31.1, 121.1]
    assert payload["limiting"][0][0] == "sunward_illumination"
    assert "nowcast_adjusted" not in payload


def test_payload_index_equals_field_probability_rounded():
    rng = np.random.default_rng(3)
    field = _field(rng.random((4, 5)))
    payload = local_grid_payload(field, event="sunrise", event_time_utc=VALID.isoformat(), context=None)
    np.testing.assert_array_equal(np.array(payload["index"]), np.round(field.probability, 3))
    assert payload["lats"] == [round(float(v), 4) for v in field.lats]


def test_nowcast_mask_is_published_when_the_stage_ran():
    field = _field([[0.2, 0.3]])
    field.nowcast_mask = np.array([[True, False]])
    payload = local_grid_payload(field, event="sunset", event_time_utc=VALID.isoformat(), context=None)
    assert payload["nowcast_adjusted"] == [[True, False]]


def test_limiting_gate_picks_lowest_gate():
    gates = STANDARD_GATES
    components = {"mid_high_cloud_presence": 0.4, "sunward_illumination": 0.0, "humidity": 0.2}
    assert limiting_gate(components, gates) == "sunward_illumination"
    assert limiting_gate({"solar_angle": 0.3, "low_cloud_obstruction": 0.3}, gates) == "solar_angle"
    assert limiting_gate({name: 1.0 for name in gates}, gates) is None
    assert limiting_gate({"humidity": 0.1}, gates) is None


def test_color_stops_match_png_scale():
    norm = BoundaryNorm(DISPLAY_INDEX_BOUNDS, INDEX_CMAP.N, clip=True)
    stops = color_stops()
    assert [bound for bound, _ in stops] == list(DISPLAY_INDEX_BOUNDS[:-1])
    for bound, color in stops:
        assert color == to_hex(INDEX_CMAP(norm(bound)))


def test_context_polylines_are_clipped_simplified_lon_lat_pairs():
    big = Polygon([(100, 20), (140, 20), (140, 50), (100, 50)])
    road = LineString([(121.0, 31.0), (121.05, 31.0005), (121.1, 31.0), (125.0, 31.0)])
    context = MapContext(country=big, surrounding=(), admin1=(road,))
    lines = context_polylines(context, bbox=(30.9, 31.3, 120.9, 121.3), tolerance_deg=0.02)
    assert lines
    for line in lines:
        for lon, lat in line:
            assert 120.89 <= lon <= 121.31 and 30.89 <= lat <= 31.31
            assert lon == round(lon, 3)
    assert context_polylines(None) == []
