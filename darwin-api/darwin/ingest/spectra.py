"""Stage 2b: download reduced spectra and register them in the `spectra` table.

This is the messy part. HLSP formats vary by program: column names differ,
units differ, some are FITS and some are CSV. Strategy: write one adapter
per data source rather than a universal parser.

This module ships with one worked example (a manual CSV adapter for files
dropped into data/spectra/manual/) so the pipeline runs end-to-end even
before MAST HLSPs are wired in. Add real adapters as you find usable HLSPs.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from darwin.config import SPECTRA_DIR

log = logging.getLogger(__name__)


@dataclass
class ParsedSpectrum:
    """In-memory representation of a parsed spectrum, ready to write."""
    pl_name: str
    instrument: str
    spectrum_type: str          # transmission | emission | reflection
    wavelength_um: list[float]
    flux: list[float]
    flux_err: list[float] | None
    source: str                 # DOI, paper ref, or MAST product ID


def register_spectrum(conn: sqlite3.Connection, spec: ParsedSpectrum) -> int:
    """Write spectrum to a CSV file and register a row in the DB."""
    if len(spec.wavelength_um) != len(spec.flux):
        raise ValueError(
            f"wavelength ({len(spec.wavelength_um)}) and flux "
            f"({len(spec.flux)}) length mismatch for {spec.pl_name}"
        )

    planet_dir = SPECTRA_DIR / _slug(spec.pl_name)
    planet_dir.mkdir(parents=True, exist_ok=True)
    out_path = planet_dir / f"{_slug(spec.instrument)}.csv"

    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        if spec.flux_err is not None:
            w.writerow(["wavelength_um", "flux", "flux_err"])
            for wl, fl, er in zip(spec.wavelength_um, spec.flux, spec.flux_err):
                w.writerow([wl, fl, er])
        else:
            w.writerow(["wavelength_um", "flux"])
            for wl, fl in zip(spec.wavelength_um, spec.flux):
                w.writerow([wl, fl])

    relpath = str(out_path.relative_to(SPECTRA_DIR.parent))
    cur = conn.execute(
        """
        INSERT INTO spectra (
            pl_name, instrument, spectrum_type,
            wavelength_min_um, wavelength_max_um, n_points,
            source, data_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec.pl_name, spec.instrument, spec.spectrum_type,
            min(spec.wavelength_um), max(spec.wavelength_um),
            len(spec.wavelength_um),
            spec.source, relpath,
        ),
    )
    conn.commit()
    log.info("Registered spectrum: %s [%s] -> %s",
             spec.pl_name, spec.instrument, relpath)
    return cur.lastrowid


def _slug(s: str) -> str:
    """Filesystem-safe identifier."""
    return s.replace(" ", "_").replace("/", "_").replace(",", "")


# ---------------------------------------------------------------------------
# Adapters: one per data source. Add new ones as you find usable HLSPs.
# ---------------------------------------------------------------------------

def ingest_manual_csv(conn: sqlite3.Connection, csv_path: Path,
                      pl_name: str, instrument: str, source: str,
                      spectrum_type: str = "transmission") -> int:
    """Adapter for manually-prepared CSVs in standard format.

    Expected columns: wavelength_um, flux, flux_err (flux_err optional).
    Use this for spectra you've pulled from paper supplements and saved by hand.
    """
    wavelengths, fluxes, errs = [], [], []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            wavelengths.append(float(row["wavelength_um"]))
            fluxes.append(float(row["flux"]))
            if "flux_err" in row and row["flux_err"]:
                errs.append(float(row["flux_err"]))

    spec = ParsedSpectrum(
        pl_name=pl_name,
        instrument=instrument,
        spectrum_type=spectrum_type,
        wavelength_um=wavelengths,
        flux=fluxes,
        flux_err=errs if errs else None,
        source=source,
    )
    return register_spectrum(conn, spec)


def ingest_mast_hlsp(conn: sqlite3.Connection, pl_name: str, obs_id: str) -> int:
    """Adapter for MAST HLSP products. Not yet implemented.

    To implement:
      1. Use astroquery.mast.Observations.get_product_list(obs_id)
      2. Filter to spectrum data products (productSubGroupDescription, etc.)
      3. Download with Observations.download_products(...)
      4. Parse the FITS file — column names differ by HLSP program; check
         the README on the HLSP landing page.
      5. Build a ParsedSpectrum and call register_spectrum().

    Programs to target first (highest-quality JWST atmosphere data):
      - JWST-TST-DREAMS  (WASP-39b, others)
      - JWST GTO Program 1366 (HD 209458 b)
      - TRAPPIST-1 NIRSpec programs
    """
    raise NotImplementedError(
        "MAST HLSP ingestion not yet implemented — see docstring for next steps"
    )


def run(conn: sqlite3.Connection) -> int:
    """Run all configured adapters. Currently picks up any CSVs in
    data/spectra/manual/ following the naming convention:
        {planet_name}__{instrument}__{source}.csv
    """
    manual_dir = SPECTRA_DIR / "manual"
    if not manual_dir.exists():
        log.info("No manual spectra directory; skipping")
        return 0

    count = 0
    for csv_path in manual_dir.glob("*.csv"):
        # Expected filename: "K2-18 b__NIRSpec__Madhusudhan2023.csv"
        parts = csv_path.stem.split("__")
        if len(parts) < 3:
            log.warning("Skipping %s: filename doesn't match convention", csv_path.name)
            continue
        pl_name, instrument, source = parts[0], parts[1], "__".join(parts[2:])
        try:
            ingest_manual_csv(conn, csv_path, pl_name, instrument, source)
            count += 1
        except Exception as e:
            log.error("Failed to ingest %s: %s: %s", csv_path.name, type(e).__name__, e)

    log.info("Ingested %d manual spectra", count)
    return count
