"""Stage 2a: MAST observation inventory for our spectra-target list.

For each curated target, list JWST and HST observations available on MAST.
We log what's there for traceability; the actual spectrum downloads happen
in ingest/spectra.py.
"""
from __future__ import annotations

import logging
import sqlite3

from darwin.config import SPECTRA_TARGETS

log = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT OR IGNORE INTO mast_products (
    pl_name, target_name, obs_collection, instrument, obs_id,
    proposal_id, dataproduct_type, calib_level, provenance_name, data_url
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def fetch_products_for_target(planet_name: str, host_name: str) -> list[tuple]:
    """Query MAST for JWST/HST observations of one host star."""
    from astroquery.mast import Observations

    log.info("  MAST: %s (host=%s)", planet_name, host_name)
    try:
        obs = Observations.query_criteria(
            target_name=host_name,
            obs_collection=["JWST", "HST"],
        )
    except Exception as e:
        log.error("    query failed: %s: %s", type(e).__name__, e)
        return []

    rows = []
    for o in obs:
        rows.append((
            planet_name,
            host_name,
            _safe(o, "obs_collection"),
            _safe(o, "instrument_name"),
            _safe(o, "obs_id"),
            _safe(o, "proposal_id"),
            _safe(o, "dataproduct_type"),
            _safe(o, "calib_level"),
            _safe(o, "provenance_name"),
            _safe(o, "dataURL"),
        ))
    log.info("    -> %d products", len(rows))
    return rows


def _safe(row, key):
    """Pull a value from an astropy row, returning None if missing/masked."""
    try:
        v = row[key]
    except (KeyError, IndexError):
        return None
    if hasattr(v, "mask") and v.mask:
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, TypeError):
            return str(v)
    return v


def run(conn: sqlite3.Connection) -> int:
    """Walk SPECTRA_TARGETS and log MAST products for each. Returns total rows."""
    total = 0
    for pl_name, host_name in SPECTRA_TARGETS:
        rows = fetch_products_for_target(pl_name, host_name)
        if rows:
            conn.executemany(_INSERT_SQL, rows)
            conn.commit()
            total += len(rows)
    log.info("Total MAST products logged: %d", total)
    return total
