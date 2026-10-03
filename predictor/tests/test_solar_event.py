# predictor/tests/test_solar_event.py
"""Tests for predictor/solar_event.py — the sunrise/sunset parameterization (#60)."""
import pytest

from predictor.solar_event import SolarEvent, SolarEventSpec, spec_for


def test_solar_event_values():
    assert SolarEvent.SUNSET.value == "sunset"
    assert SolarEvent.SUNRISE.value == "sunrise"


def test_spec_for_sunset_fields():
    spec = spec_for(SolarEvent.SUNSET)
    assert isinstance(spec, SolarEventSpec)
    assert spec.astral_key == "sunset"
    assert spec.daily_field == "sunset"
    assert spec.fallback_solar_hour == pytest.approx(18.0)
    assert spec.label_zh == "晚霞"


def test_spec_for_sunrise_fields():
    spec = spec_for(SolarEvent.SUNRISE)
    assert spec.astral_key == "sunrise"
    assert spec.daily_field == "sunrise"
    assert spec.fallback_solar_hour == pytest.approx(6.0)
    assert spec.label_zh == "朝霞"


def test_spec_for_accepts_plain_string():
    # Callers (CLI/args) may pass the literal "sunrise"/"sunset".
    assert spec_for("sunrise").astral_key == "sunrise"
    assert spec_for("sunset").astral_key == "sunset"


def test_spec_for_rejects_unknown():
    with pytest.raises(ValueError):
        spec_for("noon")


@pytest.mark.parametrize("event", [SolarEvent.SUNRISE, SolarEvent.SUNSET])
def test_event_date_is_identical_for_signed_and_gfs_longitudes(event):
    from datetime import date, timezone
    from predictor.solar_event import event_time_utc

    target_date = date(2026, 9, 14)
    signed = event_time_utc(target_date, 34.05, -118.25, event)
    gfs = event_time_utc(target_date, 34.05, 241.75, event)
    assert signed == gfs
    assert signed.tzinfo == timezone.utc


@pytest.mark.parametrize("event", [SolarEvent.SUNRISE, SolarEvent.SUNSET])
@pytest.mark.parametrize("day", ["2026-01-01", "2026-03-08", "2026-06-21",
    "2026-10-04", "2026-11-01", "2026-12-21"])
def test_nyc_civil_event_date_and_longitude_encoding(event, day):
    from datetime import date
    from zoneinfo import ZoneInfo
    from predictor.solar_event import event_time_utc

    target = date.fromisoformat(day)
    actual = event_time_utc(target, 40.7128, -74.006, event,
                            timezone_name="America/New_York")
    encoded = event_time_utc(target, 40.7128, 285.994, event,
                             timezone_name="America/New_York")
    assert actual == encoded
    assert actual.astimezone(ZoneInfo("America/New_York")).date() == target
    if event == SolarEvent.SUNSET and target.month == 6:
        assert actual.date() > target


def test_nyc_civil_event_timezone_tracks_dst():
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo
    from predictor.solar_event import event_time_utc

    zone = ZoneInfo("America/New_York")
    winter = event_time_utc(date(2026, 1, 1), 40.7128, -74.006,
                            timezone_name=zone.key).astimezone(zone)
    summer = event_time_utc(date(2026, 6, 21), 40.7128, -74.006,
                            timezone_name=zone.key).astimezone(zone)
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)
