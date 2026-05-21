from datetime import datetime, timezone
from predictor.features import Features, compute_sun_info


def test_features_dataclass_holds_fields():
    f = Features(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=40,
        humidity_pct=60, solar_elevation_deg=2.0,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),
        query_time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc),
        location=(42.36, -71.06),
    )
    assert f.cloud_high_pct == 40


def test_compute_sun_info_for_boston_late_may():
    # Boston sunset on 2026-05-20 is approximately 20:08 EDT = 00:08 UTC next day
    dt = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
    info = compute_sun_info(lat=42.36, lon=-71.06, dt=dt)
    assert "sunset" in info and "elevation" in info
    # Sunset should be on the queried local date; just sanity-check it's a datetime.
    assert isinstance(info["sunset"], datetime)
    # Elevation at the query time should be low (sun near horizon)
    assert -10.0 < info["elevation"] < 15.0
