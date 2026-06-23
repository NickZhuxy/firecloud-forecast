from fastapi.testclient import TestClient

import app.server as server


client = TestClient(server.app)


def test_index_is_overview_only_no_point_analysis():
    response = client.get("/")
    assert response.status_code == 200
    # National overview overlay endpoint is used …
    assert "/api/overlay/cn" in response.text
    # … and the removed point-analysis endpoint is no longer referenced (#40).
    assert "/api/forecast" not in response.text


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_point_forecast_endpoint_is_removed():
    # Point-level analysis was removed (#40); the route should not exist.
    response = client.get(
        "/api/forecast", params={"lat": 31.23, "lon": 121.47, "date": "2026-06-22"}
    )
    assert response.status_code == 404


def test_overlay_bad_date_returns_400():
    response = client.get("/api/overlay/cn", params={"date": "not-a-date"})
    assert response.status_code == 400


def test_overlay_image_rejects_unknown_cache_key():
    response = client.get("/api/overlay/image/not-a-cache-key.png")
    assert response.status_code == 404
