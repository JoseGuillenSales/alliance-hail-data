"""Turning a day's grid of values (radar hail sizes, wind gusts) into band shapes, and per-city sizes."""

import math
from dataclasses import dataclass

import numpy as np
import shapely
from rasterio import features
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from . import config
from .grid import centres

# The values along the state line are carried a few squares past it before the shapes
# are rounded, so rounding never pulls a path back from the line; the shapes are then
# trimmed to Colorado.
PAD = 3
COLORADO = box(config.WEST, config.SOUTH, config.EAST, config.NORTH)


@dataclass(frozen=True)
class Shaping:
    """How a grid becomes band shapes. The grid's top-left corner is Colorado's north-west corner."""

    bands: tuple[float, ...]
    step: float  # grid square size, degrees
    upsample: int
    simplify: float
    smooth_passes: int
    curve_tolerance: float
    min_area_km2: float

    @property
    def fine_transform(self):
        fine = self.step / self.upsample
        return from_origin(config.WEST - PAD * self.step, config.NORTH + PAD * self.step, fine, fine)


HAIL = Shaping(
    bands=tuple(config.BANDS),
    step=config.GRID_STEP,
    upsample=config.UPSAMPLE,
    simplify=config.SIMPLIFY_DEGREES,
    smooth_passes=config.SMOOTH_PASSES,
    curve_tolerance=config.CURVE_TOLERANCE,
    min_area_km2=config.MIN_AREA_KM2,
)
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


def _drop_specks(geom, min_km2: float):
    """Remove spots and holes smaller than min_km2."""
    keep = []
    for p in _parts(geom):
        if _km2(p) < min_km2:
            continue
        holes = [h for h in p.interiors if _km2(Polygon(h)) >= min_km2]
        keep.append(Polygon(p.exterior, holes))
    return shapely.union_all(keep) if keep else Polygon()


def _round_coords(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(v, config.COORD_DECIMALS) for v in obj]
        return [_round_coords(v) for v in obj]
    return obj


def _blend(inches: np.ndarray, k: int) -> np.ndarray:
    """Split each square k x k and blend between square centres (bilinear).

    A radar square's size belongs to its centre. Blending puts a band's edge part way
    between a square over the size and its neighbour under it, instead of along the
    square's straight side, which gives a better estimate of where the edge is.
    """
    a = np.clip(inches, 0, None)

    def weights(n):
        x = np.clip((np.arange(n * k) + 0.5) / k - 0.5, 0, n - 1)
        i0 = np.minimum(np.floor(x).astype(int), n - 2) if n > 1 else np.zeros(n * k, int)
        return i0, x - i0

    r0, fr = weights(a.shape[0])
    c0, fc = weights(a.shape[1])
    top = a[r0][:, c0] * (1 - fc) + a[r0][:, c0 + 1] * fc
    bottom = a[r0 + 1][:, c0] * (1 - fc) + a[r0 + 1][:, c0 + 1] * fc
    return top * (1 - fr)[:, None] + bottom * fr[:, None]


def _chaikin(ring, passes: int) -> list:
    """Round a closed ring's corners (Chaikin's method: cut each corner a quarter in)."""
    pts = np.asarray(ring.coords)[:-1]
    for _ in range(passes):
        nxt = np.roll(pts, -1, axis=0)
        pts = np.column_stack([0.75 * pts + 0.25 * nxt, 0.25 * pts + 0.75 * nxt]).reshape(-1, 2)
    return pts.tolist()


def _round_corners(geom, s: Shaping):
    out = []
    for p in _parts(geom):
        holes = [_chaikin(h, s.smooth_passes) for h in p.interiors]
        p = Polygon(_chaikin(p.exterior, s.smooth_passes), holes)
        out.append(shapely.make_valid(p.simplify(s.curve_tolerance, preserve_topology=True)))
    return shapely.union_all(out) if out else Polygon()


def band_shapes(values: np.ndarray, s: Shaping = HAIL) -> list[tuple[float, object]]:
    """One shape per band that has any area: [(lower edge, geometry)].

    Each band's shape covers everything at or above its lower edge and sits inside the
    band below it, so drawing them in order stacks them neatly.
    """
    out = []
    below = COLORADO
    grid_size = 10**-config.COORD_DECIMALS
    if not (values >= s.bands[0]).any():
        return out
    fine = _blend(np.pad(values, PAD, mode="edge"), s.upsample)
    transform = s.fine_transform
    for lo in s.bands:
        mask = fine >= lo
        if not mask.any():
            break
        cells = [shape(g) for g, _ in features.shapes(mask.astype(np.uint8), mask=mask, transform=transform)]
        geom = shapely.union_all(cells)
        geom = geom.simplify(s.simplify, preserve_topology=True)
        geom = _drop_specks(geom, s.min_area_km2)
        geom = _round_corners(geom, s)
        if geom.is_empty:
            break
        geom = shapely.make_valid(geom.intersection(below))
        geom = shapely.set_precision(geom, grid_size)
        geom = _drop_specks(geom, s.min_area_km2)
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


def feature(lo: float, geom, properties: dict | None = None) -> dict:
    """A GeoJSON feature for one band; hail size properties unless others are given."""
    g = mapping(geom if isinstance(geom, MultiPolygon) else MultiPolygon(_parts(geom)))
    return {
        "type": "Feature",
        "properties": properties if properties is not None else band_label(lo),
        "geometry": {"type": "MultiPolygon", "coordinates": _round_coords(g["coordinates"])},
    }


def bbox(shapes: list[tuple[float, object]]) -> list[float] | None:
    if not shapes:
        return None
    w, s, e, n = shapes[0][1].bounds  # the lowest band holds all the others
    d = config.COORD_DECIMALS
    return [round(w, d), round(s, d), round(e, d), round(n, d)]


def city_sizes(inches: np.ndarray, grid_centres=None, minimum: float = config.MIN_INCHES, digits: int = 2) -> dict[str, float]:
    """Biggest value within CITY_RADIUS_MILES of each city, for cities at `minimum` or more.

    grid_centres: (row latitudes, column longitudes); the radar grid's when not given.
    """
    lats, lons = grid_centres or centres()
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
        if biggest >= minimum:
            out[slug] = round(biggest, digits) if digits else int(round(biggest))
    return out
