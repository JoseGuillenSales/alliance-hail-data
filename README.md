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

## Running it

```bash
pip install -r requirements.txt
python -m engine day 2026-05-21            # one or more days
python -m engine range 2024-11-18 2026-11-17   # storm season plus ground-report days
python -m engine daily                     # what the daily job runs
```

On a computer without Python, use Docker:

```bash
docker build -t hailpaths .
docker run --rm -v "$PWD:/work" hailpaths python -m engine day 2026-05-21
```

Radar data: NOAA/NSSL MRMS, via the Iowa Environmental Mesonet archive (Iowa State
University). Ground reports: NWS Local Storm Reports via the Iowa Environmental Mesonet.
