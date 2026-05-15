"""
DARWIN — Database of Atmospheric Readings for Worlds with Infrared aNalysis
Starter ingestion script.

What this does:
  1. Initializes a SQLite database with tables for planets, spectra, and data products.
  2. Pulls confirmed exoplanet metadata from the NASA Exoplanet Archive (TAP service)
     for a curated list of targets known to have published atmospheric observations.
  3. Queries MAST for available JWST / HST data products on each target and records
     what's available (without downloading spectra yet — that's stage 2).
  4. Logs everything so you can see what worked and what didn't.

Usage:
  python darwin_ingest.py                  # run the full pipeline
  python darwin_ingest.py --reset          # drop and recreate the database first
  python darwin_ingest.py --targets-only   # just refresh the planet metadata

Requirements:
  pip install astroquery astropy
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

# Curated target list — planets with published JWST or HST atmospheric observations.
# This is intentionally short. Add more as you find them in HLSPs or paper supplements.
# The host-name form (without the trailing planet letter) is what MAST searches expect.
TARGETS = [
    # (planet name as in Exoplanet Archive, host name for MAST search)
    ("K2-18 b",        "K2-18"),
    ("WASP-39 b",      "WASP-39"),
    ("WASP-43 b",      "WASP-43"),
    ("WASP-96 b",      "WASP-96"),
    ("WASP-107 b",     "WASP-107"),
    ("HD 209458 b",    "HD 209458"),
    ("HD 189733 b",    "HD 189733"),
    ("GJ 1214 b",      "GJ 1214"),
    ("GJ 486 b",       "GJ 486"),
    ("LHS 475 b",      "LHS 475"),
    ("TRAPPIST-1 b",   "TRAPPIST-1"),
    ("TRAPPIST-1 c",   "TRAPPIST-1"),
    ("TRAPPIST-1 d",   "TRAPPIST-1"),
    ("TRAPPIST-1 e",   "TRAPPIST-1"),
    ("TRAPPIST-1 f",   "TRAPPIST-1"),
    ("TRAPPIST-1 g",   "TRAPPIST-1"),
    ("TRAPPIST-1 h",   "TRAPPIST-1"),
    ("55 Cnc e",       "55 Cnc"),
    ("LTT 9779 b",     "LTT 9779"),
    ("TOI-270 d",      "TOI-270"),
]

DB_PATH = Path("darwin.sqlite")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("darwin")

# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

SCHEMA = """
-- Planets: bulk parameters from the NASA Exoplanet Archive.
CREATE TABLE IF NOT EXISTS planets (
    pl_name         TEXT PRIMARY KEY,        -- e.g. "K2-18 b"
    hostname        TEXT,                    -- host star
    pl_rade         REAL,                    -- planet radius (Earth radii)
    pl_masse        REAL,                    -- planet mass (Earth masses)
    pl_orbper       REAL,                    -- orbital period (days)
    pl_eqt          REAL,                    -- equilibrium temperature (K)
    pl_insol        REAL,                    -- insolation flux (Earth units)
    st_teff         REAL,                    -- stellar effective temp (K)
    st_rad          REAL,                    -- stellar radius (solar radii)
    st_mass         REAL,                    -- stellar mass (solar masses)
    sy_dist         REAL,                    -- distance to system (pc)
    disc_year       INTEGER,
    disc_facility   TEXT,
    -- DARWIN-derived flags (populated later by the classifier stage):
    hz_flag         INTEGER DEFAULT NULL,    -- in habitable zone? (1/0/null)
    notes           TEXT,
    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Data products available on MAST for each target (one row per observation).
-- We log what's available without downloading anything yet.
CREATE TABLE IF NOT EXISTS mast_products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pl_name         TEXT,
    target_name     TEXT,                    -- as queried in MAST
    obs_collection  TEXT,                    -- JWST, HST, etc.
    instrument      TEXT,                    -- NIRSpec, NIRISS, MIRI, ...
    obs_id          TEXT,
    proposal_id     TEXT,
    dataproduct_type TEXT,                   -- spectrum, image, ...
    calib_level     INTEGER,                 -- 1=raw ... 4=HLSP
    t_obs_release   TEXT,
    provenance_name TEXT,                    -- HLSP if community-reduced
    dataURL         TEXT,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pl_name) REFERENCES planets(pl_name),
    UNIQUE(obs_id, dataURL)
);

-- Spectra: each row is one reduced spectrum (one planet may have many).
-- Wavelength/flux arrays live in files referenced by `data_path`.
CREATE TABLE IF NOT EXISTS spectra (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pl_name         TEXT,
    instrument      TEXT,                    -- e.g. "JWST/NIRSpec PRISM"
    wavelength_min  REAL,                    -- microns
    wavelength_max  REAL,                    -- microns
    n_points        INTEGER,
    spectrum_type   TEXT,                    -- "transmission", "emission", "reflection"
    source          TEXT,                    -- DOI, MAST product ID, or paper ref
    data_path       TEXT,                    -- relative path to wavelength/flux file
    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pl_name) REFERENCES planets(pl_name)
);

