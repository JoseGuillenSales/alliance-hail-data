import json
from datetime import date

import numpy as np
from shapely.geometry import Point

from engine import config, paths, wind


def blank():
    return np.zeros((wind.ROWS, wind.COLS))


def cell(lat, lng):
    return int((config.NORTH - lat) / wind.STEP), int((lng - config.WEST) / wind.STEP)


def fill(a, lat0, lat1, lng0, lng1, mph):
    r0, c0 = cell(lat1, lng0)
    r1, c1 = cell(lat0, lng1)
    a[r0 : r1 + 1, c0 : c1 + 1] = mph


def windstorm():
    """A made-up foothills windstorm: 65 mph strip, 75 mph inside, 95 mph core near Boulder."""
    a = blank()
    fill(a, 39.6, 40.6, -105.5, -104.9, 65)
    fill(a, 39.8, 40.4, -105.4, -105.0, 75)
    fill(a, 39.95, 40.1, -105.35, -105.15, 95)
    return a


def test_wind_grid_covers_colorado():
    assert (wind.ROWS, wind.COLS) == (201, 351)
    lats, lons = wind.centres()
    assert abs(lats[0] - 40.99) < 1e-9 and lats[-1] < config.SOUTH + wind.STEP
    assert abs(lons[0] + 109.05) < 1e-9 and lons[-1] > config.EAST - wind.STEP


def test_wind_bands_stack_and_skip_missing_bands():
    shapes = paths.band_shapes(windstorm(), wind.WIND)
    assert [lo for lo, _ in shapes] == [60.0, 70.0, 80.0, 90.0]
    for (_, lower), (_, upper) in zip(shapes, shapes[1:]):
        assert lower.buffer(1e-9).contains(upper)
    core, edge = Point(-105.25, 40.02), Point(-105.2, 39.68)
    assert [g.contains(core) for _, g in shapes] == [True, True, True, True]
    assert [g.contains(edge) for _, g in shapes] == [True, False, False, False]


def test_calm_day_has_no_shapes():
    a = blank() + 45
    assert paths.band_shapes(a, wind.WIND) == []


def test_band_labels_in_whole_mph():
    assert wind.band_label(70.0) == {"minMph": 70, "maxMph": 80}
    assert wind.band_label(90.0) == {"minMph": 90, "maxMph": None}


def test_day_hours_follow_mountain_time():
    assert len(wind.hours(date(2025, 12, 17))) == 24
    assert len(wind.hours(date(2026, 3, 8))) == 23  # spring forward
    assert len(wind.hours(date(2026, 11, 1))) == 25  # fall back
    first = wind.hours(date(2025, 12, 17))[0]
    assert first.strftime("%Y-%m-%d %H:%M") == "2025-12-17 07:00"


def test_gust_found_from_index(monkeypatch):
    idx = "\n".join(
        [
            "1:0:d=2026112018:HGT:surface:anl:",
            "9:51494777:d=2026112018:WIND:10 m above ground:anl:",
            "10:57112413:d=2026112018:GUST:10 m above ground:anl:",
            "11:62730049:d=2026112018:VIS:surface:anl:",
        ]
    )
    monkeypatch.setattr(wind, "_get", lambda url, byte_range=None: idx.encode())
    assert wind.gust_range("https://example/x.grb2") == (57112413, 62730048)


CSV = """VALID,VALID2,LAT,LON,MAG,WFO,TYPECODE,TYPETEXT,CITY,COUNTY,STATE,SOURCE,REMARK,UGC,UGCNAME,QUALIFIER
202512171830,2025/12/17 18:30,40.02,-105.27,98.0,BOU,N,NON-TSTM WND GST,Boulder,Boulder,CO,Mesonet,x,COZ039,x,M
202512171840,2025/12/17 18:40,40.10,-105.10,45.0,BOU,N,NON-TSTM WND GST,Niwot,Boulder,CO,ASOS,x,COZ039,x,M
202512180500,2025/12/18 05:00,39.70,-104.90,,BOU,D,NON-TSTM WND DMG,Denver,Denver,CO,Public,x,COZ039,x,
202512180200,2025/12/18 02:00,39.50,-104.50,70.0,BOU,G,TSTM WND GST,Elizabeth,Elbert,CO,Trained Spotter,x,COZ039,x,E
202512171900,2025/12/17 19:00,40.70,-111.90,80.0,SLC,N,NON-TSTM WND GST,Salt Lake,Salt Lake,UT,ASOS,x,UTZ001,x,M
202512171900,2025/12/17 19:00,40.00,-105.00,1.00,BOU,H,HAIL,Erie,Weld,CO,Public,x,COZ039,x,E
"""


def test_reports_kept_and_grouped_by_colorado_day(monkeypatch):
    monkeypatch.setattr(wind, "_get", lambda url, byte_range=None: CSV.encode())
    got = wind.fetch_reports(date(2025, 12, 17), date(2025, 12, 17))
    assert list(got) == ["2025-12-17"]  # 05:00 and 02:00 UTC on the 18th are still the 17th in Colorado
    reps = got["2025-12-17"]
    assert [(r["place"], r["kind"], r["mph"], r["measured"], r["thunderstorm"]) for r in reps] == [
        ("Boulder", "gust", 98, True, False),
        ("Elizabeth", "gust", 70, False, True),
        ("Denver", "damage", None, False, False),
    ]  # the 45 mph gust, Utah and the hail report are left out


def test_process_day_marks_wind_and_missing(monkeypatch):
    monkeypatch.setattr(wind, "day_gusts", lambda day: (windstorm(), 24, 24))
    reps = [{"time": "2025-12-17T18:30Z", "lat": 40.02, "lng": -105.27, "kind": "gust", "thunderstorm": False, "mph": 98, "measured": True, "source": "Mesonet", "place": "Boulder"}]
    r = wind.process_day(date(2025, 12, 17), reps)
    e, doc = r["entry"], r["doc"]
    assert e["status"] == "wind" and e["maxMph"] == 95 and e["maxReportMph"] == 98 and e["file"] == "days/2025-12-17.json"
    assert e["cities"]["boulder"] == 95
    assert [f["properties"]["minMph"] for f in doc["features"]] == [60, 70, 80, 90]
    assert doc["reports"] == reps and doc["units"] == "mph"
    json.dumps(doc)

    monkeypatch.setattr(wind, "day_gusts", lambda day: (windstorm(), 20, 24))
    assert wind.process_day(date(2025, 12, 17), reps)["entry"]["status"] == "missing"

    monkeypatch.setattr(wind, "day_gusts", lambda day: (blank() + 30, 24, 24))
    calm = wind.process_day(date(2025, 12, 17), [])
    assert calm["entry"]["status"] == "none" and calm["doc"] is None


def test_damage_report_alone_makes_a_wind_day(monkeypatch):
    monkeypatch.setattr(wind, "day_gusts", lambda day: (blank() + 30, 24, 24))
    dmg = [{"time": "2026-06-22T23:00Z", "lat": 40.3, "lng": -103.5, "kind": "damage", "thunderstorm": True, "mph": None, "measured": False, "source": "Public", "place": "Brush"}]
    r = wind.process_day(date(2026, 6, 22), dmg)
    assert r["entry"]["status"] == "wind" and r["doc"]["features"] == [] and r["entry"]["bbox"] == [-103.5, 40.3, -103.5, 40.3]
