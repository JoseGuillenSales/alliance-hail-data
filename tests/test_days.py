from datetime import date, datetime, timezone

from engine import days as D


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_summer_day_ends_at_6_utc():
    assert D.day_end_utc(date(2026, 5, 21)) == utc(2026, 5, 22, 6)
    assert D.day_hours(date(2026, 5, 21)) == 24
    assert D.odd_hour(date(2026, 5, 21)) is None


def test_winter_day_ends_at_7_utc():
    assert D.day_end_utc(date(2026, 1, 15)) == utc(2026, 1, 16, 7)
    assert D.odd_hour(date(2026, 1, 15)) is None


def test_spring_forward_day_is_23_hours_and_file_includes_the_night_before():
    day = date(2026, 3, 8)
    assert D.day_start_utc(day) == utc(2026, 3, 8, 7)  # midnight MST
    assert D.day_end_utc(day) == utc(2026, 3, 9, 6)  # midnight MDT
    assert D.day_hours(day) == 23
    assert D.odd_hour(day) == ("extra", utc(2026, 3, 8, 6), utc(2026, 3, 8, 7))


def test_fall_back_day_is_25_hours_and_file_misses_the_first_hour():
    day = date(2025, 11, 2)
    assert D.day_start_utc(day) == utc(2025, 11, 2, 6)  # midnight MDT
    assert D.day_end_utc(day) == utc(2025, 11, 3, 7)  # midnight MST
    assert D.day_hours(day) == 25
    assert D.odd_hour(day) == ("gap", utc(2025, 11, 2, 6), utc(2025, 11, 2, 7))


def test_days_next_to_clock_changes_are_ordinary():
    for day in [date(2026, 3, 7), date(2026, 3, 9), date(2025, 11, 1), date(2025, 11, 3)]:
        assert D.day_hours(day) == 24
        assert D.odd_hour(day) is None


def test_colorado_date_of_a_moment():
    assert D.colorado_date(utc(2026, 5, 22, 5, 59)) == date(2026, 5, 21)  # 11:59 pm MDT
    assert D.colorado_date(utc(2026, 5, 22, 6, 0)) == date(2026, 5, 22)  # midnight MDT
    assert D.colorado_date(utc(2026, 1, 16, 6, 59)) == date(2026, 1, 15)  # 11:59 pm MST
    # The May 21, 2026 storm's reports (around 5-8 pm MDT) land on May 21
    assert D.colorado_date(utc(2026, 5, 21, 23, 50)) == date(2026, 5, 21)
    assert D.colorado_date(utc(2026, 5, 22, 2, 48)) == date(2026, 5, 21)


def test_season():
    assert D.in_season(date(2026, 4, 1))
    assert D.in_season(date(2026, 10, 31))
    assert not D.in_season(date(2026, 3, 31))
    assert not D.in_season(date(2026, 11, 1))
    assert len(D.season_days(date(2024, 11, 18), date(2026, 11, 17))) == 428


def test_file_urls():
    urls = D.file_urls(D.day_end_utc(date(2026, 5, 21)))
    assert urls[0] == (
        "https://mtarchive.geol.iastate.edu/2026/05/22/mrms/ncep/MESH_Max_1440min/"
        "MESH_Max_1440min_00.50_20260522-060000.grib2.gz"
    )
    assert urls[1].endswith("/2D/MESH_Max_1440min/MRMS_MESH_Max_1440min_00.50_20260522-060000.grib2.gz")
    snap = D.file_urls(utc(2025, 11, 2, 6, 2), "MESH")[0]
    assert snap.endswith("/2025/11/02/mrms/ncep/MESH/MESH_00.50_20251102-060200.grib2.gz")
