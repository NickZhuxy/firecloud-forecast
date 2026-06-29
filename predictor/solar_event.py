"""Sunrise/sunset parameterization (#60).

The fire-cloud physics is left-right symmetric: a morning glow (朝霞) over the
eastern sky at sunrise is the mirror of an evening glow (晚霞) over the western sky
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
from enum import Enum


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
    label_zh: str


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
