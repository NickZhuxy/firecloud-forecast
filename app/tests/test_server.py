from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.server as server
from predictor.clouds import CloudLayer
from predictor.fetch import WeatherSnapshot
from predictor.spatial import SunwardProfile


client = TestClient(server.app)


def _no_gfs(monkeypatch):
    """Stub the slow GFS diagnosis so point tests stay offline and deterministic."""
    monkeypatch.setattr(server, "_diagnose_cloud_layers", lambda lat, lon, t: None)


def test_index_uses_national_overlay_endpoint():
    response = client.get("/")

    assert response.status_code == 200
    assert "/api/overlay/cn" in response.text
    assert "/api/forecast/overlay" not in response.text


def test_health_endpoint():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_point_forecast_fetches_weather_for_sunset(monkeypatch):
    sunset = datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)
    snapshot = WeatherSnapshot(
        cloud_low_pct=10,
        cloud_mid_pct=50,
        cloud_high_pct=60,
        humidity_pct=55,
        source_label="fake@sunset-window",
        retrieved_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        visibility_m=25_000,
        sunset_time=sunset,
    )
    calls = []

    class Source:
        def fetch_for_sunset(self, lat, lon, evening_hint, score_offset):
            calls.append((lat, lon, evening_hint, score_offset))
            return snapshot

    monkeypatch.setattr(server, "_source", Source())
    _no_gfs(monkeypatch)
    server._point_cache.clear()

    response = client.get(
        "/api/forecast",
        params={"lat": 31.23, "lon": 121.47, "date": "2026-06-22"},
    )

    assert response.status_code == 200
    body = response.json()
    assert calls
    assert body["sunset_utc"] == sunset.isoformat()
    assert body["scored_utc"] == "2026-06-22T10:50:00+00:00"
    assert body["inputs"]["source"] == "fake@sunset-window"
    # New-vs-old cloud-base provenance is observable in the response (#13). With
    # no diagnosed layers and no source base, it falls back to the fixed estimate
    # (high deck → 7000 m representative height) at lowered confidence.
    geometry = body["geometry"]
    assert geometry["cloud_base_source"] == "fixed_estimate"
    assert geometry["cloud_base_fixed_m"] == 7000.0
    assert geometry["cloud_base_confidence"] == 0.4


def test_bad_date_returns_400():
    response = client.get(
        "/api/forecast",
        params={"lat": 31.23, "lon": 121.47, "date": "not-a-date"},
    )

    assert response.status_code == 400


def test_point_forecast_exposes_sunward_boundary_and_aod(monkeypatch):
    snapshot = WeatherSnapshot(
        cloud_low_pct=5,
        cloud_mid_pct=70,
        cloud_high_pct=20,
        humidity_pct=55,
        source_label="fake@profile",
        retrieved_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        visibility_m=25_000,
        aerosol_optical_depth=0.12,
    )
    snapshot.sunward_profile = SunwardProfile(
        azimuth_deg=285.0,
        distances_km=[0.0, 50.0, 100.0, 200.0],
        cloud_low_pct=[5.0, 5.0, 10.0, 5.0],
        cloud_mid_pct=[70.0, 60.0, 40.0, 5.0],
        cloud_high_pct=[20.0, 20.0, 10.0, 0.0],
        aerosol_optical_depth=[0.12, 0.13, 0.14, 0.15],
        wind_speed_850_m_s=[5.0] * 4,
        wind_direction_850_deg=[90.0] * 4,
        wind_speed_700_m_s=[10.0] * 4,
        wind_direction_700_deg=[105.0] * 4,
        wind_speed_400_m_s=[20.0] * 4,
        wind_direction_400_deg=[105.0] * 4,
    )

    class Source:
        def fetch_sunward_profile(self, lat, lon, time, azimuth_deg):
            return snapshot

    monkeypatch.setattr(server, "_source", Source())
    _no_gfs(monkeypatch)
    server._point_cache.clear()

    response = client.get(
        "/api/forecast",
        params={"lat": 31.23, "lon": 121.47, "date": "2026-06-22"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["spatial"]["cloud_boundary_km"] is not None
    assert body["inputs"]["aerosol_optical_depth"] == 0.12
    assert "sunward_illumination" in body["components"]
    assert "boundary_confidence" in body["components"]


def _simple_source(snapshot):
    class Source:
        def fetch_for_sunset(self, lat, lon, evening_hint, score_offset):
            return snapshot

    return Source()


def _plain_snapshot():
    return WeatherSnapshot(
        cloud_low_pct=10, cloud_mid_pct=50, cloud_high_pct=60, humidity_pct=55,
        source_label="fake@sunset-window",
        retrieved_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        visibility_m=25_000, sunset_time=datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc),
    )


def test_detailed_point_uses_diagnosed_cloud_base(monkeypatch):
    monkeypatch.setattr(server, "_source", _simple_source(_plain_snapshot()))
    # GFS diagnosis returns a high deck → its base drives cloud_base_m (#30/#13).
    high = CloudLayer(8000.0, 10000.0, 2000.0, "ice", 0.77, "condensate", signal_margin=10.0)
    monkeypatch.setattr(server, "_diagnose_cloud_layers", lambda lat, lon, t: [high])
    server._point_cache.clear()

    body = client.get(
        "/api/forecast", params={"lat": 31.23, "lon": 121.47, "date": "2026-06-22"}
    ).json()
    geo = body["geometry"]
    assert geo["cloud_base_source"] == "diagnosed"
    assert geo["cloud_base_m"] == 8000.0
    assert geo["cloud_base_confidence"] == 0.77
    # Old fixed estimate (high deck → 7000 m) retained for comparison.
    assert geo["cloud_base_fixed_m"] == 7000.0


def test_detailed_point_falls_back_when_gfs_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_source", _simple_source(_plain_snapshot()))
    monkeypatch.setattr(server, "_diagnose_cloud_layers", lambda lat, lon, t: None)
    server._point_cache.clear()

    geo = client.get(
        "/api/forecast", params={"lat": 31.23, "lon": 121.47, "date": "2026-06-22"}
    ).json()["geometry"]
    assert geo["cloud_base_source"] != "diagnosed"
    assert geo["cloud_base_source"] == "fixed_estimate"


def test_gfs_diagnosis_helper_degrades_to_none_on_failure(monkeypatch):
    # _diagnose_cloud_layers must swallow GFS failures (network/unavailable).
    class Boom:
        def fetch_profile(self, lat, lon, t):
            raise RuntimeError("gfs down")

    monkeypatch.setattr(server, "_gfs_source", Boom())
    assert server._diagnose_cloud_layers(31.23, 121.47, datetime(2026, 6, 22, 11, tzinfo=timezone.utc)) is None


def test_overlay_image_rejects_unknown_cache_key():
    response = client.get("/api/overlay/image/not-a-cache-key.png")

    assert response.status_code == 404
