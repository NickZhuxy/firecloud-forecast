from datetime import datetime, timezone
import pytest
from predictor.features import Features


@pytest.fixture
def base_features() -> Features:
    """A neutral Features instance individual tests can mutate via dataclasses.replace."""
    return Features(
        cloud_low_pct=10.0,
        cloud_mid_pct=50.0,
        cloud_high_pct=40.0,
        humidity_pct=60.0,
        sunset_time=datetime(2026, 5, 20, 23, 30, tzinfo=timezone.utc),  # ~19:30 EDT
        query_time=datetime(2026, 5, 20, 23, 20, tzinfo=timezone.utc),
        location=(42.36, -71.06),  # Boston
    )
