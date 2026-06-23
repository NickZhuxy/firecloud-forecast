"""Shared scoring-time helpers for the web app.

Both the per-point endpoint (``server``) and the national overlay builder
(``overlay``) score weather a fixed offset before local sunset and need a rough
"local evening" UTC instant to anchor Open-Meteo's nearest-sunset selection.
Keeping these in one place avoids the two modules drifting apart.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone

SCORE_OFFSET = timedelta(minutes=10)  # score this long before sunset


def evening_instant(lon: float, d: date_cls) -> datetime:
    """A UTC instant near local evening (≈18:00 local) for date ``d``.

    Longitude approximates the local-to-UTC offset (no timezone DB needed),
    which is enough to land Open-Meteo's nearest-sunset pick on the right evening.
    """
    base = datetime.combine(d, time_cls(18, 0), tzinfo=timezone.utc)
    return base - timedelta(hours=lon / 15.0)
