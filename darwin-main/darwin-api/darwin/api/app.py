"""FastAPI application.

Endpoints:
  GET  /planets                          list (paginated, filterable)
  GET  /planets/{name}                   detail
  GET  /planets/{name}/spectra           summaries of spectra for one planet
  GET  /spectra/{spectrum_id}            full spectrum with arrays
  GET  /classifications/{name}           analysis output for one planet
  GET  /health                           ping

Run with: uvicorn darwin.api.app:app --reload
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from darwin.config import SPECTRA_DIR
from darwin.db import get_connection
from darwin.api.schemas import (
    Classification,
    PlanetDetail,
    PlanetSummary,
    Spectrum,
    SpectrumSummary,
)

log = logging.getLogger(__name__)

app = FastAPI(
    title="DARWIN API",
    description="Database of Atmospheric Readings for Worlds with Infrared aNalysis",
    version="0.1.0",
)

# Permissive CORS for development. Tighten before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/planets", response_model=list[PlanetSummary])
def list_planets(
    habitable: Optional[bool] = Query(None, description="Filter to in_hz=true"),
    rocky: Optional[bool] = Query(None, description="Filter to rocky candidates"),
    has_spectrum: Optional[bool] = Query(None, description="Filter to planets with ingested spectra"),
    min_score: Optional[float] = Query(None, ge=0, le=1),
    limit: int = Query(100, le=1000),
    offset: int = 0,
):
    where = []
    args: list = []
    if habitable is not None:
        where.append("p.in_hz = ?")
        args.append(1 if habitable else 0)
    if rocky is not None:
        where.append("p.is_rocky_candidate = ?")
        args.append(1 if rocky else 0)
    if min_score is not None:
        where.append("p.habitability_score >= ?")
        args.append(min_score)
    if has_spectrum is True:
        where.append("(SELECT COUNT(*) FROM spectra s WHERE s.pl_name = p.pl_name) > 0")
    elif has_spectrum is False:
        where.append("(SELECT COUNT(*) FROM spectra s WHERE s.pl_name = p.pl_name) = 0")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT
          p.pl_name, p.hostname, p.pl_rade, p.pl_eqt, p.sy_dist,
          p.habitability_score, p.in_hz,
          (SELECT COUNT(*) FROM spectra s WHERE s.pl_name = p.pl_name) AS n_spectra
        FROM planets p
        {where_clause}
        ORDER BY p.habitability_score DESC NULLS LAST, p.pl_name
        LIMIT ? OFFSET ?
    """
    args += [limit, offset]

    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()

    return [
        PlanetSummary(
            pl_name=r["pl_name"],
            hostname=r["hostname"],
            pl_rade=r["pl_rade"],
            pl_eqt=r["pl_eqt"],
            sy_dist=r["sy_dist"],
            habitability_score=r["habitability_score"],
            in_hz=bool(r["in_hz"]) if r["in_hz"] is not None else None,
            has_spectrum=r["n_spectra"] > 0,
            n_spectra=r["n_spectra"],
        )
        for r in rows
    ]


@app.get("/planets/{name}", response_model=PlanetDetail)
def get_planet(name: str):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   (SELECT COUNT(*) FROM spectra s WHERE s.pl_name = p.pl_name) AS n_spectra
            FROM planets p WHERE p.pl_name = ?
            """,
            (name,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"planet '{name}' not found")
    d = dict(row)
    d["in_hz"] = bool(d["in_hz"]) if d["in_hz"] is not None else None
    d["is_rocky_candidate"] = (
        bool(d["is_rocky_candidate"]) if d["is_rocky_candidate"] is not None else None
    )
    return PlanetDetail(**d)


@app.get("/planets/{name}/spectra", response_model=list[SpectrumSummary])
def list_spectra_for_planet(name: str):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM spectra WHERE pl_name = ? ORDER BY ingested_at DESC",
            (name,),
        ).fetchall()
    return [SpectrumSummary(**dict(r)) for r in rows]


@app.get("/spectra/{spectrum_id}", response_model=Spectrum)
def get_spectrum(spectrum_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM spectra WHERE id = ?", (spectrum_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"spectrum id {spectrum_id} not found")

    # Read the wavelength/flux arrays from the CSV file
    full_path = SPECTRA_DIR.parent / row["data_path"]
    if not full_path.exists():
        raise HTTPException(500, f"data file missing: {row['data_path']}")

    wavelengths, fluxes, errs = [], [], []
    with full_path.open() as f:
        reader = csv.DictReader(f)
        has_err = "flux_err" in (reader.fieldnames or [])
        for r in reader:
            wavelengths.append(float(r["wavelength_um"]))
            fluxes.append(float(r["flux"]))
            if has_err and r.get("flux_err"):
                errs.append(float(r["flux_err"]))

    return Spectrum(
        id=row["id"],
        pl_name=row["pl_name"],
        instrument=row["instrument"],
        spectrum_type=row["spectrum_type"],
        wavelength_um=wavelengths,
        flux=fluxes,
        flux_err=errs if errs else None,
        source=row["source"],
    )


@app.get("/classifications/{name}", response_model=Classification)
def get_classification(name: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM classifications WHERE pl_name = ?", (name,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"no classification for '{name}'")
    return Classification(**dict(row))
