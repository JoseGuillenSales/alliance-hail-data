# Wind paths: data contract

This is the contract for the wind-path files. The CRM (and later, maybe, the website)
reads them, so **don't change these formats without bumping `version` and updating
every reader**. The hail-path files are described separately, in `docs/hail-paths-data.md`
in the alliance-restoration-website repo; nothing about them changes.

The files are made by this repo (`python -m engine.wind`, run by the daily
"Daily wind paths" GitHub Action) from free NOAA data and published with GitHub Pages,
next to the hail files. No keys, no cost.

## Where the files are

| File | URL |
|---|---|
| Index of every processed day | `https://joseguillensales.github.io/alliance-hail-data/wind/index.json` |
| One wind day's paths and reports | `https://joseguillensales.github.io/alliance-hail-data/wind/days/YYYY-MM-DD.json` |
| Last run (for monitoring) | `https://joseguillensales.github.io/alliance-hail-data/wind/status.json` |

- Same hosting as the hail files: anyone can read them, cached about 10 minutes, gzipped.
- The `file` path in the index is relative to `wind/` (the index's own folder):
  `"file": "days/2025-12-17.json"` means `.../alliance-hail-data/wind/days/2025-12-17.json`.

## The sources

1. **Wind paths: NOAA URMA wind gust analysis.** Every hour NOAA makes a 2.5 km map of
   the wind gust at the top of the hour, from weather stations blended with a weather
   model (URMA, the "Un-Restricted Mesoscale Analysis", on NOAA's open data on AWS,
   `noaa-urma-pds`). The engine keeps the strongest of the day's hours in each square.
2. **Wind reports: NWS Local Storm Reports** (via the Iowa Environmental Mesonet):
   wind gusts of 50 mph or more and wind-damage reports in Colorado.

**Every gust in the paths is estimated.** Show "estimated" wherever a path speed
appears; never "confirmed" or "actual". Only an inspection can confirm damage.

What the paths are good and bad at (from checks against measured gusts, see the end):
- **Windstorms** (Front Range downslope wind, winter and spring wind events) last for
  hours, and the hourly maps catch them well.
- **Thunderstorm gusts** last minutes and usually fall between the hours, so the paths
  miss most of them: an 80 to 110 mph thunderstorm gust can show as 50 to 60 mph or no
  shading at all. That's why the reports are included. For thunderstorm days, show the
  reports, and don't present the shading as the storm's wind path.
- The squares are 2.5 km, so the paths show areas, not streets.

## Units and dates

- **Speeds are in mph**, whole numbers (converted from m/s).
- **Coordinates** are `[longitude, latitude]` (GeoJSON order), path coordinates rounded
  to 4 decimals, report coordinates to 3.
- **Dates are Colorado dates (Mountain Time)**, local midnight to local midnight, the
  same as the hail files. Clock-change days have 23 or 25 hours.
- **Paths start at 60 mph** (`minMph`); bands are 60, 70, 80 and 90+ mph.

## Which days are processed

- **Every day of the year** (Colorado's worst windstorms come in winter).
- The history starts **November 18, 2024**, the same as the hail files.
- The daily run (14:30 UTC) processes the last 3 finished days, fills in history not
  done yet (up to 400 days per run, newest first), and retries "missing"
  days up to 30 days old. NOAA posts each hour about 7 hours late, so a day is complete
  by the next morning.

## wind/index.json

```json
{
  "version": 1,
  "units": "mph",
  "timezone": "America/Denver",
  "bands": [60, 70, 80, 90],
  "minMph": 60,
  "cityRadiusMiles": 3.0,
  "source": "NOAA URMA hourly wind gust analysis (strongest hour of each Colorado day), plus NWS Local Storm Reports of wind",
  "days": [
    {"date":"2025-12-17","status":"wind","maxMph":115,"reports":239,"maxReportMph":124,"file":"days/2025-12-17.json","bbox":[-109.06,36.99,-102.04,41.0],"cities":{"boulder":109,"fort-collins":100,"longmont":90}},
    {"date":"2025-12-20","status":"none","maxMph":48},
    {"date":"2026-06-22","status":"wind","maxMph":75,"reports":26,"maxReportMph":113,"file":"days/2026-06-22.json","bbox":[-104.32,38.4,-102.26,40.7436]},
    {"date":"2026-07-02","status":"missing","reason":"Wind files found for 20 of 24 hours"}
  ]
}
```

| Field | Meaning |
|---|---|
| `status` | `"wind"`: the day has paths (60+ mph somewhere) or a report of 58+ mph or of wind damage, and has a `file`. `"none"`: processed, nothing to show. `"missing"`: the NOAA files couldn't be found; retried by later runs, nothing is filled in. |
| `maxMph` | Strongest estimated gust anywhere in Colorado that day. |
| `reports` | Number of wind reports kept that day (gusts of 50+ mph and damage). Missing when there were none. |
| `maxReportMph` | Strongest reported gust (measured or estimated by a person). |
| `file` | The day file, relative to `wind/`. Only on `"wind"` days. |
| `bbox` | `[west, south, east, north]` around the paths and the reports, for zooming the map. |
| `cities` | Strongest estimated gust within `cityRadiusMiles` of each website city, for cities at 60+ mph. Same city slugs as the hail index. |
| `hours`, `note` | Only when one or two of the day's hours were missing: how many hours were used, and a sentence saying so. |
| `reason` | Why a day is `"missing"`. |

## wind/days/YYYY-MM-DD.json

A GeoJSON FeatureCollection, plus extra fields:

```json
{
  "type": "FeatureCollection",
  "version": 1,
  "date": "2025-12-17",
  "units": "mph",
  "maxMph": 115,
  "bbox": [-109.06, 36.99, -102.04, 41.0],
  "source": {"product": "NOAA URMA 2.5 km wind gust analysis, strongest hour of the day", "hours": 24},
  "features": [
    {"type": "Feature", "properties": {"minMph": 60, "maxMph": 70}, "geometry": {"type": "MultiPolygon", "coordinates": []}},
    {"type": "Feature", "properties": {"minMph": 90, "maxMph": null}, "geometry": {"type": "MultiPolygon", "coordinates": []}}
  ],
  "reports": [
    {"time": "2025-12-17T18:30Z", "lat": 40.02, "lng": -105.27, "kind": "gust", "thunderstorm": false, "mph": 98, "measured": true, "source": "Mesonet", "place": "Boulder"}
  ]
}
```

- **`features`**: one per band that has any area, lowest first. Like the hail files,
  each band's shape covers everything **at or above** its lower edge and sits inside the
  band below it. Draw them in order. `maxMph: null` is the top band (90+). May be empty
  on a day that is a wind day only because of its reports.
- **`reports`**: in time order.
  - `kind`: `"gust"` or `"damage"` (a damage report usually has no speed: `mph: null`).
  - `thunderstorm`: true for thunderstorm wind, false for other wind (windstorms).
  - `measured`: true when an instrument measured it (weather station), false when a
    person estimated it.
  - `time` is UTC; `source` and `place` are as the Weather Service gave them
    ("ASOS", "Mesonet", "Trained Spotter"; "4 N Boulder"). Report remarks aren't kept.

## How close it is

Checked on November 23, 2026 against the measured gusts of 58 mph or more (weather
stations, `measured: true`) on the 40 Colorado days with the most such gusts from
December 2024 to November 2026. The map's strongest band within about 2 miles of each
station was compared with the station's gust:

| | Windstorms | Thunderstorms |
|---|---|---|
| Measured gusts compared | 1,412 (35 days) | 120 (11 days) |
| Station inside the shading | 79% | 35% |
| Shading within 10 mph of the station | 52% | 15% |
| Shading lower than measured | 25% | 45% |

So for windstorms the shading finds the windy areas about 4 times in 5, and is often
a band higher than a single station (it shows the strongest gust within the area). For
thunderstorms it misses most gusts; use the reports.

## Changing things

- Bands, grid, smoothing and the report rules are in `engine/config.py` (the `WIND_` settings).
- Re-process days from the "Daily wind paths" Action (`dates` or `range`), or locally:
  `python -m engine.wind day 2025-12-17`.
