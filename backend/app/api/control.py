"""Operator controls: modes, overrides, emergency stop and alarm reset."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agrisense_core.control.modes import Mode
from app.api.deps import get_service
from app.services.simulation import SimulationService

router = APIRouter(tags=["control"])
Svc = Depends(get_service)


class OverrideIn(BaseModel):
    level: float = Field(ge=0, le=1)
    duration_min: float = Field(default=30, gt=0, le=1440)
    by: str = "operator"


class ModeIn(BaseModel):
    mode: Mode
    level: float = Field(default=0, ge=0, le=1)
    by: str = "operator"


class EstopIn(BaseModel):
    reason: str = "operator"
    by: str = "operator"


class AlarmResetIn(BaseModel):
    code: str
    scope: str | None = None


def _controller(svc: SimulationService):
    if svc.runtime.controller is None:
        raise HTTPException(409, "automation controller is disabled")
    return svc.runtime.controller


def _check(svc: SimulationService, actuator_id: str) -> None:
    if actuator_id not in svc.runtime.engine.actuators:
        raise HTTPException(404, f"unknown actuator '{actuator_id}'")


@router.post("/actuators/{actuator_id}/override")
async def override(
    actuator_id: str, body: OverrideIn, svc: SimulationService = Svc
) -> dict[str, Any]:
    _check(svc, actuator_id)
    ctl = _controller(svc)
    ctl.override(actuator_id, body.level, body.duration_min * 60, svc.now, by=body.by)
    m = ctl.modes[actuator_id]
    return {
        "actuator_id": actuator_id,
        "mode": str(m.mode),
        "level": m.manual_level,
        "until": m.expires_at.isoformat(),
    }


@router.post("/actuators/{actuator_id}/mode")
async def set_mode(actuator_id: str, body: ModeIn, svc: SimulationService = Svc) -> dict[str, Any]:
    _check(svc, actuator_id)
    ctl = _controller(svc)
    ctl.set_mode(actuator_id, body.mode, body.level, by=body.by)
    return {
        "actuator_id": actuator_id,
        "mode": str(body.mode),
        "level": ctl.modes[actuator_id].manual_level,
    }


@router.post("/emergency-stop")
async def emergency_stop(body: EstopIn, svc: SimulationService = Svc) -> dict[str, Any]:
    _controller(svc).emergency_stop(svc.now, reason=body.reason, by=body.by)
    return {"emergency_stop": True}


@router.post("/emergency-stop/reset")
async def reset_emergency(svc: SimulationService = Svc) -> dict[str, Any]:
    _controller(svc).reset_emergency(svc.now)
    return {"emergency_stop": False}


@router.post("/alerts/reset")
async def reset_alarm(body: AlarmResetIn, svc: SimulationService = Svc) -> dict[str, Any]:
    ctl = _controller(svc)
    if not ctl.alerts.is_active(body.code, body.scope):
        raise HTTPException(404, f"no active alert {body.code} for {body.scope}")
    ctl.reset_alarm(body.code, svc.now, body.scope)
    return {"cleared": body.code, "scope": body.scope}
