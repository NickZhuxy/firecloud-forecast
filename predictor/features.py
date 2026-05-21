"""Derived features used by scoring rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from astral import Observer
from astral.sun import sun, elevation


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

    `snapshot` is duck-typed — it must expose: cloud_low_pct, cloud_mid_pct,
    cloud_high_pct, humidity_pct.
    """
    sun_info = compute_sun_info(lat, lon, time)
    return Features(
        cloud_low_pct=snapshot.cloud_low_pct,
        cloud_mid_pct=snapshot.cloud_mid_pct,
        cloud_high_pct=snapshot.cloud_high_pct,
        humidity_pct=snapshot.humidity_pct,
        solar_elevation_deg=sun_info["elevation"],
        sunset_time=sun_info["sunset"],
        query_time=time,
        location=(lat, lon),
    )
