"""Phase 4 intelligence: sensor anomalies, irrigation forecasts, crop advice and model results."""

import asyncio
import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from agrisense_core.intelligence.advisor import advise
from app.api.deps import get_service
from app.services import analytics
from app.services.simulation import SimulationService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])
Svc = Depends(get_service)


def _report(svc: SimulationService) -> dict[str, Any] | None:
    path = svc.intel.ml_dir / "reports" / "phase4_results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@router.get("/status")
async def status(svc: SimulationService = Svc) -> dict[str, Any]:
    return {**svc.intel.status(), "report_available": _report(svc) is not None}


@router.post("/reload")
async def reload(svc: SimulationService = Svc) -> dict[str, Any]:
    """Load newly trained models without restarting the server."""
    svc.intel.reload()
    return svc.intel.status()


@router.get("/anomalies")
async def anomalies(svc: SimulationService = Svc) -> list[dict[str, Any]]:
    return svc.intel.anomalies()


@router.get("/forecast")
async def forecast(svc: SimulationService = Svc) -> list[dict[str, Any]]:
    return svc.intel.forecast()


@router.get("/advice")
async def advice(
    hours: float = Query(24.0, gt=0, le=24 * 30), svc: SimulationService = Svc
) -> list[dict[str, Any]]:
    run, now, cfg = svc.run_id, svc.now, svc.config
    if not svc.db.remote:
        await svc.flush_async()

    def work() -> dict[str, Any]:
        with svc.db.read_session() as s:
            return analytics.summary(s, run, now - timedelta(hours=hours), now, cfg)

    summ = await asyncio.to_thread(work)
    report = _report(svc) or {}
    opt = report.get("optimisation", {}).get("validation")
    return advise(
        summ,
        svc.config,
        live=svc.live(decisions=0),
        anomalies=svc.intel.anomalies(),
        optimisation=opt,
    )


@router.get("/report")
async def report(svc: SimulationService = Svc) -> dict[str, Any] | None:
    """Offline evaluation results written by `agrisense ml all`."""
    return _report(svc)
