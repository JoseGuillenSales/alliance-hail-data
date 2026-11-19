"""Reading a radar file and cutting out Colorado.

The files are GRIB2: one value per 0.01-degree square for the whole U.S., in millimetres.
-1 means "no hail", -3 means "no radar coverage" (outside the U.S.).
"""

import gzip
import time
import urllib.error
import urllib.request

import eccodes
import numpy as np

from . import config

STEP = config.GRID_STEP

# Rows and columns of the U.S. grid whose squares lie inside the Colorado box.
ROW0 = round((config.GRID_FIRST_LAT - (config.NORTH - STEP / 2)) / STEP)
ROW1 = round((config.GRID_FIRST_LAT - (config.SOUTH + STEP / 2)) / STEP)
COL0 = round(((config.WEST + STEP / 2) - config.GRID_FIRST_LON) / STEP)
COL1 = round(((config.EAST - STEP / 2) - config.GRID_FIRST_LON) / STEP)
ROWS = ROW1 - ROW0 + 1
COLS = COL1 - COL0 + 1

NO_COVERAGE = -3.0


class NotFound(Exception):
    """The radar file isn't there (yet)."""


def download(urls: list[str], tries: int = 3) -> bytes:
    """The first URL that has the file. Raises NotFound when none do."""
    last: Exception | None = None
    for url in urls:
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as res:
                    return res.read()
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    break  # not on this server; try the next one
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            time.sleep(2 * (attempt + 1))
    raise NotFound(f"not found ({last})")


def _check(h, key: str, want: float) -> None:
    got = eccodes.codes_get(h, key)
    if abs(float(got) - want) > 1e-3:
        raise ValueError(f"The radar grid changed ({key} is {got}, expected {want}); the engine needs updating")


def colorado_mm(gz: bytes) -> np.ndarray:
    """Colorado's part of a radar file, in millimetres (row 0 = north, column 0 = west)."""
    h = eccodes.codes_new_from_message(gzip.decompress(gz))
    try:
        _check(h, "Ni", config.GRID_NI)
        _check(h, "Nj", config.GRID_NJ)
        _check(h, "latitudeOfFirstGridPointInDegrees", config.GRID_FIRST_LAT)
        _check(h, "longitudeOfFirstGridPointInDegrees", config.GRID_FIRST_LON % 360)
        _check(h, "iDirectionIncrementInDegrees", STEP)
        _check(h, "jDirectionIncrementInDegrees", STEP)
        _check(h, "jScansPositively", 0)
        values = eccodes.codes_get_values(h)
    finally:
        eccodes.codes_release(h)
    mm = values.reshape(config.GRID_NJ, config.GRID_NI)[ROW0 : ROW1 + 1, COL0 : COL1 + 1].copy()
    mm[mm >= 9999] = NO_COVERAGE  # the file's own "missing" marker, if it ever has one
    return mm


def to_inches(mm: np.ndarray) -> np.ndarray:
    """Hail size in inches; 0 where there was no hail or no coverage."""
    return np.where(mm > 0, mm / 25.4, 0.0)


def coverage(mm: np.ndarray) -> float:
    """Share of Colorado the radar covered."""
    return float((mm != NO_COVERAGE).mean())


def centres() -> tuple[np.ndarray, np.ndarray]:
    """Latitude of each row and longitude of each column (square centres)."""
    lats = config.NORTH - STEP / 2 - np.arange(ROWS) * STEP
    lons = config.WEST + STEP / 2 + np.arange(COLS) * STEP
    return lats, lons