CREATE INDEX IF NOT EXISTS idx_mast_planet ON mast_products(pl_name);
CREATE INDEX IF NOT EXISTS idx_spectra_planet ON spectra(pl_name);
"""


def init_db(path: Path, reset: bool = False) -> sqlite3.Connection:
    if reset and path.exists():
        log.warning("Removing existing database at %s", path)
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    log.info("Database ready at %s", path.resolve())
    return conn


# ---------------------------------------------------------------------------
# Stage 1: planet metadata from Exoplanet Archive
# ---------------------------------------------------------------------------

EA_COLUMNS = [
    "pl_name", "hostname", "pl_rade", "pl_masse", "pl_orbper",
    "pl_eqt", "pl_insol", "st_teff", "st_rad", "st_mass",
    "sy_dist", "disc_year", "disc_facility",
]


def fetch_planet_metadata(planet_names: Iterable[str]):
    """Query the Exoplanet Archive's pscomppars table for our target list."""
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    # Build a WHERE clause with each planet name quoted. The Exoplanet Archive
    # TAP service uses standard SQL string quoting.
    quoted = ",".join(f"'{name}'" for name in planet_names)
    where = f"pl_name in ({quoted})"

    log.info("Querying Exoplanet Archive for %d targets...", len(list(planet_names)))
    table = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        select=",".join(EA_COLUMNS),
        where=where,
    )
    log.info("Got %d rows from Exoplanet Archive", len(table))
    return table


def upsert_planets(conn: sqlite3.Connection, table) -> int:
    """Insert/replace planet metadata. Returns number of rows written."""
    placeholders = ",".join("?" * len(EA_COLUMNS))
    cols = ",".join(EA_COLUMNS)
    sql = f"INSERT OR REPLACE INTO planets ({cols}) VALUES ({placeholders})"
    rows = []
    for row in table:
        rows.append(tuple(
            # astropy MaskedColumn entries can be masked; coerce to None.
            None if hasattr(row[c], "mask") and row[c].mask
            else row[c].item() if hasattr(row[c], "item")
            else row[c]
            for c in EA_COLUMNS
        ))
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Stage 2: MAST product inventory
# ---------------------------------------------------------------------------

def fetch_mast_products(planet_name: str, host_name: str):
    """List JWST and HST observations available on MAST for one target."""
    from astroquery.mast import Observations

    log.info("  MAST query: %s (host=%s)", planet_name, host_name)
    try:
        obs = Observations.query_criteria(
            target_name=host_name,
            obs_collection=["JWST", "HST"],
        )
    except Exception as e:
        log.error("    MAST query failed for %s: %s", host_name, e)
        return []

    rows = []
    for o in obs:
        rows.append({
            "pl_name": planet_name,
            "target_name": host_name,
            "obs_collection": o.get("obs_collection"),
            "instrument": o.get("instrument_name"),
            "obs_id": o.get("obs_id"),
            "proposal_id": str(o.get("proposal_id", "")),
            "dataproduct_type": o.get("dataproduct_type"),
            "calib_level": o.get("calib_level"),
            "t_obs_release": str(o.get("t_obs_release", "")),
            "provenance_name": o.get("provenance_name"),
            "dataURL": o.get("dataURL"),
        })
    log.info("    -> %d observations found", len(rows))
    return rows


def insert_mast_products(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join("?" * len(cols))
    sql = (
        f"INSERT OR IGNORE INTO mast_products ({','.join(cols)}) "
        f"VALUES ({placeholders})"
    )
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    n_planets = cur.execute("SELECT COUNT(*) FROM planets").fetchone()[0]
    n_products = cur.execute("SELECT COUNT(*) FROM mast_products").fetchone()[0]
    log.info("=" * 60)
    log.info("Summary")
    log.info("=" * 60)
    log.info("Planets in database:    %d", n_planets)
    log.info("MAST products logged:   %d", n_products)
    log.info("")
    log.info("Top targets by product count:")
    for pl_name, count in cur.execute(
        "SELECT pl_name, COUNT(*) c FROM mast_products "
        "GROUP BY pl_name ORDER BY c DESC LIMIT 10"
    ):
        log.info("  %-20s %d", pl_name, count)
    log.info("")
    log.info("HLSP (reduced) products available:")
    for pl_name, count in cur.execute(
        "SELECT pl_name, COUNT(*) c FROM mast_products "
        "WHERE provenance_name = 'HLSP' GROUP BY pl_name ORDER BY c DESC"
    ):
        log.info("  %-20s %d", pl_name, count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DARWIN ingestion pipeline")
    ap.add_argument("--reset", action="store_true",
                    help="Drop and recreate the database before ingesting")
    ap.add_argument("--targets-only", action="store_true",
                    help="Only refresh planet metadata; skip MAST product inventory")
    ap.add_argument("--db", type=Path, default=DB_PATH,
                    help="Path to the SQLite database file")
    args = ap.parse_args(argv)

    conn = init_db(args.db, reset=args.reset)

    # Stage 1: planet metadata
    planet_names = [pl for pl, _host in TARGETS]
    try:
        table = fetch_planet_metadata(planet_names)
        n = upsert_planets(conn, table)
        log.info("Wrote %d planet rows", n)
    except Exception as e:
        log.error("Planet metadata stage failed: %s: %s", type(e).__name__, e)
        log.error("Check your network connection and that astroquery is installed.")
        return 1

    if args.targets_only:
        print_summary(conn)
        return 0

    # Stage 2: MAST inventory
    log.info("Querying MAST for data products on each target...")
    for pl_name, host_name in TARGETS:
        rows = fetch_mast_products(pl_name, host_name)
        insert_mast_products(conn, rows)

    print_summary(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
