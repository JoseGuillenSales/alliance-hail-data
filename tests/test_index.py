import json
from datetime import date

from engine import run


def hail(d, size):
    return {
        "entry": {"date": d, "status": "hail", "maxInches": size, "file": f"days/{d}.json", "bbox": [-104, 39, -103, 40]},
        "doc": {"type": "FeatureCollection", "date": d, "features": []},
    }


def test_index_is_sorted_and_rerunning_changes_nothing(tmp_path):
    results = [hail("2026-05-21", 2.71), {"entry": {"date": "2026-05-20", "status": "none", "maxInches": 0.4}}]
    run.save(tmp_path, results)
    first = (tmp_path / "index.json").read_text()
    run.save(tmp_path, results)
    assert (tmp_path / "index.json").read_text() == first
    index = json.loads(first)
    assert [d["date"] for d in index["days"]] == ["2026-05-20", "2026-05-21"]
    assert index["bands"] == [1.0, 1.5, 2.0, 2.5] and index["units"] == "inches"
    assert (tmp_path / "days" / "2026-05-21.json").exists()
    assert not (tmp_path / "days" / "2026-05-20.json").exists()


def test_missing_never_replaces_good_data(tmp_path):
    run.save(tmp_path, [hail("2026-05-21", 2.71)])
    run.save(tmp_path, [{"entry": {"date": "2026-05-21", "status": "missing", "reason": "Radar file not found"}}])
    assert run.load_index(tmp_path)["2026-05-21"]["status"] == "hail"


def test_missing_day_is_filled_in_later(tmp_path):
    run.save(tmp_path, [{"entry": {"date": "2026-07-02", "status": "missing", "reason": "Radar file not found"}}])
    run.save(tmp_path, [hail("2026-07-02", 1.3)])
    assert run.load_index(tmp_path)["2026-07-02"]["status"] == "hail"


def test_a_day_that_turns_out_dry_loses_its_file(tmp_path):
    run.save(tmp_path, [hail("2026-07-02", 1.3)])
    run.save(tmp_path, [{"entry": {"date": "2026-07-02", "status": "none", "maxInches": 0.8}}])
    assert not (tmp_path / "days" / "2026-07-02.json").exists()


def test_daily_picks_recent_days_and_retries_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "report_days", lambda a, b: set())
    run.save(tmp_path, [
        {"entry": {"date": "2026-06-20", "status": "missing", "reason": "x"}},  # retried
        {"entry": {"date": "2026-04-01", "status": "missing", "reason": "x"}},  # too old
    ])
    got = run.daily_days(tmp_path, date(2026, 7, 2))
    assert got == [date(2026, 6, 20), date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)]


def test_daily_off_season_only_processes_report_days(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "report_days", lambda a, b: {date(2026, 11, 16)})
    assert run.daily_days(tmp_path, date(2026, 11, 18)) == [date(2026, 11, 16)]
