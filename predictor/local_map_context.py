"""Natural Earth geography for a bounded local map; weather paths stay global."""
from __future__ import annotations

from predictor.national_product import MapContext


def _intersects(bounds, bbox) -> bool:
    west, south, east, north = bounds
    lat_min, lat_max, lon_min, lon_max = bbox
    return not (
        east < lon_min or west > lon_max or north < lat_min or south > lat_max
    )


def load_local_map_context(
    country_code: str, bbox: tuple[float, float, float, float]
) -> MapContext:
    """Load land and state outlines intersecting a (south, north, west, east) box."""
    import cartopy.io.shapereader as shpreader

    countries_path = shpreader.natural_earth(
        resolution="10m", category="cultural", name="admin_0_countries"
    )
    country = None
    surrounding = []
    for record in shpreader.Reader(countries_path).records():
        geometry = record.geometry
        if not _intersects(geometry.bounds, bbox):
            continue
        attributes = record.attributes
        code = attributes.get("ADM0_A3") or attributes.get("adm0_a3")
        if code == country_code:
            country = geometry
        else:
            surrounding.append(geometry)
    if country is None:
        raise ValueError(f"{country_code} geography not found for the local map")

    states_path = shpreader.natural_earth(
        resolution="10m", category="cultural", name="admin_1_states_provinces_lakes"
    )
    states = []
    for record in shpreader.Reader(states_path).records():
        attributes = record.attributes
        code = attributes.get("adm0_a3") or attributes.get("ADM0_A3")
        if code == country_code and _intersects(record.geometry.bounds, bbox):
            states.append(record.geometry.boundary)
    return MapContext(country=country, surrounding=tuple(surrounding), admin1=tuple(states))
