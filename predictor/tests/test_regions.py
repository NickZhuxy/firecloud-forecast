"""Product-region boundaries constrain observers, never atmospheric samples."""
import pytest

from predictor.regions import REGION_KEYS, get_region


def test_china_retains_existing_product_capabilities():
    region = get_region()
    assert REGION_KEYS == ("china", "us-nyc")
    assert region.national_enabled and region.remote_enabled and region.satellite_enabled
    assert region.local_product_name == "china_firecloud_local"
    region.validate_center(31.23, 121.47)


def test_nyc_is_explicit_local_pilot():
    region = get_region("us-nyc")
    assert region.timezone_name == "America/New_York"
    assert region.country_code == "USA"
    assert not region.national_enabled
    assert not region.remote_enabled
    assert not region.satellite_enabled
    region.validate_center(40.7128, -74.0060)


@pytest.mark.parametrize("lat,lon", [(34.05, -118.25), (42.36, -71.06),
    (float("nan"), -74), (40.7, float("inf")), (91, -74), (40.7, 286)])
def test_invalid_or_outside_pilot_observers_rejected(lat, lon):
    with pytest.raises(ValueError):
        get_region("us-nyc").validate_center(lat, lon)


def test_unknown_region_rejected():
    with pytest.raises(ValueError, match="unknown region"):
        get_region("us")
