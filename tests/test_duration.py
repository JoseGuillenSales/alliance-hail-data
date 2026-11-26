import json
from datetime import date, timedelta

import numpy as np
from shapely.geometry import Point, shape

from engine import config, duration, grid


def cell(lat, lng):
    return int((config.NORTH - lat) / config.GRID_STEP), int((lng - config.WEST) / config.GRID_STEP)


def made_up_day(day=date(2026, 6, 1)):
    """A made-up storm crossing Frederick: 1-inch hail for 6 snapshots (12 min) in the core,
    2 snapshots (4 min) around it, starting at 1:00 pm MDT."""
    times = duration.snapshot_times(day)
    count = np.zeros((grid.ROWS, grid.COLS), np.int16)
    first = np.full((grid.ROWS, grid.COLS), duration.NONE)
    last = np.full((grid.ROWS, grid.COLS), duration.NONE)
    start = times.index(next(t for t in times if t.hour == 19 and t.minute == 0))  # 19:00 UTC = 1 pm MDT
    r0, c0 = cell(40.16, -105.0)
    r1, c1 = cell(40.04, -104.88)
    count[r0:r1, c0:c1] = 2
    first[r0:r1, c0:c1] = start + 2
    last[r0:r1, c0:c1] = start + 3
    rr0, cc0 = cell(40.13, -104.97)
    rr1, cc1 = cell(40.07, -104.91)
    count[rr0:rr1, cc0:cc1] = 6
    first[rr0:rr1, cc0:cc1] = start
    last[rr0:rr1, cc0:cc1] = start + 5
    return {"times": times, "count": count, "first": first, "last": last, "found": len(times), "any": list(range(start, start + 6))}


def test_snapshots_cover_the_local_day_including_clock_changes():
    assert len(duration.snapshot_times(date(2026, 6, 1))) == 720
    assert len(duration.snapshot_times(date(2026, 3, 8))) == 690  # spring forward: 23 hours
    assert len(duration.snapshot_times(date(2026, 11, 1))) == 750  # fall back: 25 hours
    t = duration.snapshot_times(date(2026, 6, 1))
    assert t[0].hour == 6 and t[-1] - t[0] == timedelta(hours=23, minutes=58)


def test_day_file_has_stacked_minute_bands_and_cell_times():
    r = duration.build_day(date(2026, 6, 1), made_up_day())
    e, doc = r["entry"], r["doc"]
    assert e["status"] == "duration" and e["maxMinutes"] == 12
    assert e["first"] == "2026-06-01T19:00:00Z" and e["last"] == "2026-06-01T19:10:00Z"
    assert e["cities"]["frederick"] == 12 and e["file"] == "days/2026-06-01.json"
    bands = [f["properties"] for f in doc["duration"]["features"]]
    assert bands == [{"minMinutes": 2, "maxMinutes": 5}, {"minMinutes": 5, "maxMinutes": 10}, {"minMinutes": 10, "maxMinutes": 15}]
    core = Point(-104.94, 40.10)
    inside = [f["properties"]["minMinutes"] for f in doc["duration"]["features"] if shape(f["geometry"]).contains(core)]
    assert max(inside) == 10
    json.dumps(doc)  # plain JSON


def test_cell_rows_look_up_a_house():
    doc = duration.build_day(date(2026, 6, 1), made_up_day())["doc"]
    c = doc["cells"]
    assert c["columns"] == ["row", "col", "first", "last", "minutes"]
    lat, lng = 40.10, -104.94
    row = int((c["north"] - lat) / c["step"])
    col = int((lng - c["west"]) / c["step"])
    hit = [x for x in c["rows"] if x[0] == row and x[1] == col]
    assert len(hit) == 1
    _, _, first, last, minutes = hit[0]
    assert minutes == 12
    start = doc["cells"]["start"]
    assert start == "2026-06-01T06:00:00Z"
    assert (first, last) == (13 * 60, 13 * 60 + 10)  # 1:00 pm to 1:10 pm MDT, minutes after local midnight


def test_too_many_missing_snapshots_marks_the_day_missing():
    g = made_up_day()
    g["found"] = len(g["times"]) - config.DURATION_MAX_MISSING_SNAPSHOTS - 1
    r = duration.build_day(date(2026, 6, 1), g)
    assert r["entry"]["status"] == "missing" and r.get("doc") is None
    g["found"] = len(g["times"]) - 3
    r = duration.build_day(date(2026, 6, 1), g)
    assert r["entry"]["status"] == "duration" and r["entry"]["snapshots"] == g["found"]


def test_a_day_with_no_inch_hail_in_any_snapshot_is_none():
    g = made_up_day()
    g["count"][:] = 0
    g["first"][:] = duration.NONE
    g["last"][:] = duration.NONE
    g["any"] = []
    r = duration.build_day(date(2026, 6, 1), g)
    assert r["entry"]["status"] == "none" and r["doc"] is None


def test_daily_picks_recent_then_missing_then_history_newest_first(tmp_path):
    hail = tmp_path / "index.json"
    days = ["2024-06-01", "2025-07-04", "2026-05-01", "2026-11-20", "2026-11-23", "2026-11-24"]
    hail.write_text(json.dumps({"days": [{"date": d, "status": "hail"} for d in days] + [{"date": "2026-11-22", "status": "none"}]}))
    out = tmp_path / "duration"
    duration.write_index(out, {"2026-11-20": {"date": "2026-11-20", "status": "missing"}, "2025-07-04": {"date": "2025-07-04", "status": "duration"}})
    got = [d.isoformat() for d in duration.daily_days(out, hail, date(2026, 11, 25))]
    assert got == ["2026-11-24", "2026-11-23", "2026-11-20", "2026-05-01"]  # 2024-06-01 is before the history start
