"""How long radar showed hail, and when it first showed, for each Colorado hail day.

    python -m engine.duration day 2026-06-01 [more dates]   these hail days
    python -m engine.duration daily                         recent hail days, plus history

For each hail day (status "hail" in the hail index.json), every 2-minute NOAA MRMS MESH
snapshot of the Colorado day is read. At each radar square:
- minutes: how many snapshots showed DURATION_MIN_INCHES or more, times 2 minutes;
- first / last: when the first and the last such snapshot came.
The minutes become shapes like the hail paths (duration bands, stacked like the size
bands), for the map. Every square with hail also goes into a small list ("cells") with
its first time, last time and minutes, for looking up one house. Radar sees hail in the
cloud every 2 minutes, so these are radar estimates, never ground measurements.

Output (next to the hail data, in duration/):
    duration/index.json        one entry per processed hail day
    duration/days/DATE.json    the day's duration shapes and per-square times
"""

import argparse
import concurrent.futures as cf
import json
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import config, grid, paths
from . import days as D
from .run import _dump, _write, load_index

STEP = timedelta(minutes=config.DURATION_STEP_MINUTES)
NONE = np.int16(-1)


def _shaping(bands) -> paths.Shaping:
    return paths.Shaping(
        bands=tuple(float(b) for b in bands),
        step=config.GRID_STEP,
        upsample=config.UPSAMPLE,
        simplify=config.SIMPLIFY_DEGREES,
        smooth_passes=config.SMOOTH_PASSES,
        curve_tolerance=config.CURVE_TOLERANCE,
        min_area_km2=config.MIN_AREA_KM2,
    )


DURATION = _shaping(config.DURATION_BANDS)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- radar for one day


def snapshot_times(day: date) -> list[datetime]:
    """Every 2-minute snapshot of the Colorado day (local midnight to midnight)."""
    t, end, out = D.day_start_utc(day), D.day_end_utc(day), []
    while t < end:
        out.append(t)
        t += STEP
    return out


def _download(t: datetime) -> bytes | None:
    try:
        return grid.download(D.file_urls(t, config.SNAPSHOT_PRODUCT))
    except grid.NotFound:
        return None


def hits(mm: np.ndarray) -> np.ndarray:
    """Squares where a snapshot shows DURATION_MIN_INCHES or more."""
    return grid.to_inches(mm) >= config.DURATION_MIN_INCHES


def day_grids(day: date) -> dict:
    """Snapshot counts and first/last snapshot index per square, plus what was found.

    Downloads run in threads; each file is decoded right away and then dropped, so only
    a few whole-U.S. grids are ever in memory.
    """
    times = snapshot_times(day)
    count = np.zeros((grid.ROWS, grid.COLS), np.int16)
    first = np.full((grid.ROWS, grid.COLS), np.int16(32767))
    last = np.full((grid.ROWS, grid.COLS), NONE)
    any_hit: list[int] = []
    found = 0
    with cf.ThreadPoolExecutor(max_workers=config.DURATION_DOWNLOAD_THREADS) as pool:
        futures = {pool.submit(_download, t): i for i, t in enumerate(times)}
        for fut in cf.as_completed(futures):
            i = futures[fut]
            gz = fut.result()
            if gz is None:
                continue
            found += 1
            h = hits(grid.colorado_mm(gz))
            if h.any():
                any_hit.append(i)
                count += h
                np.minimum(first, np.where(h, np.int16(i), first), out=first)
                np.maximum(last, np.where(h, np.int16(i), last), out=last)
    first[first == 32767] = NONE
    return {"times": times, "count": count, "first": first, "last": last, "found": found, "any": sorted(any_hit)}


# ---------------------------------------------------------------- one day


def _cell_bbox(rows: np.ndarray, cols: np.ndarray) -> list[float]:
    """[west, south, east, north] around the squares, when there are no shapes."""
    s, d = config.GRID_STEP, config.COORD_DECIMALS
    return [round(config.WEST + cols.min() * s, d), round(config.NORTH - (rows.max() + 1) * s, d), round(config.WEST + (cols.max() + 1) * s, d), round(config.NORTH - rows.min() * s, d)]


