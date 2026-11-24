"""Wind paths: each Colorado day's strongest wind gust, and the wind reports.

    python -m engine.wind day 2025-12-17 [more dates]
    python -m engine.wind range 2024-11-18 2026-11-21     every day in the range
    python -m engine.wind daily                            the last few finished days, plus retries

The gusts come from NOAA's hourly wind analysis (URMA, the "un-restricted mesoscale
analysis"): a 2.5 km map of the gust at the top of every hour, made from weather
stations and a weather model. The day's file keeps the strongest of the day's hours.
Gusts between hours are not seen, so short thunderstorm gusts are often missed; the
Weather Service's wind reports (measured gusts and damage) are added for that reason.

Only the gust part of each hourly file is downloaded (about 5.6 MB of 86 MB). A day
with more than WIND_MAX_MISSING_HOURS hours missing is marked "missing" and tried
again later; nothing is ever filled in.
"""

import argparse
import concurrent.futures as cf
import csv
import io
import json
import math
import struct
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from . import config, paths
from . import days as D
from .run import _dump, _write, load_index

MPS_TO_MPH = 2.2369363
STEP = config.WIND_STEP
ROWS = math.ceil(round((config.NORTH - config.SOUTH) / STEP, 6))
COLS = math.ceil(round((config.EAST - config.WEST) / STEP, 6))
TRANSFORM = from_origin(config.WEST, config.NORTH, STEP, STEP)
GUST_MESSAGE = 10  # where the gust sits in files that have no index (checked when read)

WIND = paths.Shaping(
    bands=tuple(config.WIND_BANDS),
    step=STEP,
    upsample=config.WIND_UPSAMPLE,
    simplify=config.WIND_SIMPLIFY_DEGREES,
    smooth_passes=config.WIND_SMOOTH_PASSES,
    curve_tolerance=config.WIND_CURVE_TOLERANCE,
    min_area_km2=config.WIND_MIN_AREA_KM2,
)


class NotFound(Exception):
    """The hour's wind file isn't there (yet)."""


# ---------------------------------------------------------------- downloading


def _get(url: str, byte_range: tuple[int, int | str] | None = None, tries: int = 3) -> bytes:
    headers = {"User-Agent": config.USER_AGENT}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    last: Exception | None = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise NotFound(f"{url} ({e.code})") from e
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise NotFound(f"{url} ({last})")


def gust_range(url: str) -> tuple[int, int | str]:
    """Byte range of the gust inside an hourly file: from its index, or by reading GRIB headers."""
    try:
        lines = _get(url + ".idx").decode().splitlines()
    except NotFound:
        lines = []
    for i, line in enumerate(lines):
        if ":GUST:" in line:
            start = int(line.split(":")[1])
            end = int(lines[i + 1].split(":")[1]) - 1 if i + 1 < len(lines) else ""
            return start, end
    if lines:
        raise ValueError(f"no gust in {url}")
    # Older files have no index: each GRIB2 message starts with its own length
    offset = 0
    for n in range(1, GUST_MESSAGE + 1):
        head = _get(url, (offset, offset + 15))
        if head[:4] != b"GRIB" or len(head) < 16:
            raise ValueError(f"unexpected file layout in {url}")
        length = struct.unpack(">Q", head[8:16])[0]
        if n == GUST_MESSAGE:
            return offset, offset + length - 1
        offset += length
    raise ValueError(f"no gust in {url}")


def colorado_mph(message: bytes) -> np.ndarray:
    """One hour's gusts on the Colorado wind grid, in mph (NaN where there's no value)."""
    with MemoryFile(message, ext=".grb2") as mf, mf.open() as src:
        element = src.tags(1).get("GRIB_ELEMENT", "")
        if element != "GUST":
            raise ValueError(f"expected the gust, got {element!r}; the engine needs updating")
        out = np.full((ROWS, COLS), np.nan, dtype="float32")
        reproject(
            rasterio.band(src, 1),
            out,
            dst_transform=TRANSFORM,
            dst_crs="EPSG:4326",
            resampling=Resampling.bilinear,
            dst_nodata=np.nan,
        )
    return out * MPS_TO_MPH


def hours(day: date) -> list[datetime]:
    """The UTC hours of a Colorado day (23 or 25 on clock-change days)."""
    t, end, out = D.day_start_utc(day), D.day_end_utc(day), []
    while t < end:
        out.append(t)
        t += timedelta(hours=1)
    return out


def _hour(t: datetime) -> np.ndarray | None:
    url = config.WIND_URL.format(t=t)
    try:
        return colorado_mph(_get(url, gust_range(url)))
    except NotFound:
        return None


def day_gusts(day: date) -> tuple[np.ndarray | None, int, int]:
    """Strongest gust of the day per square (mph), hours found, hours in the day."""
    todo = hours(day)
    best, found = None, 0
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for mph in pool.map(_hour, todo):
            if mph is None:
                continue
            found += 1
            best = mph if best is None else np.fmax(best, mph)
    return best, found, len(todo)


