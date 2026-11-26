# Alliance hail data

Radar hail paths for Colorado, made every day from free NOAA radar data (MRMS MESH,
Maximum Estimated Size of Hail) for Alliance Restoration's website and CRM.

**All sizes are radar-estimated.** Radar can overestimate or underestimate hail size;
only an inspection can confirm damage.

- `data/`: the published files (`index.json`, `days/YYYY-MM-DD.json`, `status.json`),
  served at https://joseguillensales.github.io/alliance-hail-data/
- `engine/`: the Python that makes them. All settings, including the size bands, are
  in `engine/config.py`.
- `tests/`: `python -m pytest`

The file formats are described in `docs/hail-paths-data.md` in the
alliance-restoration-website repo. That's the contract the website and CRM rely on.

**Wind paths** are made here too (`engine/wind.py`, the "Daily wind paths" Action) and
published under `data/wind/`: each Colorado day's strongest estimated wind gust from
NOAA's hourly wind analysis (URMA), plus the Weather Service's wind reports. Their
format, and how close they are to measured gusts, is in
[`docs/wind-paths-data.md`](docs/wind-paths-data.md). All wind-path speeds are
estimated; thunderstorm gusts are often missed by the hourly maps, which is why the
reports are included.

**Hail duration** is made here too (`engine/duration.py`, the "Daily hail duration"
Action) and published under `data/duration/`: for each hail day, how many minutes radar
showed hail of 1 inch or more at each spot, and when it first and last did, from NOAA's
2-minute radar snapshots. Format and limits: [`docs/hail-duration-data.md`](docs/hail-duration-data.md).
Always radar-estimated, never measured at the ground.

## Running it

```bash
pip install -r requirements.txt
python -m engine day 2026-05-21            # one or more days
python -m engine range 2024-11-18 2026-11-17   # storm season plus ground-report days
python -m engine daily                     # what the daily job runs
python -m engine.wind day 2025-12-17       # wind for one or more days
python -m engine.wind range 2026-05-01 2026-10-31
python -m engine.wind daily                # what the daily wind job runs
python -m engine.duration day 2026-06-01   # hail duration for one or more hail days
python -m engine.duration daily            # what the daily duration job runs
```

On a computer without Python, use Docker:

```bash
docker build -t hailpaths .
docker run --rm -v "$PWD:/work" hailpaths python -m engine day 2026-05-21
```

Radar data: NOAA/NSSL MRMS, via the Iowa Environmental Mesonet archive (Iowa State
University). Wind gusts: NOAA URMA, from NOAA's open data on AWS. Ground reports: NWS
Local Storm Reports via the Iowa Environmental Mesonet.