def band_label(lo: float) -> dict:
    i = config.DURATION_BANDS.index(int(lo))
    hi = config.DURATION_BANDS[i + 1] if i + 1 < len(config.DURATION_BANDS) else None
    return {"minMinutes": int(lo), "maxMinutes": hi}


def build_day(day: date, g: dict) -> dict:
    """The index entry and file for one day, from day_grids()."""
    iso = day.isoformat()
    times, found, total = g["times"], g["found"], len(g["times"])
    if total - found > config.DURATION_MAX_MISSING_SNAPSHOTS:
        return {"entry": {"date": iso, "status": "missing", "reason": f"2-minute radar files found for {found} of {total}"}}

    minutes = g["count"].astype(np.float32) * config.DURATION_STEP_MINUTES
    shapes = paths.band_shapes(minutes, DURATION)
    entry: dict = {"date": iso, "status": "duration" if g["any"] else "none", "maxMinutes": int(minutes.max())}
    if found < total:
        entry["snapshots"] = found
        entry["note"] = f"2-minute radar files were found for {found} of the day's {total}."
    doc = None
    if g["any"]:
        first_t, last_t = times[g["any"][0]], times[g["any"][-1]]
        entry["first"], entry["last"] = _iso(first_t), _iso(last_t)
        entry["file"] = f"days/{iso}.json"  # next to duration/index.json
        step = config.DURATION_STEP_MINUTES
        rows, cols = np.nonzero(g["count"])
        entry["bbox"] = paths.bbox(shapes) or _cell_bbox(rows, cols)
        cells = [[int(r), int(c), int(g["first"][r, c]) * step, int(g["last"][r, c]) * step, int(g["count"][r, c]) * step] for r, c in zip(rows, cols)]
        doc = {
            "type": "HailDuration",
            "version": config.DURATION_DATA_VERSION,
            "date": iso,
            "units": "minutes",
            "stepMinutes": config.DURATION_STEP_MINUTES,
            "minInches": config.DURATION_MIN_INCHES,
            "maxMinutes": entry["maxMinutes"],
            "first": entry["first"],
            "last": entry["last"],
            "bbox": entry["bbox"],
            "snapshots": {"found": found, "expected": total},
            "source": {"product": config.SNAPSHOT_PRODUCT, "everyMinutes": config.DURATION_STEP_MINUTES},
            "duration": {"type": "FeatureCollection", "features": [paths.feature(lo, geom, band_label(lo)) for lo, geom in shapes]},
            # One radar square = one row: [row, col, first, last, minutes]. first/last are
            # minutes after "start" (local midnight, in UTC); row 0 is the north edge.
            "cells": {
                "start": _iso(times[0]),
                "west": config.WEST,
                "north": config.NORTH,
                "step": config.GRID_STEP,
                "columns": ["row", "col", "first", "last", "minutes"],
                "rows": cells,
            },
        }
    cities = paths.city_sizes(minutes, minimum=config.DURATION_BANDS[0], digits=0)
    if cities:
        entry["cities"] = cities
    return {"entry": entry, "doc": doc}


def process_day(day: date) -> dict:
    try:
        return build_day(day, day_grids(day))
    except Exception as e:  # one bad day never stops the others
        return {"entry": {"date": day.isoformat(), "status": "missing", "reason": "Could not be processed"}, "error": f"{e}\n{traceback.format_exc()}"}


# ---------------------------------------------------------------- files


