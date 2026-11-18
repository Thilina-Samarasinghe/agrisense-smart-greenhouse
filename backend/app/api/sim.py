"""Simulation state, speed control and scenarios.

All handlers are `async` so they run on the event loop thread, the same thread that advances
the simulation; this keeps the simulation state consistent without locks.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_service
from app.services.simulation import MAX_ADVANCE_H, SimulationService

router = APIRouter(tags=["simulation"])
Svc = Depends(get_service)


class SpeedIn(BaseModel):
    speed: float = Field(gt=0, le=3600, description="simulated seconds per real second")


class ResetIn(BaseModel):
    seed: int | None = None


class AdvanceIn(BaseModel):
    hours: float = Field(gt=0, le=MAX_ADVANCE_H)


class ScenarioIn(BaseModel):
    name: str
    duration_h: float | None = Field(default=None, ge=0, le=240)
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/config")
async def get_config(svc: SimulationService = Svc) -> dict[str, Any]:
    return svc.describe()


@router.get("/state")
async def get_state(svc: SimulationService = Svc) -> dict[str, Any]:
    return svc.live(decisions=50)


@router.get("/sensors")
async def get_sensors(svc: SimulationService = Svc) -> list[dict[str, Any]]:
    return svc.sensors()


@router.post("/sim/speed")
async def set_speed(body: SpeedIn, svc: SimulationService = Svc) -> dict[str, Any]:
    svc.set_speed(body.speed)
    return {"speed": body.speed}


@router.post("/sim/pause")
async def pause(svc: SimulationService = Svc) -> dict[str, bool]:
    svc.paused = True
    return {"paused": True}


@router.post("/sim/resume")
async def resume(svc: SimulationService = Svc) -> dict[str, bool]:
    svc.paused = False
    return {"paused": False}


@router.post("/sim/reset")
async def reset(body: ResetIn, svc: SimulationService = Svc) -> dict[str, Any]:
    run_id = svc.reset(body.seed)
    return {"run_id": run_id, "seed": svc.runtime.engine.seed, "time": svc.now.isoformat()}


@router.post("/sim/advance")
async def advance(body: AdvanceIn, svc: SimulationService = Svc) -> dict[str, Any]:
    """Fast-forward simulated time (blocks briefly: about 3 s per simulated day)."""
    svc.advance(body.hours * 3600)
    await svc.flush_async()  # store the fast-forwarded history off the event loop
    return {"time": svc.now.isoformat()}


@router.get("/scenarios")
async def list_scenarios(svc: SimulationService = Svc) -> dict[str, Any]:
    return {
        "catalog": svc.describe()["scenarios"],
        "active": svc.runtime.engine.scenarios.active_summary(),
    }


@router.post("/scenarios", status_code=201)
async def start_scenario(body: ScenarioIn, svc: SimulationService = Svc) -> dict[str, Any]:
    try:
        sc = svc.runtime.engine.scenarios.start(body.name, body.duration_h, **body.params)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "id": sc.id,
        "name": sc.name,
        "params": sc.params,
        "started": sc.started.isoformat(),
        "ends": sc.ends.isoformat() if sc.ends else None,
    }


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def stop_scenario(scenario_id: int, svc: SimulationService = Svc) -> None:
    mgr = svc.runtime.engine.scenarios
    if not any(s.id == scenario_id for s in mgr.active):
        raise HTTPException(404, f"no active scenario {scenario_id}")
    mgr.stop(scenario_id)
