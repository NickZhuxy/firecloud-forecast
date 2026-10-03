"""Explicit product coverage profiles; observer bounds do not clip weather paths."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastRegion:
    key: str
    name: str
    timezone_name: str
    country_code: str
    national_enabled: bool
    remote_enabled: bool
    satellite_enabled: bool
    local_product_name: str
    center_bbox: tuple[float, float, float, float] | None = None

    def validate_center(self, lat: float, lon: float) -> None:
        """Validate a signed observer coordinate before any source access."""
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError("latitude and longitude must be finite")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("latitude must be -90..90 and longitude must be -180..180")
        if self.center_bbox is not None:
            south, north, west, east = self.center_bbox
            if not (south <= lat <= north and west <= lon <= east):
                raise ValueError(
                    f"{self.name} pilot centers must be within "
                    f"{south}..{north} latitude and {west}..{east} longitude"
                )


_REGIONS = {
    "china": ForecastRegion(
        "china", "China", "Asia/Shanghai", "CHN", True, True, True,
        "china_firecloud_local",
    ),
    "us-nyc": ForecastRegion(
        "us-nyc", "New York City", "America/New_York", "USA", False, False, False,
        "us_nyc_firecloud_local", (40.0, 41.5, -75.0, -72.5),
    ),
}
REGION_KEYS = tuple(_REGIONS)


def get_region(key: str = "china") -> ForecastRegion:
    """Resolve a supported product profile, rather than infer it from coordinates."""
    try:
        return _REGIONS[key]
    except KeyError as exc:
        raise ValueError(f"unknown region {key!r}; choose from {', '.join(REGION_KEYS)}") from exc
