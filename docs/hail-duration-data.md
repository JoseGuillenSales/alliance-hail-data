# Hail duration: data contract

How long radar showed hail of 1 inch or more at each spot on a Colorado hail day, and
when it first and last did. The CRM reads these files; **don't change these formats
without bumping `version` and updating every reader**. The hail-path and wind-path files
don't change; this is a separate, optional set of files next to them.

Made by this repo (`python -m engine.duration`, run by the "Daily hail duration" GitHub
Action) from free NOAA data, published with GitHub Pages. No keys, no cost.

## Where the files are

| File | URL |
|---|---|
| Index of every processed hail day | `https://joseguillensales.github.io/alliance-hail-data/duration/index.json` |
| One day's duration shapes and per-square times | `https://joseguillensales.github.io/alliance-hail-data/duration/days/YYYY-MM-DD.json` |
| Last run (for monitoring) | `https://joseguillensales.github.io/alliance-hail-data/duration/status.json` |

The `file` path in the index is relative to `duration/`, like the wind files.

## The source and what it means

NOAA MRMS **MESH** (Maximum Estimated Size of Hail) every 2 minutes, the same radar
product the daily hail paths are built from (the daily file is the maximum of these).
For each 0.01-degree radar square (about 1 km) and each snapshot of the Colorado day:

- a snapshot showing **1 inch or more** counts as **2 minutes** of hail there;
- **first** / **last**: the first and the last such snapshot.

The squares that ever reach 1 inch are exactly the squares inside the daily 1-inch hail
path, so a house inside the 1" hail path always has a duration, and one outside never does.

Limits, to say plainly wherever this is shown:
- It's what radar saw in the cloud, every 2 minutes, not a stopwatch at the ground.
  Always word it as **radar-estimated** ("radar showed 1-inch hail here for about 10
  minutes, 1:02 to 1:12 pm, estimated"). Never "actual" or "measured".
- 2-minute steps: a short burst between two snapshots can show as 0 or 2 minutes.
- Hail aloft can melt or drift before it lands. In a check against the Weather Service's
  ground reports on June 1, 2026, the reported time was usually within about 7 minutes of
  radar's first 1-inch snapshot at or next to the spot, and within 30 minutes in every case.

## Which days

Only **hail days**: days with `"status": "hail"` in the hail `index.json` (1-inch radar
hail somewhere in Colorado). History from 2024-11-18, filled in newest first over the
first runs. A day without duration data yet simply isn't in `duration/index.json` (or is
`"missing"`), so readers should say "not available for this day", never 0 minutes.

## `duration/index.json`

```json
{"version":1,"units":"minutes","timezone":"America/Denver","bands":[2,5,10,15],
 "stepMinutes":2,"minInches":1.0,"cityRadiusMiles":3.0,"source":"…","days":[
{"date":"2026-06-01","status":"duration","maxMinutes":30,"first":"2026-06-01T18:58:00Z",
 "last":"2026-06-02T00:04:00Z","file":"days/2026-06-01.json","bbox":[-105.19,37.4002,-102.06,40.8825],
 "cities":{"denver":16,"aurora":30,"strasburg":20}}
]}
```

| Field | Meaning |
|---|---|
| `status` | `"duration"` (has a file), `"none"` (no snapshot reached 1 inch), `"missing"` (more than 30 snapshots, an hour, couldn't be downloaded; tried again on later runs for 30 days) |
| `maxMinutes` | the longest anywhere in Colorado that day |
| `first`, `last` | the first and last 2-minute snapshot with 1-inch hail anywhere in Colorado, UTC |
| `cities` | the longest within `cityRadiusMiles` of each of the website's cities, in minutes (cities under 2 minutes left out) |
| `snapshots`, `note` | only when a few snapshots were missing: how many were found |

## `duration/days/YYYY-MM-DD.json`

```json
{"type":"HailDuration","version":1,"date":"2026-06-01","units":"minutes","stepMinutes":2,
 "minInches":1.0,"maxMinutes":30,"first":"…Z","last":"…Z","bbox":[…],
 "snapshots":{"found":720,"expected":720},"source":{"product":"MESH","everyMinutes":2},
 "duration":{"type":"FeatureCollection","features":[
   {"type":"Feature","properties":{"minMinutes":2,"maxMinutes":5},"geometry":{"type":"MultiPolygon",…}},
   …]},
 "cells":{"start":"2026-06-01T06:00:00Z","west":-109.06,"north":41.0,"step":0.01,
   "columns":["row","col","first","last","minutes"],
   "rows":[[870,413,780,790,12], …]}}
```

**`duration`**: shapes for the map, made exactly like the hail-path bands. Bands 2, 5,
10 and 15 minutes; each shape covers everything at or above its lower edge and sits inside
the one below (`maxMinutes: null` on the 15+ band). For a point, the highest band whose
shape contains it gives "about 5 to 10 minutes", and so on.

**`cells`**: one row per radar square that had 1-inch hail, for looking up a house:
- `row = floor((north - lat) / step)`, `col = floor((lng - west) / step)`.
- `first` and `last` are **minutes after `start`**, which is local midnight beginning
  the Colorado day, in UTC. The time is `start + first minutes` (so DST and clock-change
  days need no special handling). `last` is the start of the last 2-minute snapshot.
- `minutes` is the number of snapshots × 2.
- Recommended lookup: the house's own square; if it has no row, the 8 squares around it
  (about 1 km, which matches the slight smoothing of the shapes). Take the earliest
  `first`, the latest `last` and the largest `minutes` of the squares found.

A big hail day (June 1, 2026, about 1,200 squares) is about 100 KB.
