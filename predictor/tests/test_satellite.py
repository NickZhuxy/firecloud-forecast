"""Offline unit tests for the Himawari-9 IR ingestion layer (#15).

The real download/decode/resample path is exercised by
``test_satellite_integration.py`` (network-gated). These cover the pure pieces:
slot selection, S3 key/URL construction, and nearest-pixel sampling.
"""
from datetime import datetime, timezone

import numpy as np

from predictor.satellite import (
    BrightnessTempField,
    himawari_keys,
    himawari_urls,
    nearest_slot,
)


def test_nearest_slot_floors_to_ten_minute_cadence():
    slot = nearest_slot(datetime(2026, 6, 22, 11, 7, 30, tzinfo=timezone.utc))
    assert slot == datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)


def test_nearest_slot_keeps_exact_slot_and_assumes_utc():
    # Naive input is treated as UTC; an exact 10-min boundary is unchanged.
    slot = nearest_slot(datetime(2026, 6, 22, 11, 20))
    assert slot == datetime(2026, 6, 22, 11, 20, tzinfo=timezone.utc)


def test_himawari_keys_match_spike_verified_format():
    slot = datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)
    keys = himawari_keys(slot, band="B13")
    assert len(keys) == 10
    # First and fifth segment exactly as listed in the #14 spike.
    assert keys[0] == (
        "AHI-L1b-FLDK/2026/06/22/1100/"
        "HS_H09_20260622_1100_B13_FLDK_R20_S0110.DAT.bz2"
    )
    assert keys[4] == (
        "AHI-L1b-FLDK/2026/06/22/1100/"
        "HS_H09_20260622_1100_B13_FLDK_R20_S0510.DAT.bz2"
    )
    assert keys[-1].endswith("S1010.DAT.bz2")


def test_himawari_urls_are_anonymous_https_on_the_public_bucket():
    slot = datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)
    urls = himawari_urls(slot, band="B13")
    assert urls[0] == (
        "https://noaa-himawari9.s3.amazonaws.com/AHI-L1b-FLDK/2026/06/22/1100/"
        "HS_H09_20260622_1100_B13_FLDK_R20_S0110.DAT.bz2"
    )
    assert all(u.startswith("https://noaa-himawari9.s3.amazonaws.com/") for u in urls)


def _field() -> BrightnessTempField:
    lats = np.array([34.0, 33.0, 32.0, 31.0])   # descending, like the grid
    lons = np.array([118.0, 119.0, 120.0, 121.0])  # ascending
    bt = np.array([
        [240.0, 241.0, 242.0, 243.0],
        [250.0, 251.0, 252.0, 253.0],
        [260.0, 261.0, 262.0, 263.0],
        [np.nan, 271.0, 272.0, 273.0],
    ])
    return BrightnessTempField(
        lats=lats, lons=lons, brightness_temp_k=bt,
        observation_time=datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc),
        band="B13", source_label="himawari9@test",
        retrieved_at=datetime(2026, 6, 22, 11, 5, tzinfo=timezone.utc),
    )


def test_sample_returns_nearest_pixel_brightness_temperature():
    f = _field()
    # Nearest to (32.1, 119.9) is row=32.0, col=120.0 → 262.0 K.
    assert f.sample(32.1, 119.9) == 262.0


def test_sample_returns_nan_when_nearest_pixel_is_masked():
    f = _field()
    # Nearest to (31.0, 118.0) is the NaN corner pixel.
    assert np.isnan(f.sample(31.0, 118.0))
