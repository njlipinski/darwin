"""Tests that don't require network access (schema, schemas, API logic)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from darwin.api.app import app
from darwin.api.schemas import PlanetSummary, Spectrum
from darwin.db import init_db


def setup_db():
    conn = init_db(reset=True)
    conn.execute(
        "INSERT INTO planets (pl_name, hostname, pl_rade, pl_eqt, in_hz, "
        "is_rocky_candidate, habitability_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("TRAPPIST-1 e", "TRAPPIST-1", 0.92, 251, 1, 1, 1.0),
    )
    conn.commit()
    return conn


def test_schema_validates():
    p = PlanetSummary(pl_name="X", has_spectrum=False, n_spectra=0)
    assert p.pl_name == "X"


def test_health():
    setup_db()
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_planets_list():
    setup_db()
    client = TestClient(app)
    r = client.get("/planets")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["pl_name"] == "TRAPPIST-1 e"


def test_planet_filter_combines():
    setup_db()
    client = TestClient(app)
    r = client.get("/planets?habitable=true&rocky=true")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r = client.get("/planets?habitable=true&rocky=false")
    assert r.status_code == 200
    assert len(r.json()) == 0


def test_404_for_missing_planet():
    setup_db()
    client = TestClient(app)
    assert client.get("/planets/Mars").status_code == 404


if __name__ == "__main__":
    # Run each test, print PASS/FAIL
    for name in [n for n in dir() if n.startswith("test_")]:
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            print(f"ERROR {name}: {type(e).__name__}: {e}")