def write_index(out: Path, entries: dict[str, dict]) -> None:
    head = {
        "version": config.DURATION_DATA_VERSION,
        "units": "minutes",
        "timezone": config.TIMEZONE,
        "bands": config.DURATION_BANDS,
        "stepMinutes": config.DURATION_STEP_MINUTES,
        "minInches": config.DURATION_MIN_INCHES,
        "cityRadiusMiles": config.CITY_RADIUS_MILES,
        "source": "NOAA MRMS MESH 2-minute snapshots: minutes radar showed hail of 1 inch or more at each spot, and when it first and last did",
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


# ---------------------------------------------------------------- running


def run(day_list: list[date], out: Path, workers: int, mode: str, budget_minutes: float | None = None) -> int:
    """Process the days in order; with a budget, stop starting new days once it's used up."""
    print(f"Processing {len(day_list)} hail day(s) into {out}", flush=True)
    started = time.monotonic()
    results, errors, batch, skipped = [], 0, [], 0
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {}
        todo = list(day_list)
        while todo or pending:
            over = budget_minutes is not None and (time.monotonic() - started) / 60 > budget_minutes
            while todo and len(pending) < workers and not over:
                d = todo.pop(0)
                pending[pool.submit(process_day, d)] = d
            if over and todo:
                skipped += len(todo)
                todo = []
            if not pending:
                break
            done, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                pending.pop(fut)
                r = fut.result()
                e = r["entry"]
                extra = f"max {e['maxMinutes']} min" if "maxMinutes" in e else e.get("reason", "")
                print(f"{e['date']}  {e['status']:<8}  {extra}", flush=True)
                if r.get("error"):
                    errors += 1
                    print(r["error"], file=sys.stderr, flush=True)
                results.append(r)
                batch.append(r)
                if len(batch) >= 10:  # save as we go, so a crash keeps what's done
                    save(out, batch)
                    batch = []
    if batch:
        save(out, batch)
    status = {
        "lastRun": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "checked": sorted(r["entry"]["date"] for r in results),
        "missing": sorted(r["entry"]["date"] for r in results if r["entry"]["status"] == "missing"),
        "leftForNextRun": skipped,
        "errors": errors,
    }
    _write(out / "status.json", json.dumps(status, indent=1) + "\n")
    print(f"Done: {len(results)} day(s), {len(status['missing'])} missing, {errors} error(s), {skipped} left for the next run", flush=True)
    return 1 if errors else 0


def hail_days(hail_index: Path) -> list[date]:
    """Days the hail data marks as hail days (1-inch radar hail somewhere in Colorado)."""
    if not hail_index.exists():
        return []
    days = json.loads(hail_index.read_text(encoding="utf-8"))["days"]
    return sorted(date.fromisoformat(e["date"]) for e in days if e.get("status") == "hail")


def daily_days(out: Path, hail_index: Path, today: date) -> list[date]:
    """Recent hail days first (they may have changed), then missing ones, then history newest first."""
    hail = hail_days(hail_index)
    done = load_index(out)
    recent_from = today - timedelta(days=config.RECHECK_DAYS)
    retry_from = today - timedelta(days=config.RETRY_MISSING_DAYS)
    recent = [d for d in hail if d >= recent_from]
    retry = [d for d in hail if d >= retry_from and done.get(d.isoformat(), {}).get("status") == "missing"]
    history = [d for d in reversed(hail) if d >= config.DURATION_HISTORY_START and d.isoformat() not in done]
    out_list: list[date] = []
    for d in recent[::-1] + retry[::-1] + history:
        if d not in out_list:
            out_list.append(d)
    return out_list


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.duration")
    ap.add_argument("--out", default="data/duration", help="output folder (default: data/duration)")
    ap.add_argument("--hail-index", default="data/index.json", help="the hail index.json listing hail days")
    ap.add_argument("--workers", type=int, default=4)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("day")
    p.add_argument("dates", nargs="+", type=date.fromisoformat)
    p = sub.add_parser("daily")
    p.add_argument("--today", type=date.fromisoformat, help="pretend today is this Colorado date")
    p.add_argument("--budget", type=float, default=config.DURATION_TIME_BUDGET_MINUTES, help="minutes before no new days are started")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.cmd == "day":
        return run(sorted(set(a.dates)), out, a.workers, "day")
    todo = daily_days(out, Path(a.hail_index), a.today or D.colorado_today())
    if not todo:
        print("Nothing to process", flush=True)
    return run(todo, out, a.workers, "daily", a.budget)


if __name__ == "__main__":
    sys.exit(main())
