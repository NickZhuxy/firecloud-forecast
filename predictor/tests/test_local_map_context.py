"""Offline regional geography selection for a local New York map."""
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from predictor.local_map_context import load_local_map_context


def _record(geometry, **attributes):
    return SimpleNamespace(geometry=geometry, attributes=attributes)


def test_local_context_selects_us_land_and_intersecting_states(monkeypatch):
    import cartopy.io.shapereader as shpreader

    us = box(-80, 35, -70, 45)
    canada = box(-80, 43, -70, 50)
    new_york = box(-75, 40, -73, 45)
    new_jersey = box(-75.5, 39, -73.5, 41)
    california = box(-125, 32, -114, 42)
    countries = [
        _record(us, ADM0_A3="USA"), _record(canada, ADM0_A3="CAN"),
        _record(box(100, 20, 130, 40), ADM0_A3="CHN"),
    ]
    states = [
        _record(new_york, adm0_a3="USA"), _record(new_jersey, adm0_a3="USA"),
        _record(california, adm0_a3="USA"), _record(canada, adm0_a3="CAN"),
    ]
    monkeypatch.setattr(shpreader, "natural_earth", lambda **kwargs: kwargs["name"])
    monkeypatch.setattr(shpreader, "Reader", lambda path: SimpleNamespace(
        records=lambda: iter(countries if path == "admin_0_countries" else states),
    ))

    context = load_local_map_context("USA", (40, 44, -75, -73))
    assert context.country.equals(us)
    assert len(context.surrounding) == 1 and context.surrounding[0].equals(canada)
    assert len(context.admin1) == 2
    assert any(line.equals(new_york.boundary) for line in context.admin1)
    assert any(line.equals(new_jersey.boundary) for line in context.admin1)


def test_local_context_rejects_absent_country_instead_of_using_china(monkeypatch):
    import cartopy.io.shapereader as shpreader

    monkeypatch.setattr(shpreader, "natural_earth", lambda **kwargs: kwargs["name"])
    monkeypatch.setattr(shpreader, "Reader", lambda path: SimpleNamespace(records=lambda: iter([
        _record(box(100, 20, 130, 40), ADM0_A3="CHN"),
    ])))
    with pytest.raises(ValueError, match="USA geography not found"):
        load_local_map_context("USA", (40, 41, -75, -73))
