import math

from predictor.spatial import destination_point, sunward_coordinates


def test_destination_point_zero_distance_is_observer():
    assert destination_point(31.23, 121.47, 285.0, 0.0) == (31.23, 121.47)


def test_destination_point_due_north_moves_about_nine_degrees_at_1000km():
    lat, lon = destination_point(0.0, 120.0, 0.0, 1000.0)
    assert math.isclose(lat, 8.993, abs_tol=0.01)
    assert math.isclose(lon, 120.0, abs_tol=0.01)


def test_sunward_coordinates_preserve_distance_order():
    coords = sunward_coordinates(31.23, 121.47, 270.0, [0.0, 100.0, 800.0])
    assert len(coords) == 3
    assert coords[0] == (31.23, 121.47)
    assert coords[1][1] > coords[2][1]
