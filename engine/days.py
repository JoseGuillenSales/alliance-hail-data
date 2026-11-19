"""Colorado days (Mountain Time) and which radar files cover them.

Each MESH_Max_1440min file holds the biggest hail the radar saw in the 24 hours before
the file's time. So the file stamped at the local midnight that ends a Colorado day
covers that whole day: 06:00 UTC the next day in summer (MDT), 07:00 UTC in winter (MST).

On the two clock-change days the day isn't 24 hours long:
- Spring forward (23 hours): the file also covers 11 pm to midnight the night before.
- Fall back (25 hours): the file misses the day's first hour (midnight to 1 am MDT).
The engine covers that odd hour with the 2-minute snapshots (see run.py).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config

DENVER = ZoneInfo(config.TIMEZONE)


def day_start_utc(day: date) -> datetime:
    """Local midnight starting the day, in UTC."""
    return datetime.combine(day, time(0), tzinfo=DENVER).astimezone(timezone.utc)


def day_end_utc(day: date) -> datetime:
    """Local midnight ending the day, in UTC: the time of the file that covers the day."""
    return day_start_utc(day + timedelta(days=1))


def day_hours(day: date) -> float:
    return (day_end_utc(day) - day_start_utc(day)).total_seconds() / 3600


def odd_hour(day: date) -> tuple[str, datetime, datetime] | None:
    """On a clock-change day, the hour the 24-hour file gets wrong.

    ("extra", start, end): the file includes this hour from the night before.
    ("gap", start, end): the file leaves out this hour of the day.
    None on ordinary 24-hour days.
    """
    end = day_end_utc(day)
    window_start = end - timedelta(hours=24)
    start = day_start_utc(day)
    if window_start < start:
        return ("extra", window_start, start)
    if window_start > start:
        return ("gap", start, window_start)
    return None


def colorado_date(t: datetime) -> date:
    """The Colorado date of a moment in time."""
    return t.astimezone(DENVER).date()


def colorado_today(now: datetime | None = None) -> date:
    return colorado_date(now or datetime.now(timezone.utc))


def in_season(day: date) -> bool:
    return config.SEASON_START <= (day.month, day.day) <= config.SEASON_END


def file_urls(t: datetime, product: str = config.DAY_PRODUCT) -> list[str]:
    """Where the radar file for this moment can be downloaded, best first."""
    t = t.astimezone(timezone.utc)
    return [config.ARCHIVE_URL.format(t=t, product=product), config.REALTIME_URL.format(t=t, product=product)]


def season_days(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if in_season(d):
            out.append(d)
        d += timedelta(days=1)
    return out
