"""Stored history, events and analytics."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import get_service
from app.db.models import AlertRow, DecisionRow, Run
from app.services import analytics
from app.services.simulation import SimulationService

router = APIRouter(tags=["data"])
Svc = Depends(get_service)
Hours = Query(24.0, gt=0, le=24 * 30)


def _run(svc: SimulationService, run_id: int | None) -> int:
    return run_id or svc.run_id


@router.get("/runs")
async def runs(svc: SimulationService = Svc) -> list[dict[str, Any]]:
    with svc.db.session() as s:
        rows = s.scalars(select(Run).order_by(Run.id.desc())).all()
        return [
            {
                "id": r.id,
                "seed": r.seed,
                "sim_start": r.sim_start.isoformat(),
                "created_at": r.created_at.isoformat(),
                "current": r.id == svc.run_id,
            }
            for r in rows
        ]


@router.get("/history/zones/{zone_id}")
async def zone_history(
    zone_id: str,
    hours: float = Hours,
    bucket_min: int | None = Query(None, ge=1),
    run_id: int | None = None,
    svc: SimulationService = Svc,
) -> dict[str, Any]:
    if zone_id not in svc.runtime.engine.zones:
        raise HTTPException(404, f"unknown zone '{zone_id}'")
    svc.flush()
    bucket = bucket_min or analytics.auto_bucket(hours)
    with svc.db.session() as s:
        rows = analytics.zone_history(
            s, _run(svc, run_id), zone_id, svc.now - timedelta(hours=hours), bucket
        )
    return {"zone_id": zone_id, "bucket_min": bucket, "points": rows}


@router.get("/history/greenhouse")
async def greenhouse_history(
    hours: float = Hours,
    bucket_min: int | None = Query(None, ge=1),
    run_id: int | None = None,
    svc: SimulationService = Svc,
) -> dict[str, Any]:
    svc.flush()
    bucket = bucket_min or analytics.auto_bucket(hours)
    with svc.db.session() as s:
        rows = analytics.greenhouse_history(
            s, _run(svc, run_id), svc.now - timedelta(hours=hours), bucket
        )
    return {"bucket_min": bucket, "points": rows}


@router.get("/decisions")
async def decisions(
    zone: str | None = None,
    actuator: str | None = None,
    limit: int = Query(200, ge=1, le=5000),
    run_id: int | None = None,
    svc: SimulationService = Svc,
) -> list[dict[str, Any]]:
    svc.flush()
    q = select(DecisionRow).where(DecisionRow.run_id == _run(svc, run_id))
    if zone:
        q = q.where(DecisionRow.zone_id == zone)
    if actuator:
        q = q.where(DecisionRow.actuator_id == actuator)
    with svc.db.session() as s:
        rows = s.scalars(
            q.order_by(DecisionRow.ts.desc(), DecisionRow.id.desc()).limit(limit)
        ).all()
        return [
            {
                "ts": r.ts.isoformat(),
                "actuator_id": r.actuator_id,
                "zone_id": r.zone_id,
                "from_level": r.from_level,
                "to_level": r.to_level,
                "rule": r.rule,
                "source": r.source,
                "message": r.message,
            }
            for r in rows
        ]


@router.get("/alerts")
async def alerts(
    active_only: bool = False,
    severity: str | None = None,
    limit: int = Query(200, ge=1, le=5000),
    run_id: int | None = None,
    svc: SimulationService = Svc,
) -> list[dict[str, Any]]:
    svc.flush()
    q = select(AlertRow).where(AlertRow.run_id == _run(svc, run_id))
    if active_only:
        q = q.where(AlertRow.cleared_at.is_(None))
    if severity:
        q = q.where(AlertRow.severity == severity)
    with svc.db.session() as s:
        rows = s.scalars(
            q.order_by(AlertRow.raised_at.desc(), AlertRow.id.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.alert_id,
                "code": r.code,
                "severity": r.severity,
                "message": r.message,
                "zone_id": r.zone_id,
                "subject": r.subject,
                "latched": r.latched,
                "raised_at": r.raised_at.isoformat(),
                "cleared_at": r.cleared_at.isoformat() if r.cleared_at else None,
                "active": r.cleared_at is None,
            }
            for r in rows
        ]


@router.get("/analytics/summary")
async def summary(
    hours: float = Hours, run_id: int | None = None, svc: SimulationService = Svc
) -> dict[str, Any]:
    svc.flush()
    with svc.db.session() as s:
        return analytics.summary(
            s, _run(svc, run_id), svc.now - timedelta(hours=hours), svc.now, svc.config
        )
