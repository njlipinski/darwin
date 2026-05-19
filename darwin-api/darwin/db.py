"""Database schema and connection helpers.

All SQLite access goes through here. Schema is defined once; `get_connection`
ensures every consumer gets a connection with foreign keys enabled.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from darwin.config import DB_PATH

log = logging.getLogger(__name__)

SCHEMA = """
-- Layer 1: bulk planet catalog from the NASA Exoplanet Archive.
-- One row per confirmed exoplanet. Used for habitability screening.
CREATE TABLE IF NOT EXISTS planets (
    pl_name             TEXT PRIMARY KEY,
    hostname            TEXT,
    pl_rade             REAL,    -- Earth radii
    pl_masse            REAL,    -- Earth masses
    pl_orbper           REAL,    -- days
    pl_orbsmax          REAL,    -- AU
    pl_eqt              REAL,    -- K
    pl_insol            REAL,    -- Earth = 1
    st_teff             REAL,    -- K
    st_rad              REAL,    -- solar radii
    st_mass             REAL,    -- solar masses
    st_lum              REAL,    -- log10(L_sun)
    st_spectype         TEXT,    -- spectral type (added in latest ingest)
    sy_dist             REAL,    -- pc
    disc_year           INTEGER,
    disc_facility       TEXT,

    -- DARWIN-derived (populated by habitability scoring stage):
    in_hz               INTEGER, -- 1 if in conservative HZ, 0 if not, NULL if unknown
    is_rocky_candidate  INTEGER, -- 1 if R < threshold, 0 if not, NULL if unknown
    habitability_score  REAL,    -- 0-1, NULL if insufficient data
    esi                 REAL,    -- Earth Similarity Index (simplified), NULL if unknown

    last_updated        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_planets_hostname ON planets(hostname);
CREATE INDEX IF NOT EXISTS idx_planets_hz ON planets(in_hz);

-- Layer 2a: inventory of MAST observations for spectra targets.
-- We don't store the underlying data, just pointers to what exists.
CREATE TABLE IF NOT EXISTS mast_products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pl_name             TEXT,
    target_name         TEXT,           -- as queried in MAST (host name)
    obs_collection      TEXT,           -- JWST, HST, ...
    instrument          TEXT,
    obs_id              TEXT,
    proposal_id         TEXT,
    dataproduct_type    TEXT,
    calib_level         INTEGER,        -- 1=raw .. 4=HLSP
    provenance_name     TEXT,           -- 'HLSP' for community-reduced
    data_url            TEXT,
    fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pl_name) REFERENCES planets(pl_name),
    UNIQUE(obs_id, data_url)
);

CREATE INDEX IF NOT EXISTS idx_mast_planet ON mast_products(pl_name);
CREATE INDEX IF NOT EXISTS idx_mast_hlsp ON mast_products(provenance_name);

-- Layer 2b: reduced spectra we've actually ingested and parsed.
-- Wavelength/flux arrays live in files; this table stores metadata + path.
CREATE TABLE IF NOT EXISTS spectra (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pl_name             TEXT,
    instrument          TEXT,           -- e.g. "JWST/NIRSpec PRISM"
    spectrum_type       TEXT,           -- "transmission" | "emission" | "reflection"
    wavelength_min_um   REAL,
    wavelength_max_um   REAL,
    n_points            INTEGER,
    source              TEXT,           -- DOI, paper ref, or MAST product ID
    data_path           TEXT,           -- relative path under data/spectra/
    ingested_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pl_name) REFERENCES planets(pl_name)
);

CREATE INDEX IF NOT EXISTS idx_spectra_planet ON spectra(pl_name);

-- Layer 3: classifications produced by the data-analysis track.
-- The analysis person writes here (or hands us a JSON we load).
CREATE TABLE IF NOT EXISTS classifications (
    pl_name             TEXT PRIMARY KEY,
    habitability_label  TEXT,    -- 'habitable' | 'marginal' | 'uninhabitable'
    biosignature_label  TEXT,    -- 'candidate' | 'inconclusive' | 'none' | 'no_data'
    confidence          REAL,    -- 0-1
    reasoning           TEXT,    -- prose explanation (Claude output)
    caveats             TEXT,    -- known false-positive concerns
    classified_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pl_name) REFERENCES planets(pl_name)
);
"""


def get_connection(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a connection with sensible defaults (FKs on, row factory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path = DB_PATH, *, reset: bool = False) -> sqlite3.Connection:
    """Create tables if needed. With reset=True, drops the file first."""
    if reset and path.exists():
        log.warning("Removing existing database at %s", path)
        path.unlink()
    conn = get_connection(path)
    conn.executescript(SCHEMA)
    conn.commit()
    log.info("Database ready at %s", path)
    return conn
