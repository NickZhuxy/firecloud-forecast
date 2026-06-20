"""Derived features used by scoring rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from astral import Observer
from astral.sun import sun, elevation


# Representative base altitudes (metres) for the WMO three-tier cloud layers,
# used to estimate a cloud-base height when the data source does not report one.
_LAYER_BASE_M = {"low": 1000.0, "mid": 3500.0, "high": 7000.0}
_LAYER_PRESENCE_THRESHOLD = 10.0  # percent coverage to count a layer as "present"


@dataclass
class Features:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    humidity_pct: float
    solar_elevation_deg: float
    sunset_time: datetime
    query_time: datetime
    location: tuple[float, float]  # (lat, lon)
    visibility_m: float | None = None
    cloud_base_m: float | None = None


def estimate_cloud_base_m(
    cloud_low_pct: float, cloud_mid_pct: float, cloud_high_pct: float
) -> float | None:
    """Estimate the lowest present cloud layer's base height (metres).

    Returns the representative base of the lowest layer whose coverage exceeds
    the presence threshold, or None if the sky is effectively clear. This is a
    coarse stand-in for a model cloud-base diagnostic (which Open-Meteo does not
    provide); a source that reports cloud base directly should pass it through
    instead of relying on this estimate.
    """
    if cloud_low_pct >= _LAYER_PRESENCE_THRESHOLD:
        return _LAYER_BASE_M["low"]
    if cloud_mid_pct >= _LAYER_PRESENCE_THRESHOLD:
        return _LAYER_BASE_M["mid"]
    if cloud_high_pct >= _LAYER_PRESENCE_THRESHOLD:
        return _LAYER_BASE_M["high"]
    return None


def compute_sun_info(lat: float, lon: float, dt: datetime) -> dict:
    """Return sunset time and solar elevation for the given location & instant.

    Both `dt` and the returned `sunset` are timezone-aware (UTC).
    """
    observer = Observer(latitude=lat, longitude=lon)
    s = sun(observer, date=dt.date(), tzinfo=dt.tzinfo)
    elev = elevation(observer, dateandtime=dt)
    return {"sunset": s["sunset"], "elevation": elev}


def derive(snapshot, lat: float, lon: float, time: datetime) -> Features:
    """Build a Features instance from a WeatherSnapshot + location + query time.

    `snapshot` is duck-typed — it must expose cloud_low_pct, cloud_mid_pct,
    cloud_high_pct, humidity_pct. Optional attributes (visibility_m,
    cloud_base_m, sunset_time) are used when present and filled in otherwise:
    the sunset time falls back to an astral computation, and the cloud base to a
    layer-based estimate.
    """
    sun_info = compute_sun_info(lat, lon, time)

    source_sunset = getattr(snapshot, "sunset_time", None)
    sunset_time = source_sunset if source_sunset is not None else sun_info["sunset"]

    source_base = getattr(snapshot, "cloud_base_m", None)
    cloud_base_m = (
        source_base
        if source_base is not None
        else estimate_cloud_base_m(
            snapshot.cloud_low_pct, snapshot.cloud_mid_pct, snapshot.cloud_high_pct
        )
    )

    return Features(
        cloud_low_pct=snapshot.cloud_low_pct,
        cloud_mid_pct=snapshot.cloud_mid_pct,
        cloud_high_pct=snapshot.cloud_high_pct,
        humidity_pct=snapshot.humidity_pct,
        solar_elevation_deg=sun_info["elevation"],
        sunset_time=sunset_time,
        query_time=time,
        location=(lat, lon),
        visibility_m=getattr(snapshot, "visibility_m", None),
        cloud_base_m=cloud_base_m,
    )
