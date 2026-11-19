"""Turning a day's radar hail sizes into hail-path shapes and per-city sizes."""

import math

import numpy as np
import shapely
from rasterio import features
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from . import config
from .grid import centres

TRANSFORM = from_origin(config.WEST, config.NORTH, config.GRID_STEP, config.GRID_STEP)
COLORADO = box(config.WEST, config.SOUTH, config.EAST, config.NORTH)
KM_PER_DEGREE = 111.32


def _km2(geom) -> float:
    if geom.is_empty:
        return 0.0
    lat = geom.centroid.y
    return geom.area * KM_PER_DEGREE**2 * math.cos(math.radians(lat))


def _parts(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    # Multi-shapes and mixed collections; lines and points left by clipping are dropped
    return [p for g in getattr(geom, "geoms", []) for p in _parts(g)]


def _drop_specks(geom):
    """Remove spots and holes smaller than MIN_AREA_KM2."""
    keep = []
    for p in _parts(geom):
        if _km2(p) < config.MIN_AREA_KM2:
            continue
        holes = [h for h in p.interiors if _km2(Polygon(h)) >= config.MIN_AREA_KM2]
        keep.append(Polygon(p.exterior, holes))
    return shapely.union_all(keep) if keep else Polygon()


def _round_coords(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(v, config.COORD_DECIMALS) for v in obj]
        return [_round_coords(v) for v in obj]
    return obj


def band_shapes(inches: np.ndarray) -> list[tuple[float, object]]:
    """One shape per size band that has any area: [(lower edge in inches, geometry)].

    Each band's shape covers everything at or above its lower edge and sits inside the
    band below it, so drawing them in order stacks them neatly.
    """
    out = []
    below = COLORADO
    grid_size = 10**-config.COORD_DECIMALS
    for lo in config.BANDS:
        mask = inches >= lo
        if not mask.any():
            break
        cells = [shape(g) for g, _ in features.shapes(mask.astype(np.uint8), mask=mask, transform=TRANSFORM)]
        geom = shapely.union_all(cells)
        geom = geom.simplify(config.SIMPLIFY_DEGREES, preserve_topology=True)
        geom = _drop_specks(geom)
        if geom.is_empty:
            break
        geom = shapely.make_valid(geom.intersection(below))
        geom = shapely.set_precision(geom, grid_size)
        geom = _drop_specks(geom)
        if geom.is_empty:
            break
        geom = shapely.orient_polygons(shapely.normalize(geom), exterior_cw=False)
        out.append((lo, geom))
        below = geom
    return out


def band_label(lo: float) -> dict:
    i = config.BANDS.index(lo)
    hi = config.BANDS[i + 1] if i + 1 < len(config.BANDS) else None
    return {"minInches": lo, "maxInches": hi}


def feature(lo: float, geom) -> dict:
    g = mapping(geom if isinstance(geom, MultiPolygon) else MultiPolygon(_parts(geom)))
    return {
        "type": "Feature",
        "properties": band_label(lo),
        "geometry": {"type": "MultiPolygon", "coordinates": _round_coords(g["coordinates"])},
    }


def bbox(shapes: list[tuple[float, object]]) -> list[float] | None:
    if not shapes:
        return None
    w, s, e, n = shapes[0][1].bounds  # the lowest band holds all the others
    d = config.COORD_DECIMALS
    return [round(w, d), round(s, d), round(e, d), round(n, d)]


def city_sizes(inches: np.ndarray) -> dict[str, float]:
    """Biggest radar size within CITY_RADIUS_MILES of each city, for cities at MIN_INCHES or more."""
    lats, lons = centres()
    out = {}
    for slug, _name, lat, lng in config.CITIES:
        dlat = config.CITY_RADIUS_MILES / 69.0
        dlon = dlat / math.cos(math.radians(lat))
        rows = np.where(np.abs(lats - lat) <= dlat)[0]
        cols = np.where(np.abs(lons - lng) <= dlon)[0]
        if not len(rows) or not len(cols):
            continue
        window = inches[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
        la = lats[rows[0] : rows[-1] + 1, None]
        lo = lons[None, cols[0] : cols[-1] + 1]
        miles = 3958.8 * 2 * np.arcsin(
            np.sqrt(np.sin(np.radians(la - lat) / 2) ** 2 + np.cos(np.radians(lat)) * np.cos(np.radians(la)) * np.sin(np.radians(lo - lng) / 2) ** 2)
        )
        biggest = float(window[miles <= config.CITY_RADIUS_MILES].max(initial=0.0))
        if biggest >= config.MIN_INCHES:
            out[slug] = round(biggest, 2)
    return out
