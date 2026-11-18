"""Integration test against a real PostgreSQL whose schema was created by Prisma Migrate.

Runs only when AGRISENSE_TEST_POSTGRES_URL is set (CI does this after `prisma migrate deploy`).
It checks that the SQLAlchemy runtime works on the Prisma-managed schema without creating
anything itself. Never point it at a database whose data you need: it adds simulation runs.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

URL = os.environ.get("AGRISENSE_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set AGRISENSE_TEST_POSTGRES_URL to run")


def test_backend_runs_on_prisma_migrated_schema():
    settings = Settings(
        database_url=URL,
        db_auto_create=False,  # the schema must come from Prisma
        autostart=False,
        sim_step_s=10.0,
        seed=3,
        ml_dir="nonexistent-ml-dir",
        keep_runs=2,
    )
    with TestClient(create_app(settings)) as c:
        c.post("/api/scenarios", json={"name": "dry_soil", "params": {"zone": "A", "vwc": 0.13}})
        assert c.post("/api/sim/advance", json={"hours": 3}).status_code == 200
        c.app.state.service.flush()
        hist = c.get("/api/history/zones/A", params={"hours": 3, "bucket_min": 1}).json()
        assert len(hist["points"]) >= 170
        assert any(d["rule"] == "SOIL_LOW" for d in c.get("/api/decisions").json())
        assert any(a["code"] == "SOIL_DRY" for a in c.get("/api/alerts").json())
        summary = c.get("/api/analytics/summary", params={"hours": 3}).json()
        assert summary["zones"]["A"]["water"]["irrigation_l"] > 0
        for _ in range(3):  # pruning old runs exercises the foreign keys
            c.post("/api/sim/reset", json={})
        assert len(c.get("/api/runs").json()) == 2
