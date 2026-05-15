"""
DARWIN - fetch_planet_metadata.py
Pulls metadata for a curated list of JWST-observed exoplanets from the
NASA Exoplanet Archive and saves it as a CSV for the DARWIN database.

Usage:
    python fetch_planet_metadata.py

Output:
    data/planet_metadata.csv

Requires:
    pip install astroquery pandas
"""

from pathlib import Path
import sys
import pandas as pd

# ---------------------------------------------------------------------------
# Curated target list: exoplanets with published JWST atmospheric data.
# Add or remove planets here as the project scope evolves.
# Names must match the NASA Exoplanet Archive's pl_name field exactly.
# ---------------------------------------------------------------------------
TARGET_PLANETS = [
    "WASP-39 b",      # CO2, SO2, H2O, Na - landmark JWST ERS target
    "WASP-96 b",      # First JWST exoplanet spectrum released
    "WASP-43 b",      # Phase curve, dayside/nightside chemistry
    "WASP-17 b",      # Quartz clouds detected
    "WASP-18 b",      # Ultra-hot Jupiter, water emission
    "WASP-77 A b",    # Carbon-to-oxygen ratio measurement
    "WASP-107 b",     # Methane, SO2, sulfur photochemistry
    "K2-18 b",        # CH4, CO2, possible DMS - sub-Neptune in HZ
    "GJ 1214 b",      # Hazy mini-Neptune
    "GJ 486 b",       # Terrestrial, water vapor (or stellar contamination)
    "GJ 367 b",       # Ultra-short-period rocky planet
    "LHS 475 b",      # Earth-sized, no thick atmosphere
    "TRAPPIST-1 b",   # Thermal emission, likely bare rock
    "TRAPPIST-1 c",   # Thermal emission, thin or no atmosphere
    "55 Cnc e",       # Super-Earth, secondary eclipse
    "HD 189733 b",    # Legacy hot Jupiter re-observed
    "HD 209458 b",    # Legacy hot Jupiter, water and CO
    "TOI-270 d",      # Sub-Neptune atmosphere
    "L 98-59 d",      # Small planet, sulfur compounds reported
]

# Columns we want from the pscomppars (planetary systems composite) table.
# Full column reference:
#   https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html
COLUMNS = [
    "pl_name",        # Planet name
    "hostname",       # Host star name
    "discoverymethod",
    "disc_year",
    "pl_orbper",      # Orbital period (days)
    "pl_rade",        # Planet radius (Earth radii)
    "pl_radj",        # Planet radius (Jupiter radii)
    "pl_masse",       # Planet mass (Earth masses)
    "pl_massj",       # Planet mass (Jupiter masses)
    "pl_eqt",         # Equilibrium temperature (K)
    "pl_insol",       # Insolation flux (Earth units)
    "pl_orbsmax",     # Semi-major axis (AU)
    "pl_orbeccen",    # Eccentricity
    "st_spectype",    # Stellar spectral type
    "st_teff",        # Stellar effective temperature (K)
    "st_rad",         # Stellar radius (solar radii)
    "st_mass",        # Stellar mass (solar masses)
    "st_met",         # Stellar metallicity
    "sy_dist",        # Distance to system (parsecs)
    "ra",             # Right ascension
    "dec",            # Declination
]


def fetch_via_astroquery():
    """Try the astroquery wrapper first (cleanest API)."""
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    # Build a SQL-style WHERE clause: pl_name='WASP-39 b' OR pl_name='K2-18 b' OR ...
    name_clause = " OR ".join(f"pl_name='{p}'" for p in TARGET_PLANETS)
    select_clause = ",".join(COLUMNS)

    print(f"Querying NASA Exoplanet Archive for {len(TARGET_PLANETS)} planets...")
    result = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        where=name_clause,
        select=select_clause,
    )
    return result.to_pandas()


def fetch_via_tap():
    """
    Fallback: hit the TAP endpoint directly with requests.
    Useful if astroquery has issues or you want fewer dependencies.
    """
    import requests
    from io import StringIO

    name_list = ",".join(f"'{p}'" for p in TARGET_PLANETS)
    select_clause = ",".join(COLUMNS)
    adql = (
        f"SELECT {select_clause} "
        f"FROM pscomppars "
        f"WHERE pl_name IN ({name_list})"
    )

    url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
    params = {"query": adql, "format": "csv"}

    print(f"Querying NASA Exoplanet Archive TAP endpoint...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(StringIO(resp.text))


def main():
    try:
        df = fetch_via_astroquery()
    except Exception as e:
        print(f"astroquery path failed ({e}); falling back to direct TAP query.")
        df = fetch_via_tap()

    # Report which targets we got and which we missed
    found = set(df["pl_name"].tolist())
    missing = [p for p in TARGET_PLANETS if p not in found]
    print(f"\nReceived {len(df)} rows for {len(found)} unique planets.")
    if missing:
        print(f"Missing from results: {missing}")
        print("(Check spelling against pl_name on exoplanetarchive.ipac.caltech.edu)")

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "planet_metadata.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")

    # Quick sanity-print of a couple key columns
    preview_cols = ["pl_name", "hostname", "pl_rade", "pl_eqt", "sy_dist"]
    available = [c for c in preview_cols if c in df.columns]
    print("\nPreview:")
    print(df[available].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
