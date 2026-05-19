"""Stage 1: bulk planet metadata from the NASA Exoplanet Archive.

Pulls the entire confirmed-planet catalog (~5,800 rows) and writes to the
`planets` table. Then runs habitability scoring on the populated table.

The Exoplanet Archive's TAP service uses ADQL, which is SQL-like. The
`pscomppars` table is the "composite parameters" view — one row per planet
with the best available values across references.
"""
from __future__ import annotations

import logging
import sqlite3

from darwin.config import (
    EA_COLUMNS,
    HZ_TEQ_MAX_K,
    HZ_TEQ_MIN_K,
    ROCKY_RADIUS_MAX_REARTH,
)

log = logging.getLogger(__name__)


def fetch_all_planets():
    """Query the Exoplanet Archive for all confirmed planets.

    Returns an astropy Table. Network call; can be slow (10-30s).
    """
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    log.info("Querying NASA Exoplanet Archive (this may take 10-30 seconds)...")
    table = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        select=",".join(EA_COLUMNS),
    )
    log.info("Got %d planets from Exoplanet Archive", len(table))
    return table


def _coerce(value):
    """Convert astropy masked values, numpy scalars, etc. to plain Python."""
    if value is None:
        return None
    # Masked values
    if hasattr(value, "mask") and value.mask:
        return None
    # numpy scalars
    if hasattr(value, "item"):
        try:
            v = value.item()
            # numpy NaN -> None
            if isinstance(v, float) and v != v:
                return None
            return v
        except (ValueError, TypeError):
            pass
    # plain NaN floats
    if isinstance(value, float) and value != value:
        return None
    return value


def upsert_planets(conn: sqlite3.Connection, table) -> int:
    """Insert/replace bulk planet rows. Returns count written."""
    cols = EA_COLUMNS
    placeholders = ",".join("?" * len(cols))
    sql = (
        f"INSERT OR REPLACE INTO planets ({','.join(cols)}) "
        f"VALUES ({placeholders})"
    )
    rows = [tuple(_coerce(row[c]) for c in cols) for row in table]
    conn.executemany(sql, rows)
    conn.commit()
    log.info("Wrote %d planet rows", len(rows))
    return len(rows)

def esi(radius_re, teq_k, radius_ref=1.0, teq_ref=288.0):
    """Earth Similarity Index (simplified, radius+temperature only)."""
    if radius_re is None or teq_k is None:
        return None
    er = 1 - abs((radius_re - radius_ref) / (radius_re + radius_ref))
    et = 1 - abs((teq_k - teq_ref) / (teq_k + teq_ref))
    return (er * et) ** 0.5

def score_habitability(conn: sqlite3.Connection) -> int:
    """Populate in_hz, is_rocky_candidate, and habitability_score columns.

    Simple rule-based scoring; the analysis track may replace this with
    something more sophisticated. Returns count of planets scored.
    """
    cur = conn.cursor()

    # in_hz: equilibrium temperature in conservative habitable range
    cur.execute(
        """
        UPDATE planets
        SET in_hz = CASE
            WHEN pl_eqt IS NULL THEN NULL
            WHEN pl_eqt BETWEEN ? AND ? THEN 1
            ELSE 0
        END
        """,
        (HZ_TEQ_MIN_K, HZ_TEQ_MAX_K),
    )

    # is_rocky_candidate: radius below the sub-Neptune gap
    cur.execute(
        """
        UPDATE planets
        SET is_rocky_candidate = CASE
            WHEN pl_rade IS NULL THEN NULL
            WHEN pl_rade <= ? THEN 1
            ELSE 0
        END
        """,
        (ROCKY_RADIUS_MAX_REARTH,)
    )
    
    # ESI — Earth Similarity Index. Computed in Python because the
    # formula isn't easily expressed in SQL.
    rows = cur.execute(
        "SELECT pl_name, pl_rade, pl_eqt FROM planets"
    ).fetchall()
    updates = [
        (esi(r["pl_rade"], r["pl_eqt"]), r["pl_name"])
        for r in rows
    ]
    cur.executemany("UPDATE planets SET esi = ? WHERE pl_name = ?", updates)

    # habitability_score: 1.0 only if both flags positive; 0.5 if one; 0 if neither;
    # NULL if either input is unknown.
    cur.execute(
        """
        UPDATE planets
        SET habitability_score = CASE
            WHEN in_hz IS NULL OR is_rocky_candidate IS NULL THEN NULL
            WHEN in_hz = 1 AND is_rocky_candidate = 1 THEN 1.0
            WHEN in_hz = 1 OR is_rocky_candidate = 1 THEN 0.5
            ELSE 0.0
        END
        """
    )

    conn.commit()
    n = cur.execute(
        "SELECT COUNT(*) FROM planets WHERE habitability_score IS NOT NULL"
    ).fetchone()[0]
    log.info("Scored %d planets for habitability", n)

    # Quick breakdown for the log
    breakdown = cur.execute(
        """
        SELECT
          SUM(CASE WHEN habitability_score = 1.0 THEN 1 ELSE 0 END) AS strong,
          SUM(CASE WHEN habitability_score = 0.5 THEN 1 ELSE 0 END) AS partial,
          SUM(CASE WHEN habitability_score = 0.0 THEN 1 ELSE 0 END) AS none,
          SUM(CASE WHEN habitability_score IS NULL THEN 1 ELSE 0 END) AS unknown
        FROM planets
        """
    ).fetchone()
    log.info(
        "  strong=%s  partial=%s  none=%s  unknown=%s",
        breakdown["strong"], breakdown["partial"],
        breakdown["none"], breakdown["unknown"],
    )
    return n


def run(conn: sqlite3.Connection) -> None:
    """Full stage: fetch + upsert + score."""
    table = fetch_all_planets()
    upsert_planets(conn, table)
    score_habitability(conn)