def centres() -> tuple[np.ndarray, np.ndarray]:
    lats = config.NORTH - STEP / 2 - np.arange(ROWS) * STEP
    lons = config.WEST + STEP / 2 + np.arange(COLS) * STEP
    return lats, lons


# ---------------------------------------------------------------- reports


def fetch_reports(first: date, last: date) -> dict[str, list[dict]]:
    """Colorado wind reports by Colorado date: gusts of WIND_REPORT_MIN_MPH or more, and damage."""
    params = {
        "state": "CO",
        "sts": D.day_start_utc(first).strftime("%Y-%m-%dT%H:%MZ"),
        "ets": D.day_end_utc(last).strftime("%Y-%m-%dT%H:%MZ"),
        "fmt": "csv",
    }
    url = config.LSR_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    text = _get(url).decode("utf-8", "replace")
    out: dict[str, list[dict]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        kind = config.WIND_REPORT_TYPES.get(row.get("TYPETEXT", ""))
        if not kind or row.get("STATE") != "CO" or not row.get("VALID"):
            continue
        try:
            lat, lng = float(row["LAT"]), float(row["LON"])
        except (TypeError, ValueError):
            continue
        if not (config.SOUTH <= lat <= config.NORTH and config.WEST <= lng <= config.EAST):
            continue
        try:
            mph = round(float(row.get("MAG") or 0))
        except ValueError:
            mph = 0
        if kind == "gust" and mph < config.WIND_REPORT_MIN_MPH:
            continue
        t = datetime.strptime(row["VALID"], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        report = {
            "time": t.strftime("%Y-%m-%dT%H:%MZ"),
            "lat": round(lat, 3),
            "lng": round(lng, 3),
            "kind": kind,
            "thunderstorm": row["TYPETEXT"].startswith("TSTM"),
            "mph": mph or None,
            # M = measured by an instrument, E = estimated by a person
            "measured": row.get("QUALIFIER") == "M",
            "source": row.get("SOURCE") or None,
            "place": row.get("CITY") or None,
        }
        out.setdefault(D.colorado_date(t).isoformat(), []).append(report)
    for reps in out.values():
        reps.sort(key=lambda r: (r["time"], r["lat"], r["lng"]))
    return out


def reports_by_day(first: date, last: date) -> dict[str, list[dict]]:
    """Reports for a long range, fetched 90 days at a time."""
    out: dict[str, list[dict]] = {}
    start = first
    while start <= last:
        stop = min(start + timedelta(days=89), last)
        out.update(fetch_reports(start, stop))
        start = stop + timedelta(days=1)
    return out


# ---------------------------------------------------------------- one day


def _bbox(shapes, reports) -> list[float] | None:
    boxes = []
    if shapes:
        boxes.append(paths.bbox(shapes))
    for r in reports:
        boxes.append([r["lng"], r["lat"], r["lng"], r["lat"]])
    if not boxes:
        return None
    d = config.COORD_DECIMALS
    return [round(min(b[0] for b in boxes), d), round(min(b[1] for b in boxes), d), round(max(b[2] for b in boxes), d), round(max(b[3] for b in boxes), d)]


def band_label(lo: float) -> dict:
    i = config.WIND_BANDS.index(lo)
    hi = config.WIND_BANDS[i + 1] if i + 1 < len(config.WIND_BANDS) else None
    return {"minMph": int(lo), "maxMph": int(hi) if hi else None}


def process_day(day: date, reports: list[dict] | None) -> dict:
    """One day's index entry, plus its file when there's anything to show ("doc")."""
    iso = day.isoformat()
    try:
        gusts, found, total = day_gusts(day)
    except Exception as e:  # one bad day never stops the others
        return {"entry": {"date": iso, "status": "missing", "reason": "Could not be processed"}, "error": f"{e}\n{traceback.format_exc()}"}
    if gusts is None or total - found > config.WIND_MAX_MISSING_HOURS:
        return {"entry": {"date": iso, "status": "missing", "reason": f"Wind files found for {found} of {total} hours"}}

    mph = np.nan_to_num(gusts, nan=0.0)
    shapes = paths.band_shapes(mph, WIND)
    reports = reports or []
    strong = [r for r in reports if r["kind"] == "damage" or (r["mph"] or 0) >= 58]
    entry: dict = {"date": iso, "status": "wind" if shapes or strong else "none", "maxMph": int(round(float(mph.max())))}
    if found < total:
        entry["hours"] = found
        entry["note"] = f"Wind files were found for {found} of the day's {total} hours."
    if reports:
        entry["reports"] = len(reports)
        gusts_reported = [r["mph"] for r in reports if r["kind"] == "gust" and r["mph"]]
        if gusts_reported:
            entry["maxReportMph"] = max(gusts_reported)
    doc = None
    if entry["status"] == "wind":
        entry["file"] = f"days/{iso}.json"  # next to wind/index.json
        entry["bbox"] = _bbox(shapes, reports)
        doc = {
            "type": "FeatureCollection",
            "version": config.WIND_DATA_VERSION,
            "date": iso,
            "units": "mph",
            "maxMph": entry["maxMph"],
            "bbox": entry["bbox"],
            "source": {"product": "NOAA URMA 2.5 km wind gust analysis, strongest hour of the day", "hours": found},
            "features": [paths.feature(lo, g, band_label(lo)) for lo, g in shapes],
            "reports": reports,
        }
    cities = paths.city_sizes(mph, centres(), minimum=config.WIND_BANDS[0], digits=0)
    if cities:
        entry["cities"] = cities
    return {"entry": entry, "doc": doc}


# ---------------------------------------------------------------- files


def write_index(out: Path, entries: dict[str, dict]) -> None:
    head = {
        "version": config.WIND_DATA_VERSION,
        "units": "mph",
        "timezone": config.TIMEZONE,
        "bands": [int(b) for b in config.WIND_BANDS],
        "minMph": int(config.WIND_BANDS[0]),
        "cityRadiusMiles": config.CITY_RADIUS_MILES,
        "source": "NOAA URMA hourly wind gust analysis (strongest hour of each Colorado day), plus NWS Local Storm Reports of wind",
    }
    days = sorted(entries.values(), key=lambda e: e["date"])
    text = _dump(head)[:-1] + ',"days":[\n' + ",\n".join(_dump(e) for e in days) + "\n]}\n"
    _write(out / "index.json", text)


def save(out: Path, results: list[dict]) -> None:
    entries = load_index(out)
    for r in results:
        e = r["entry"]
        old = entries.get(e["date"])
        if e["status"] == "missing" and old and old["status"] != "missing":
            continue  # a failed re-check never replaces good data
        day_file = out / "days" / f"{e['date']}.json"
        if r.get("doc"):
            _write(day_file, _dump(r["doc"]) + "\n")
        elif e["status"] != "missing" and day_file.exists():
            day_file.unlink()
        entries[e["date"]] = e
    write_index(out, entries)


def _work(args):
    return process_day(*args)


def run(day_list: list[date], out: Path, workers: int, mode: str) -> int:
    print(f"Wind: processing {len(day_list)} day(s) into {out}", flush=True)
    try:
        reps = reports_by_day(day_list[0], day_list[-1]) if day_list else {}
    except Exception as e:
        # Without the reports a day would look calmer than it was, so stop instead
        print(f"Wind reports could not be loaded ({e}); nothing was changed", file=sys.stderr, flush=True)
        return 1
    results, errors, batch = [], 0, []
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(_work, [(d, reps.get(d.isoformat())) for d in day_list]):
            e = r["entry"]
            extra = f"max {e['maxMph']} mph" if "maxMph" in e else e.get("reason", "")
            if e.get("maxReportMph"):
                extra += f", reported {e['maxReportMph']} mph"
            print(f"{e['date']}  {e['status']:<7}  {extra}", flush=True)
            if r.get("error"):
                errors += 1
                print(r["error"], file=sys.stderr, flush=True)
            results.append(r)
            batch.append(r)
            if len(batch) >= 20:
                save(out, batch)
                batch = []
    if batch:
        save(out, batch)
    missing = [r["entry"]["date"] for r in results if r["entry"]["status"] == "missing"]
    status = {
        "lastRun": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "checked": [d.isoformat() for d in day_list],
        "missing": missing,
        "errors": errors,
    }
    _write(out / "status.json", json.dumps(status, indent=1) + "\n")
    print(f"Wind done: {len(results)} day(s), {len(missing)} missing, {errors} error(s)", flush=True)
    return 1 if errors else 0


def daily_days(out: Path, today: date) -> list[date]:
    picked = {today - timedelta(days=n) for n in range(1, config.RECHECK_DAYS + 1)}
    oldest = today - timedelta(days=config.RETRY_MISSING_DAYS)
    for e in load_index(out).values():
        d = date.fromisoformat(e["date"])
        if e["status"] == "missing" and d >= oldest:
            picked.add(d)
    return sorted(picked)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.wind")
    ap.add_argument("--out", default="data/wind", help="output folder (default: data/wind)")
    ap.add_argument("--workers", type=int, default=3)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("day")
    p.add_argument("dates", nargs="+", type=date.fromisoformat)
    p = sub.add_parser("range")
    p.add_argument("first", type=date.fromisoformat)
    p.add_argument("last", type=date.fromisoformat)
    p = sub.add_parser("daily")
    p.add_argument("--today", type=date.fromisoformat, help="pretend today is this Colorado date")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.cmd == "day":
        todo = sorted(set(a.dates))
    elif a.cmd == "range":
        todo = [a.first + timedelta(days=n) for n in range((a.last - a.first).days + 1)]
    else:
        todo = daily_days(out, a.today or D.colorado_today())
    if not todo:
        print("Nothing to process", flush=True)
        return 0
    return run(todo, out, a.workers, a.cmd)


if __name__ == "__main__":
    sys.exit(main())
