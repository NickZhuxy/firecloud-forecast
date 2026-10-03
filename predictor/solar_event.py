"""Sunrise/sunset parameterization (#60).

The fire-cloud physics is left-right symmetric: a morning glow over the
eastern sky at sunrise is the mirror of an evening glow over the western sky
at sunset. The whole pipeline runs as ONE code path over a ``solar_event`` rather
than duplicating "sunset" logic.

Only four things actually differ between the events, and they all live here:

- ``astral_key`` — which key to read from ``astral.sun.sun(...)`` (the event time);
- ``daily_field`` — the Open-Meteo ``daily=`` field to request/read;
- ``fallback_solar_hour`` — local-solar-hour used at the polar edge when astral
  cannot resolve the event (dusk 18 vs dawn 6);
- ``label_en`` / ``label_zh`` — display/labelling strings.

Everything else falls out of the event *time*: the sunward azimuth is whatever
``astral`` reports at that instant (≈270° west at sunset, ≈90° east at sunrise), and
the GFS forecast-hour selection just tracks the event-time grid. So no azimuth or
forecast-step field is needed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun


class SolarEvent(str, Enum):
    SUNSET = "sunset"
    SUNRISE = "sunrise"


@dataclass(frozen=True)
class SolarEventSpec:
    event: SolarEvent
    astral_key: str            # astral.sun.sun(...)[astral_key]
    daily_field: str           # Open-Meteo daily= field
    fallback_solar_hour: float  # local solar hour for the polar-edge fallback
    label_en: str
    label_zh: str  # Legacy localization API; CLI output uses English.


_SPECS: dict[SolarEvent, SolarEventSpec] = {
    SolarEvent.SUNSET: SolarEventSpec(
        SolarEvent.SUNSET, "sunset", "sunset", 18.0, "Sunset", "晚霞"
    ),
    SolarEvent.SUNRISE: SolarEventSpec(
        SolarEvent.SUNRISE, "sunrise", "sunrise", 6.0, "Sunrise", "朝霞"
    ),
}


def spec_for(solar_event: SolarEvent | str) -> SolarEventSpec:
    """Resolve the spec for a ``SolarEvent`` or its literal string ("sunrise"/"sunset")."""
    return _SPECS[SolarEvent(solar_event)]


def event_time_utc(
    target_date: date, lat: float, lon: float,
    solar_event: SolarEvent | str = SolarEvent.SUNSET,
    *, timezone_name: str | None = None,
) -> datetime:
    """Resolve an event on the location's solar date, returning UTC.

    A regional date is not a UTC date: a western sunset can occur tomorrow in
    UTC, and an eastern sunrise yesterday. Use longitude's mean-solar offset
    solely to select the event day, then convert the resulting instant to UTC.
    An explicit IANA ``timezone_name`` selects the region's civil calendar day.
    Without it, the existing longitude-based solar-day policy is retained.

    Accept both signed and GFS 0–360 longitudes. Missing polar events raise
    ValueError; the grid caller retains its existing polar fallback.
    """
    signed_lon = (lon + 180.0) % 360.0 - 180.0
    solar_tz = (
        ZoneInfo(timezone_name) if timezone_name is not None
        else timezone(timedelta(hours=signed_lon / 15.0))
    )
    observer = Observer(latitude=lat, longitude=signed_lon)
    event = sun(observer, date=target_date, tzinfo=solar_tz)[spec_for(solar_event).astral_key]
    return event.astimezone(timezone.utc)
