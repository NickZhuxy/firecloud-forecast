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
