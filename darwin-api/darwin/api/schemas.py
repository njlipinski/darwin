"""Pydantic response models — THE CONTRACT WITH THE FRONTEND.

If you change a schema here, tell the frontend coder. They build against
these shapes; silent changes break their UI.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PlanetSummary(BaseModel):
    """Minimal fields for catalog list views."""
    pl_name: str
    hostname: Optional[str] = None
    pl_rade: Optional[float] = Field(None, description="Planet radius (Earth radii)")
    pl_eqt: Optional[float] = Field(None, description="Equilibrium temperature (K)")
    sy_dist: Optional[float] = Field(None, description="Distance to system (pc)")
    habitability_score: Optional[float] = Field(None, ge=0, le=1)
    in_hz: Optional[bool] = None
    has_spectrum: bool = False
    n_spectra: int = 0


class PlanetDetail(BaseModel):
    """Full planet record for detail pages."""
    pl_name: str
    hostname: Optional[str]
    pl_rade: Optional[float]
    pl_masse: Optional[float]
    pl_orbper: Optional[float]
    pl_orbsmax: Optional[float]
    pl_eqt: Optional[float]
    pl_insol: Optional[float]
    st_teff: Optional[float]
    st_rad: Optional[float]
    st_mass: Optional[float]
    st_lum: Optional[float]
    sy_dist: Optional[float]
    disc_year: Optional[int]
    disc_facility: Optional[str]
    in_hz: Optional[bool]
    is_rocky_candidate: Optional[bool]
    habitability_score: Optional[float]
    n_spectra: int = 0


class SpectrumSummary(BaseModel):
    """Spectrum metadata (no arrays). Used in lists."""
    id: int
    pl_name: str
    instrument: str
    spectrum_type: Literal["transmission", "emission", "reflection"]
    wavelength_min_um: float
    wavelength_max_um: float
    n_points: int
    source: str


class Spectrum(BaseModel):
    """Full spectrum with wavelength/flux arrays — what the plot consumes."""
    id: int
    pl_name: str
    instrument: str
    spectrum_type: Literal["transmission", "emission", "reflection"]
    wavelength_um: list[float]
    flux: list[float]
    flux_err: Optional[list[float]] = None
    source: str


class Classification(BaseModel):
    """Output from the data-analysis track."""
    pl_name: str
    habitability_label: Optional[Literal["habitable", "marginal", "uninhabitable"]] = None
    biosignature_label: Optional[Literal["candidate", "inconclusive", "none", "no_data"]] = None
    confidence: Optional[float] = Field(None, ge=0, le=1)
    reasoning: Optional[str] = None
    caveats: Optional[str] = None
