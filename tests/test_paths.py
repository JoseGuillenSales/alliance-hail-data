import json

import numpy as np
from shapely.geometry import Point, shape

from engine import config, grid, paths

STEP = config.GRID_STEP


def blank():
    return np.zeros((grid.ROWS, grid.COLS))


def cell(lat, lng):
    """Row and column of the square holding this point."""
    return int((config.NORTH - lat) / STEP), int((lng - config.WEST) / STEP)


def fill(a, lat0, lat1, lng0, lng1, inches):
    r0, c0 = cell(lat1, lng0)
    r1, c1 = cell(lat0, lng1)
    a[r0 : r1 + 1, c0 : c1 + 1] = inches


def storm():
    """A made-up storm east of Denver: a 1.2" swath with a 1.7" middle and a 2.6" core."""
    a = blank()
    fill(a, 39.60, 39.80, -104.20, -103.20, 1.2)
    fill(a, 39.65, 39.75, -104.00, -103.40, 1.7)
    fill(a, 39.68, 39.72, -103.80, -103.60, 2.6)
    return a


def test_colorado_grid_is_the_website_box():
    assert (grid.ROWS, grid.COLS) == (401, 702)
    lats, lons = grid.centres()
    assert abs(lats[0] - 40.995) < 1e-9 and abs(lats[-1] - 36.995) < 1e-9
    assert abs(lons[0] + 109.055) < 1e-9 and abs(lons[-1] + 102.045) < 1e-9


def test_millimetres_to_inches_and_no_hail_codes():
    mm = np.array([[-3.0, -1.0, 0.0, 25.4, 50.8]])
    assert grid.to_inches(mm).tolist() == [[0, 0, 0, 1.0, 2.0]]
    assert grid.coverage(mm) == 0.8


def test_bands_stack_inside_each_other():
    shapes = paths.band_shapes(storm())
    assert [lo for lo, _ in shapes] == [1.0, 1.5, 2.0, 2.5]
    for (_, lower), (_, upper) in zip(shapes, shapes[1:]):
        assert lower.buffer(1e-9).contains(upper)
    # The core is in every band; a spot in the outer swath only in the first
    core, edge = Point(-103.7, 39.70), Point(-104.1, 39.62)
    assert [g.contains(core) for _, g in shapes] == [True, True, True, True]
    assert [g.contains(edge) for _, g in shapes] == [True, False, False, False]


def test_hail_under_one_inch_is_ignored():
    a = blank()
    fill(a, 39.0, 39.5, -104.5, -104.0, 0.99)
    assert paths.band_shapes(a) == []


def test_specks_are_dropped_but_real_paths_kept():
    a = storm()
    r, c = cell(38.5, -105.5)
    a[r, c] = 3.0  # one lone square: radar noise
    shapes = paths.band_shapes(a)
    assert not shapes[0][1].contains(Point(-105.495, 38.495))
    assert shapes[0][1].contains(Point(-103.7, 39.70))


def test_small_holes_are_filled():
    a = storm()
    r, c = cell(39.62, -104.1)
    a[r, c] = 0  # one dry square inside the swath
    outer = paths.band_shapes(a)[0][1]
    assert outer.contains(Point(-104.095, 39.615))


def test_paths_are_clipped_to_colorado():
    a = blank()
    a[:, -40:] = 1.4  # along the Kansas line
    a[:30, :] = 1.4  # along the Wyoming line
    g = paths.band_shapes(a)[0][1]
    w, s, e, n = g.bounds
    assert w >= config.WEST and e <= config.EAST and n <= config.NORTH and s >= config.SOUTH


def test_geojson_output():
    shapes = paths.band_shapes(storm())
    f = paths.feature(*shapes[1])
    assert f["properties"] == {"minInches": 1.5, "maxInches": 2.0}
    assert paths.feature(*shapes[-1])["properties"] == {"minInches": 2.5, "maxInches": None}
    assert f["geometry"]["type"] == "MultiPolygon"
    g = shape(f["geometry"])
    assert g.is_valid and not g.is_empty
    # Coordinates rounded to 3 decimals, outer rings counter-clockwise (GeoJSON rule)
    ring = f["geometry"]["coordinates"][0][0]
    assert all(len(str(v).split(".")[-1]) <= 3 for pt in ring for v in pt)
    from shapely.geometry import LinearRing

    assert LinearRing(ring).is_ccw
    assert paths.bbox(shapes) == [round(v, 3) for v in shapes[0][1].bounds]


def test_same_input_gives_the_same_output():
    one = json.dumps([paths.feature(lo, g) for lo, g in paths.band_shapes(storm())])
    two = json.dumps([paths.feature(lo, g) for lo, g in paths.band_shapes(storm())])
    assert one == two


def test_city_sizes():
    a = blank()
    r, c = cell(39.75, -104.35)  # about 1.5 miles from Strasburg's centre
    a[r - 1 : r + 2, c - 1 : c + 2] = 1.8
    r, c = cell(40.10, -104.80)  # about 7 miles east of Frederick: too far
    a[r - 1 : r + 2, c - 1 : c + 2] = 2.2
    assert paths.city_sizes(a) == {"strasburg": 1.8}
