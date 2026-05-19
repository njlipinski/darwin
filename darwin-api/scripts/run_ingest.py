#!/usr/bin/env python3
"""Run the full DARWIN ingestion pipeline.

Usage:
  python scripts/run_ingest.py                  # full run
  python scripts/run_ingest.py --reset          # rebuild from scratch
  python scripts/run_ingest.py --skip-mast      # planet bulk only
  python scripts/run_ingest.py --skip-planets   # MAST + spectra only
"""
from __future__ import annotations

import argparse
import logging
import sys

# Make the darwin package importable when running this script directly
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from darwin.db import init_db
from darwin.ingest import planets, mast_inventory, spectra


def main() -> int:
    ap = argparse.ArgumentParser(description="DARWIN ingestion pipeline")
    ap.add_argument("--reset", action="store_true", help="Drop and recreate the DB")
    ap.add_argument("--skip-planets", action="store_true", help="Skip bulk planet ingestion")
    ap.add_argument("--skip-mast", action="store_true", help="Skip MAST inventory")
    ap.add_argument("--skip-spectra", action="store_true", help="Skip spectra ingestion")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )

    conn = init_db(reset=args.reset)

    if not args.skip_planets:
        try:
            planets.run(conn)
        except Exception as e:
            logging.error("Planet ingestion failed: %s: %s", type(e).__name__, e)
            return 1

    if not args.skip_mast:
        try:
            mast_inventory.run(conn)
        except Exception as e:
            logging.error("MAST inventory failed: %s: %s", type(e).__name__, e)
            # Not fatal — keep going

    if not args.skip_spectra:
        try:
            spectra.run(conn)
        except Exception as e:
            logging.error("Spectra ingestion failed: %s: %s", type(e).__name__, e)

    # Final summary
    cur = conn.cursor()
    n_planets = cur.execute("SELECT COUNT(*) FROM planets").fetchone()[0]
    n_hz = cur.execute("SELECT COUNT(*) FROM planets WHERE in_hz=1").fetchone()[0]
    n_rocky_hz = cur.execute(
        "SELECT COUNT(*) FROM planets WHERE in_hz=1 AND is_rocky_candidate=1"
    ).fetchone()[0]
    n_mast = cur.execute("SELECT COUNT(*) FROM mast_products").fetchone()[0]
    n_spectra = cur.execute("SELECT COUNT(*) FROM spectra").fetchone()[0]

    print()
    print("=" * 60)
    print("DARWIN ingestion summary")
    print("=" * 60)
    print(f"  Planets in catalog:           {n_planets}")
    print(f"  In habitable zone:            {n_hz}")
    print(f"  Rocky + in HZ (strong cand.): {n_rocky_hz}")
    print(f"  MAST products logged:         {n_mast}")
    print(f"  Spectra ingested:             {n_spectra}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
