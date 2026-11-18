"""Runs the greenhouse (simulator + controller) inside the API server and stores its history.

Everything runs on the asyncio event loop thread: the background loop advances the simulation
in small slices and every API handler is `async`, so no locking is needed. The number of physics
steps per slice is capped so the server stays responsive at high simulation speeds; if the
simulation cannot keep up, `lagging` is reported instead of freezing the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from agrisense_core.config import AgriSenseConfig, load_config
from agrisense_core.intelligence.live import LiveIntelligence
from agrisense_core.intelligence.pipeline import DEFAULT_ML_DIR
from agrisense_core.runtime import GreenhouseRuntime
from agrisense_core.sim.scenarios import CATALOG
from app.config import Settings
from app.db.models import (
    ActuatorState,
    AlertRow,
    DecisionRow,
    GreenhouseState,
    Run,
    SensorReading,
    ZoneState,
)
from app.db.session import Database

MAX_ADVANCE_H = 72.0
log = logging.getLogger("agrisense.storage")


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


class SimulationService:
    def __init__(
        self, settings: Settings, db: Database, config: AgriSenseConfig | None = None
    ) -> None:
        self.settings = settings
        self.db = db
        self.config = config or load_config(settings.config_dir)
        self.paused = False
        self.lagging = False
        self._task: asyncio.Task | None = None
        self._rows: list[Any] = []
        self._pending_decisions: list[dict[str, Any]] = []
        self._pending_alerts: dict[int, dict[str, Any]] = {}
        self._write_lock = threading.Lock()
        self._writer: asyncio.Task | None = None
        self._last_write = 0.0
        self.write_errors = 0
        self.last_write = {"rows": 0, "seconds": 0.0, "at": None}
        self._prune_before: datetime | None = None
        ml_dir = Path(settings.ml_dir) if settings.ml_dir else DEFAULT_ML_DIR
        self.intel = LiveIntelligence(self.config, ml_dir)
        self.reset(settings.seed)

    # ------------------------------------------------------------------ lifecycle

    def reset(self, seed: int | None = None) -> int:
        """Start a fresh simulation run (new history) and prune old runs."""
        self.flush()
        rt = GreenhouseRuntime(
            self.config, seed=seed, speed=self.settings.sim_speed, step_s=self.settings.sim_step_s
        )
        self.runtime = rt
        self._pending_decisions.clear()
        self._pending_alerts.clear()
        gh = self.config.greenhouse.id
        rt.engine.bus.subscribe(
            f"agrisense/{gh}/control/decision", lambda _t, p: self._pending_decisions.append(p)
        )
        rt.engine.bus.subscribe(
            f"agrisense/{gh}/control/alert",
            lambda _t, p: self._pending_alerts.__setitem__(p["id"], p),
        )
        with self.db.session() as s:
            run = Run(
                created_at=datetime.now(),
                seed=rt.engine.seed,
                sim_start=rt.now,
                greenhouse=self.config.greenhouse.name,
            )
            s.add(run)
            s.commit()
            self.run_id = run.id
            old = s.scalars(
                select(Run.id).order_by(Run.id.desc()).offset(self.settings.keep_runs)
            ).all()
            if old:
                for table in (
                    ZoneState,
                    GreenhouseState,
                    ActuatorState,
                    SensorReading,
                    DecisionRow,
                    AlertRow,
                ):
                    s.execute(delete(table).where(table.run_id.in_(old)))
                s.execute(delete(Run).where(Run.id.in_(old)))
                s.commit()
        self._next_state = rt.now
        self._next_readings = rt.now
        self._next_obs = rt.now
        self._next_prune = rt.now + timedelta(days=1)
        self.intel.reset()
        return self.run_id

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush_async()

    async def _loop(self) -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(self.settings.loop_interval_s)
            now = time.perf_counter()
            real_dt, last = now - last, now
            if not self.paused:
                self._advance_real(real_dt)
            self._maybe_start_writer(now)

    def _maybe_start_writer(self, now: float) -> None:
        """Write pending history in a background thread so slow (remote) databases never block
        the simulation; at most one write is in flight, and failed batches are re-queued."""
        if self._writer is not None:
            if not self._writer.done():
                return
            failed = self._writer.result()
            self._writer = None
            if failed is not None:
                self._requeue(failed)
        if now - self._last_write < self.settings.flush_every_s:
            return
        batch = self._take_batch()
        if batch is not None:
            self._last_write = now
            self._writer = asyncio.create_task(asyncio.to_thread(self._write_safely, batch))

    # ------------------------------------------------------------------ stepping

    @property
    def now(self) -> datetime:
        return self.runtime.now

    def _advance_real(self, real_dt: float) -> None:
        steps = self.runtime.engine.clock.steps_for_real(real_dt)
        cap = self.settings.max_steps_per_loop
        self.lagging = steps > cap
        for _ in range(min(steps, cap)):
            self._step()

    def advance(self, sim_seconds: float) -> None:
        """Fast-forward by simulated time as quickly as possible (also used by tests)."""
        for _ in range(int(round(sim_seconds / self.runtime.engine.clock.step_s))):
            self._step()

    def _step(self) -> None:
        self.runtime.step()
        now = self.runtime.now
        if now >= self._next_state:
            self._collect_states(now)
            self._next_state = now + timedelta(seconds=self.settings.state_every_s)
        if now >= self._next_readings:
            self._collect_readings(now)
            self._next_readings = now + timedelta(seconds=self.settings.readings_every_s)
        if now >= self._next_prune:  # retention: drop history older than retain_days, daily
            self._prune_before = now - timedelta(days=self.settings.retain_days)
            self._next_prune = now + timedelta(days=1)
        if now >= self._next_obs:  # one observation per simulated minute for the ML models
            self.intel.record(self.runtime)
            self._next_obs = now + timedelta(seconds=60)

    def set_speed(self, speed: float) -> None:
        self.runtime.engine.clock.speed = speed

    # ------------------------------------------------------------------ persistence

    def _collect_states(self, ts: datetime) -> None:
        e, ctl, run = self.runtime.engine, self.runtime.controller, self.run_id
        acts = e.actuators
        for zid, zm in e.zones.items():
            s = zm.state
            m = ctl.zones[zid].measured if ctl else {}

            def lvl(kind: str, zid: str = zid) -> float:
                a = acts.get(f"{zid}.{kind}")
                return a.actual if a else 0.0

            self._rows.append(
                ZoneState(
                    run_id=run,
                    ts=ts,
                    zone_id=zid,
                    temp_c=s.temp_c,
                    rh_pct=s.rh_pct,
                    vpd_kpa=s.vpd_kpa,
                    co2_ppm=s.co2_ppm,
                    vwc=s.vwc,
                    soil_temp_c=s.soil_temp_c,
                    par_umol=s.par_umol,
                    dli_mol=s.dli_mol,
                    et_mm_h=s.transpiration_mm_h,
                    measured_temp_c=m.get("temp"),
                    measured_rh_pct=m.get("rh"),
                    measured_vwc_pct=m.get("vwc_pct"),
                    measured_lux=m.get("lux"),
                    fan=lvl("fan"),
                    valve=lvl("valve"),
                    light=lvl("light"),
                    mister=lvl("mister"),
                    irrigation_l_total=s.totals["irrigation_l"],
                    et_l_total=s.totals["et_l"],
                )
            )
        w = e.weather.state
        self._rows.append(
            GreenhouseState(
                run_id=run,
                ts=ts,
                out_temp_c=w.temp_c,
                out_rh_pct=w.rh_pct,
                solar_w_m2=w.solar_w_m2,
                cloud=w.cloud,
                wind_ms=w.wind_ms,
                rain_mm_h=w.rain_mm_h,
                tank_pct=e.tank.level_frac * 100,
                tank_inflow_l_total=e.tank.inflow_total_l,
                alerts_active=len(ctl.alerts.active) if ctl else 0,
            )
        )
        for aid, a in acts.items():
            self._rows.append(
                ActuatorState(
                    run_id=run,
                    ts=ts,
                    actuator_id=aid,
                    kind=a.kind,
                    zone_id=a.zone_id,
                    level=a.actual,
                    energy_wh_total=a.energy_wh,
                    runtime_s_total=a.runtime_s,
                    starts_total=a.starts,
                )
            )

    def _collect_readings(self, ts: datetime) -> None:
        for (sid, q), r in self.runtime.engine.latest.items():
            self._rows.append(
                SensorReading(
                    run_id=self.run_id,
                    ts=ts,
                    sensor_id=sid,
                    zone_id=r.zone_id,
                    quantity=q,
                    value=r.value,
                    raw=r.raw,
                    unit=r.unit,
                    quality=str(r.quality),
                )
            )

    def _take_batch(self) -> tuple | None:
        if not (
            self._rows or self._pending_decisions or self._pending_alerts or self._prune_before
        ):
            return None
        batch = (
            self.run_id,
            self._rows,
            self._pending_decisions,
            self._pending_alerts,
            self._prune_before,
        )
        self._rows, self._pending_decisions, self._pending_alerts = [], [], {}
        self._prune_before = None
        return batch

    def _requeue(self, batch: tuple) -> None:
        _, rows, decisions, alerts, prune = batch
        self._prune_before = self._prune_before or prune
        self._rows[:0] = rows
        self._pending_decisions[:0] = decisions
        for k, v in alerts.items():
            self._pending_alerts.setdefault(k, v)

    def _write_safely(self, batch: tuple) -> tuple | None:
        """Runs in a worker thread. Returns the batch if it could not be written."""
        try:
            self._write(batch)
            return None
        except Exception as exc:  # network blip, database restart, ...
            self.write_errors += 1
            log.warning("could not store history (will retry): %s", exc)
            return batch

    def _write(self, batch: tuple) -> None:
        run, rows, decisions, alerts, prune_before = batch
        started = time.perf_counter()
        with self._write_lock, self.db.session() as s:
            s.add_all(rows)
            for d in decisions:
                s.add(
                    DecisionRow(
                        run_id=run,
                        ts=datetime.fromisoformat(d["ts"]),
                        actuator_id=d["actuator_id"],
                        zone_id=d["zone_id"],
                        from_level=d["from_level"],
                        to_level=d["to_level"],
                        rule=d["rule"],
                        source=d["source"],
                        message=d["message"],
                    )
                )
            if alerts:
                # One query for all alerts in the batch (each round trip is slow on a remote DB).
                existing = {
                    r.alert_id: r
                    for r in s.scalars(
                        select(AlertRow).where(
                            AlertRow.run_id == run, AlertRow.alert_id.in_(list(alerts))
                        )
                    )
                }
                for a in alerts.values():
                    cleared = datetime.fromisoformat(a["cleared_at"]) if a["cleared_at"] else None
                    row = existing.get(a["id"])
                    if row is None:
                        s.add(
                            AlertRow(
                                run_id=run,
                                alert_id=a["id"],
                                code=a["code"],
                                severity=a["severity"],
                                message=a["message"],
                                zone_id=a["zone_id"],
                                subject=a["subject"],
                                latched=a["latched"],
                                raised_at=datetime.fromisoformat(a["raised_at"]),
                                cleared_at=cleared,
                            )
                        )
                    else:
                        row.cleared_at = cleared
            if prune_before is not None:
                for table in (
                    ZoneState,
                    GreenhouseState,
                    ActuatorState,
                    SensorReading,
                    DecisionRow,
                ):
                    s.execute(delete(table).where(table.run_id == run, table.ts < prune_before))
            s.commit()
        self.last_write = {
            "rows": len(rows) + len(decisions) + len(alerts),
            "seconds": round(time.perf_counter() - started, 2),
            "at": datetime.now().isoformat(timespec="seconds"),
        }

    def flush(self) -> None:
        """Write everything pending now, on the calling thread (startup, reset, tests)."""
        batch = self._take_batch()
        if batch is not None:
            self._write(batch)

    async def flush_async(self) -> None:
        """Make all history so far queryable without blocking the event loop."""
        if self._writer is not None:
            failed = await self._writer
            self._writer = None
            if failed is not None:
                self._requeue(failed)
        batch = self._take_batch()
        if batch is not None:
            failed = await asyncio.to_thread(self._write_safely, batch)
            if failed is not None:
                self._requeue(failed)

    # ------------------------------------------------------------------ views

    def describe(self) -> dict[str, Any]:
        """Static configuration the dashboard needs: zones, targets, equipment, sensors."""
        cfg = self.config
        e = self.runtime.engine
        zones = []
        for z in cfg.greenhouse.zones:
            crop = cfg.crops[z.crop]
            zones.append(
                {
                    "id": z.id,
                    "name": z.name,
                    "crop": z.crop,
                    "crop_name": crop.display_name,
                    "stage": z.stage,
                    "area_m2": z.floor_area_m2,
                    "targets": crop.targets.model_dump(),
                    "soil": z.soil.model_dump(),
                    "actuators": [a for a in e.actuators if a.startswith(f"{z.id}.")],
                    "sensors": [s for s in e.sensors if s.startswith(f"{z.id}.")],
                }
            )
        return {
            "greenhouse": {
                "id": cfg.greenhouse.id,
                "name": cfg.greenhouse.name,
                "location": cfg.greenhouse.location.model_dump(),
                "tank_capacity_l": cfg.greenhouse.tank.capacity_l,
            },
            "zones": zones,
            "actuators": {
                aid: {"kind": a.kind, "zone_id": a.zone_id, "power_w": a.power_w}
                for aid, a in e.actuators.items()
            },
            "scenarios": [
                {
                    "name": s.name,
                    "description": s.description,
                    "default_duration_h": s.default_duration_h,
                    "params": s.params,
                }
                for s in CATALOG.values()
            ],
            "control": {
                "day_window": cfg.control.day_window,
                "lighting_window": cfg.control.lighting.window,
            },
        }

    def live(self, decisions: int = 20) -> dict[str, Any]:
        """Compact live state for the WebSocket and the overview page."""
        e, ctl = self.runtime.engine, self.runtime.controller
        w = e.weather.state
        zones = {}
        for zid, zm in e.zones.items():
            s = zm.state
            zc = ctl.zones[zid] if ctl else None
            zones[zid] = {
                "true": {
                    "temp_c": _r(s.temp_c),
                    "rh_pct": _r(s.rh_pct, 1),
                    "vpd_kpa": _r(s.vpd_kpa),
                    "co2_ppm": _r(s.co2_ppm, 0),
                    "vwc_pct": _r(s.vwc * 100),
                    "par_umol": _r(s.par_umol, 0),
                    "dli_mol": _r(s.dli_mol),
                    "soil_temp_c": _r(s.soil_temp_c),
                    "et_mm_h": _r(s.transpiration_mm_h, 3),
                    "water_stress_ks": _r(s.water_stress_ks),
                },
                "measured": {k: _r(v) for k, v in zc.measured.items()} if zc else {},
                "irrigation": zc.irrigation if zc else None,
                "fan_stage": zc.fan_stage if zc else None,
                "dli_estimate": _r(zc.dli_estimate) if zc else None,
                "irrigation_lpm": _r(e.irrigation_lps[zid] * 60),
            }
        actuators = {}
        for aid, a in e.actuators.items():
            info: dict[str, Any] = {
                "kind": a.kind,
                "zone_id": a.zone_id,
                "level": a.actual,
                "fault": str(a.fault) if a.fault else None,
                "energy_wh": round(a.energy_wh, 1),
            }
            if ctl:
                p, m = ctl.last[aid], ctl.modes[aid]
                info.update(
                    {
                        "rule": p.rule,
                        "reason": p.reason,
                        "source": p.source,
                        "mode": str(m.mode),
                        "override_until": m.expires_at.isoformat() if m.expires_at else None,
                    }
                )
            actuators[aid] = info
        return {
            "time": e.now.isoformat(),
            "run_id": self.run_id,
            "speed": e.clock.speed,
            "paused": self.paused,
            "lagging": self.lagging,
            "control": ctl is not None,
            "emergency_stop": ctl.estop if ctl else False,
            "weather": {
                "temp_c": _r(w.temp_c),
                "rh_pct": _r(w.rh_pct, 1),
                "solar_w_m2": _r(w.solar_w_m2, 0),
                "cloud": _r(w.cloud),
                "wind_ms": _r(w.wind_ms, 1),
                "rain_mm_h": _r(w.rain_mm_h, 1),
            },
            "tank": {
                "level_pct": _r(e.tank.level_frac * 100, 1),
                "volume_l": _r(e.tank.volume_l, 0),
            },
            "zones": zones,
            "actuators": actuators,
            "alerts": sorted(
                (a.to_message() for a in ctl.alerts.active.values()),
                key=lambda a: a["raised_at"],
                reverse=True,
            )
            if ctl
            else [],
            "decisions": [d.to_message() for d in list(ctl.decisions)[-decisions:]][::-1]
            if ctl
            else [],
            "scenarios": e.scenarios.active_summary(),
            "storage": {
                "remote": self.db.remote,
                "pending_rows": len(self._rows) + len(self._pending_decisions),
                "writing": self._writer is not None and not self._writer.done(),
                "last_write": self.last_write,
                "write_errors": self.write_errors,
            },
        }

    def sensors(self) -> list[dict[str, Any]]:
        e, ctl = self.runtime.engine, self.runtime.controller
        out = []
        for (sid, q), r in sorted(e.latest.items()):
            ch = ctl.health.channel(sid, q) if ctl else None
            sensor = e.sensors.get(sid)
            out.append(
                {
                    "sensor_id": sid,
                    "zone_id": r.zone_id,
                    "quantity": q,
                    "model": sensor.model if sensor else None,
                    "value": r.value,
                    "raw": r.raw,
                    "unit": r.unit,
                    "quality": str(r.quality),
                    "ts": r.ts.isoformat(),
                    "health": str(ch.health) if ch else None,
                    "fault": str(sensor.fault) if sensor and sensor.fault else None,
                }
            )
        return out
