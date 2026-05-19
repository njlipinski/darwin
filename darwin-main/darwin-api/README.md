# DARWIN — API / MAST integration

Database of Atmospheric Readings for Worlds with Infrared aNalysis.

This is the backend track: ingestion pipeline + REST API serving planet
metadata, spectra, and classifications.

## Setup

```bash
pip install -r requirements.txt
```

## Populate the database

```bash
# Full pipeline (planets + MAST inventory + spectra)
python scripts/run_ingest.py

# Start fresh
python scripts/run_ingest.py --reset

# Just refresh the bulk planet catalog
python scripts/run_ingest.py --skip-mast --skip-spectra
```

The first run takes a few minutes — the bulk Exoplanet Archive query pulls
~5,800 planets, and the MAST inventory queries ~20 targets.

## Serve the API

```bash
uvicorn darwin.api.app:app --reload
```

Then visit:
- `http://localhost:8000/docs` — interactive API documentation
- `http://localhost:8000/planets?habitable=true&rocky=true` — strong candidates
- `http://localhost:8000/planets/K2-18%20b` — one planet's detail

## Adding spectra

Two paths:

1. **Manual ingestion (works now).** Drop a CSV into `data/spectra/manual/`
   following the naming convention `{planet_name}__{instrument}__{source}.csv`
   with columns `wavelength_um,flux,flux_err`. Run `scripts/run_ingest.py`.

2. **MAST HLSP ingestion (TODO).** See the docstring in
   `darwin/ingest/spectra.py::ingest_mast_hlsp`. Implement per-program adapters.

## Repo layout

```
darwin-api/
├── darwin/
│   ├── config.py        # paths, target list, HZ thresholds
│   ├── db.py            # schema + connection helpers
│   ├── ingest/
│   │   ├── planets.py           # bulk catalog + habitability scoring
│   │   ├── mast_inventory.py    # MAST observation logging
│   │   └── spectra.py           # spectrum file → DB
│   └── api/
│       ├── app.py       # FastAPI app
│       └── schemas.py   # response models (frontend contract)
├── scripts/
│   └── run_ingest.py    # main entry point
├── data/                # gitignored, populated by ingestion
└── tests/
```

## The frontend contract

The Pydantic models in `darwin/api/schemas.py` define exactly what each
endpoint returns. If you change a schema, tell the frontend coder. The
auto-generated docs at `/docs` are the source of truth.
