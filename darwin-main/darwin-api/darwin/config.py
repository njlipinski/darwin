"""Configuration: paths, constants, and the curated target list.

Everything that needs to know about the file layout or which planets we focus
on imports from this module. Don't sprinkle paths or planet lists elsewhere.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent   # darwin-api/
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "darwin.sqlite"
SPECTRA_DIR = DATA_DIR / "spectra"
CALIBRATION_DIR = DATA_DIR / "calibration"

# ---------------------------------------------------------------------------
# Bulk ingestion (Option C, layer 1): the whole confirmed-exoplanet catalog
# ---------------------------------------------------------------------------

# Columns we want from the Exoplanet Archive's pscomppars table.
# pscomppars = "Planetary Systems Composite Parameters", one row per planet
# with the best available values combined across references.
EA_COLUMNS = [
    "pl_name",        # planet name (primary key)
    "hostname",       # host star
    "pl_rade",        # planet radius (Earth radii)
    "pl_masse",       # planet mass (Earth masses)
    "pl_orbper",      # orbital period (days)
    "pl_orbsmax",     # semi-major axis (AU) — needed for HZ calc
    "pl_eqt",         # equilibrium temperature (K)
    "pl_insol",       # insolation flux (Earth = 1)
    "st_teff",        # stellar effective temperature (K)
    "st_rad",         # stellar radius (solar radii)
    "st_mass",        # stellar mass (solar masses)
    "st_lum",         # log(stellar luminosity / L_sun)
    "sy_dist",        # distance to system (pc)
    "disc_year",
    "disc_facility",
]

# ---------------------------------------------------------------------------
# Spectra ingestion (Option C, layer 2): curated list of planets with
# published atmospheric observations worth analyzing for biosignatures.
# ---------------------------------------------------------------------------

# Format: (planet name as in Exoplanet Archive, host name for MAST query).
# MAST searches expect the host star name, not the planet name.
SPECTRA_TARGETS = [
    ("K2-18 b",      "K2-18"),
    ("WASP-39 b",    "WASP-39"),
    ("WASP-43 b",    "WASP-43"),
    ("WASP-96 b",    "WASP-96"),
    ("WASP-107 b",   "WASP-107"),
    ("HD 209458 b",  "HD 209458"),
    ("HD 189733 b",  "HD 189733"),
    ("GJ 1214 b",    "GJ 1214"),
    ("GJ 486 b",     "GJ 486"),
    ("LHS 475 b",    "LHS 475"),
    ("TRAPPIST-1 b", "TRAPPIST-1"),
    ("TRAPPIST-1 c", "TRAPPIST-1"),
    ("TRAPPIST-1 d", "TRAPPIST-1"),
    ("TRAPPIST-1 e", "TRAPPIST-1"),
    ("TRAPPIST-1 f", "TRAPPIST-1"),
    ("TRAPPIST-1 g", "TRAPPIST-1"),
    ("TRAPPIST-1 h", "TRAPPIST-1"),
    ("55 Cnc e",     "55 Cnc"),
    ("LTT 9779 b",   "LTT 9779"),
    ("TOI-270 d",    "TOI-270"),
]

# ---------------------------------------------------------------------------
# Habitability scoring thresholds (Option C, layer 1)
# Conservative habitable zone definition; used by ingest/planets.py.
# These are tunable — document any changes in the writeup.
# ---------------------------------------------------------------------------

HZ_TEQ_MIN_K = 175    # below this: too cold (Mars is ~210, but allow margin)
HZ_TEQ_MAX_K = 320    # above this: too hot (runaway greenhouse risk)
ROCKY_RADIUS_MAX_REARTH = 1.8   # above this: likely gaseous (Fulton gap ~1.6-2.0)
