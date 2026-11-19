"""Processing Colorado days and keeping the index up to date.

    python -m engine day 2026-05-21 [more dates]   one or more days, season or not
    python -m engine range 2024-11-18 2026-11-17   storm-season days plus ground-report days
    python -m engine daily                         the last few finished days, plus retries

Running a day again gives the same files. A day whose radar file can't be found is
marked "missing" and tried again on later daily runs; nothing is ever filled in.
"""

import argparse
import concurrent.futures as cf
import csv
import io
import json
import os
import sys
import traceback
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import config, grid, paths
from . import days as D


# ---------------------------------------------------------------- radar for one day


def _snapshot_max(start: datetime, end: datetime) -> np.ndarray:
    """Biggest value in the 2-minute files from start up to (not including) end."""
    best, t = None, start
    while t < end:
        mm = grid.colorado_mm(grid.download(D.file_urls(t, config.SNAPSHOT_PRODUCT)))
        best = mm if best is None else np.maximum(best, mm)
        t += timedelta(minutes=2)
    return best


def day_radar(day: date) -> tuple[np.ndarray, str, str | None]:
    """Colorado's radar hail sizes (mm) for one local day, the file used, and a note."""
    end = D.day_end_utc(day)
    name = D.file_urls(end)[0].rsplit("/", 1)[1]
    mm = grid.colorado_mm(grid.download(D.file_urls(end)))
    note = None
    odd = D.odd_hour(day)
    if odd:
        kind, start, stop = odd
        hour = _snapshot_max(start, stop)
        if kind == "gap":
            mm = np.maximum(mm, hour)
            note = "Clock change: the day's first hour was added from the 2-minute radar files."
        elif (grid.to_inches(hour) >= config.MIN_INCHES).any():
            mm = _snapshot_max(D.day_start_utc(day), end)
            note = "Clock change: the day was built from the 2-minute radar files."
    return mm, name, note


def process_day(day: date) -> dict:
    """One day's index entry, plus its hail-path file when there is one ("doc")."""
    iso = day.isoformat()
    try:
        mm, source, note = day_radar(day)
    except grid.NotFound as e:
        return {"entry": {"date": iso, "status": "missing", "reason": "Radar file not found"}, "log": str(e)}
    except Exception as e:  # one bad day never stops the others
        return {"entry": {"date": iso, "status": "missing", "reason": "Could not be processed"}, "error": f"{e}\n{traceback.format_exc()}"}

    inches = grid.to_inches(mm)
    shapes = paths.band_shapes(inches)
    entry = {"date": iso, "status": "hail" if shapes else "none", "maxInches": round(float(inches.max()), 2)}
    doc = None
    if shapes:
        entry["file"] = f"days/{iso}.json"
        entry["bbox"] = paths.bbox(shapes)
        doc = {
            "type": "FeatureCollection",
            "version": config.DATA_VERSION,
            "date": iso,
            "units": "inches",
            "maxInches": entry["maxInches"],
            "bbox": entry["bbox"],
            "source": {"product": config.DAY_PRODUCT, "file": source},
            "features": [paths.feature(lo, g) for lo, g in shapes],
        }
    cities = paths.city_sizes(inches)
    if cities:
        entry["cities"] = cities
    cov = grid.coverage(mm)
    if cov < 0.99:
        entry["coverage"] = round(cov, 2)
    if note:
        entry["note"] = note
    return {"entry": entry, "doc": doc}


# ---------------------------------------------------------------- ground reports


def report_days(first: date, last: date) -> set[date]:
    """Colorado dates with at least one ground hail report (any size)."""
    found: set[date] = set()
    start = first
    while start <= last:
        stop = min(start + timedelta(days=180), last)
        params = {
            "state": "CO",
            "sts": D.day_start_utc(start).strftime("%Y-%m-%dT%H:%MZ"),
            "ets": D.day_end_utc(stop).strftime("%Y-%m-%dT%H:%MZ"),
            "fmt": "csv",
        }
        url = config.LSR_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=90) as res:
            text = res.read().decode("utf-8", "replace")
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("TYPETEXT") == "HAIL" and row.get("VALID"):
                t = datetime.strptime(row["VALID"], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                found.add(D.colorado_date(t))
        start = stop + timedelta(days=1)
    return {d for d in found if first <= d <= last}


def storm_days(first: date, last: date) -> list[date]:
    picked = set(D.season_days(first, last))
    try:
        picked |= report_days(first, last)
    except Exception as e:
        print(f"Warning: ground reports could not be checked ({e}); only storm-season days are processed", flush=True)
    return sorted(picked)


# ---------------------------------------------------------------- files


def _dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def load_index(out: Path) -> dict[str, dict]:
    p = out / "index.json"
    if not p.exists():
        return {}
    return {e["date"]: e for e in json.loads(p.read_text(encoding="utf-8"))["days"]}


def write_index(out: Path, entries: dict[str, dict]) -> None:
    head = {
        "version": config.DATA_VERSION,
        "units": "inches",
        "timezone": config.TIMEZONE,
        "bands": config.BANDS,
        "minInches": config.MIN_INCHES,
        "cityRadiusMiles": config.CITY_RADIUS_MILES,
        "source": "NOAA MRMS MESH (Maximum Estimated Size of Hail), 24-hour maximum ending at local midnight",
    }
    days = sorted(entries.values(), key=lambda e: e["date"])
    # One day per line, so changes are easy to see
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


def run(day_list: list[date], out: Path, workers: int, mode: str) -> int:
    print(f"Processing {len(day_list)} day(s) into {out}", flush=True)
    results, errors, batch = [], 0, []
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(process_day, day_list):
            e = r["entry"]
            extra = f"max {e['maxInches']:.2f} in" if "maxInches" in e else e.get("reason", "")
            print(f"{e['date']}  {e['status']:<7}  {extra}", flush=True)
            if r.get("error"):
                errors += 1
                print(r["error"], file=sys.stderr, flush=True)
            results.append(r)
            batch.append(r)
            if len(batch) >= 20:  # save as we go, so a crash keeps what's done
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
    print(f"Done: {len(results)} day(s), {len(missing)} missing, {errors} error(s)", flush=True)
    return 1 if errors else 0


def daily_days(out: Path, today: date) -> list[date]:
    recent = [today - timedelta(days=n) for n in range(1, config.RECHECK_DAYS + 1)]
    picked = set(d for d in recent if D.in_season(d))
    try:
        picked |= report_days(recent[-1], recent[0])
    except Exception as e:
        print(f"Warning: ground reports could not be checked ({e})", flush=True)
    oldest = today - timedelta(days=config.RETRY_MISSING_DAYS)
    for e in load_index(out).values():
        d = date.fromisoformat(e["date"])
        if e["status"] == "missing" and d >= oldest:
            picked.add(d)
    return sorted(picked)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine")
    ap.add_argument("--out", default="data", help="output folder (default: data)")
    ap.add_argument("--workers", type=int, default=4)
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
        todo = storm_days(a.first, a.last)
    else:
        todo = daily_days(out, a.today or D.colorado_today())
    if not todo:
        print("Nothing to process", flush=True)
    return run(todo, out, a.workers, a.cmd)


if __name__ == "__main__":
    sys.exit(main())
