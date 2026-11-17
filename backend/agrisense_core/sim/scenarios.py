"""Scenario injection: weather events, disturbances and equipment / sensor faults.

Timed scenarios are reverted automatically when their duration ends; instant scenarios
(e.g. "dry soil") change the state once and let the physics take over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from agrisense_core.devices.actuators import ActuatorFault
from agrisense_core.devices.sensors import SensorFault
from agrisense_core.sim import psychro

if TYPE_CHECKING:
    from agrisense_core.sim.engine import GreenhouseEngine


@dataclass(frozen=True)
class ScenarioInfo:
    name: str
    description: str
    default_duration_h: float  # 0 = instant
    params: dict[str, Any] = field(default_factory=dict)


CATALOG: dict[str, ScenarioInfo] = {
    s.name: s
    for s in [
        ScenarioInfo("hot_day", "Clear sky and hotter than normal", 12, {"temp_offset_c": 5.0}),
        ScenarioInfo("heatwave", "Several very hot, clear days", 72, {"temp_offset_c": 7.0}),
        ScenarioInfo(
            "rainfall",
            "Rain storm: cooler, humid, refills the tank from the roof",
            2,
            {"rain_mm_h": 10.0},
        ),
        ScenarioInfo("cloudy", "Overcast sky, little sunlight", 24, {"cloud": 0.95}),
        ScenarioInfo("cold_night", "Clear, cold night", 10, {"temp_offset_c": -6.0}),
        ScenarioInfo(
            "humidity_spike",
            "Sudden humidity rise inside a zone",
            0,
            {"zone": None, "rh_pct": 97.0},
        ),
        ScenarioInfo(
            "dry_soil", "Soil moisture drops sharply in a zone", 0, {"zone": None, "vwc": None}
        ),
        ScenarioInfo("water_shortage", "Tank nearly empty", 0, {"level_pct": 5.0}),
        ScenarioInfo("refill_tank", "Tank refilled to a level", 0, {"level_pct": 100.0}),
        ScenarioInfo("pump_failure", "Pump runs but delivers no water", 6, {"fault": "failed"}),
        ScenarioInfo(
            "actuator_fault", "Any actuator fault", 6, {"actuator": None, "fault": "failed"}
        ),
        ScenarioInfo(
            "sensor_failure",
            "Sensor fault: stuck, dropout, spike, drift or offset",
            6,
            {"sensor": None, "fault": "stuck", "magnitude": 0.0},
        ),
    ]
}


@dataclass
class ActiveScenario:
    id: int
    name: str
    params: dict[str, Any]
    started: datetime
    ends: datetime | None


class ScenarioManager:
    def __init__(self, engine: GreenhouseEngine) -> None:
        self.engine = engine
        self.active: list[ActiveScenario] = []
        self.history: list[ActiveScenario] = []
        self._next_id = 1

    def start(self, name: str, duration_h: float | None = None, **params: Any) -> ActiveScenario:
        info = CATALOG.get(name)
        if info is None:
            raise KeyError(f"unknown scenario '{name}'. Available: {', '.join(CATALOG)}")
        unknown = set(params) - set(info.params)
        if unknown:
            raise ValueError(f"scenario '{name}' does not take {sorted(unknown)}")
        merged = {**info.params, **params}
        duration = info.default_duration_h if duration_h is None else duration_h
        now = self.engine.clock.now
        sc = ActiveScenario(
            self._next_id,
            name,
            merged,
            now,
            now + timedelta(hours=duration) if duration > 0 else None,
        )
        self._next_id += 1
        getattr(self, f"_apply_{name}")(merged, revert=False)
        self.history.append(sc)
        if sc.ends is not None:
            self.active.append(sc)
        return sc

    def stop(self, scenario_id: int) -> None:
        for sc in list(self.active):
            if sc.id == scenario_id:
                getattr(self, f"_apply_{sc.name}")(sc.params, revert=True)
                self.active.remove(sc)

    def update(self, now: datetime) -> None:
        for sc in list(self.active):
            if sc.ends is not None and now >= sc.ends:
                self.stop(sc.id)

    def active_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "params": s.params,
                "started": s.started.isoformat(),
                "ends": s.ends.isoformat() if s.ends else None,
            }
            for s in self.active
        ]

    # ------------------------------------------------------------------ helpers

    def _zones(self, zone: str | None):
        if zone is None:
            return list(self.engine.zones.values())
        return [self.engine.zones[zone]]

    @property
    def _ov(self):
        return self.engine.weather.overrides

    # ------------------------------------------------------------------ weather scenarios

    def _apply_hot_day(self, p, revert):
        self._ov.temp_offset_c = 0.0 if revert else p["temp_offset_c"]
        self._ov.cloud = None if revert else 0.1

    def _apply_heatwave(self, p, revert):
        self._ov.temp_offset_c = 0.0 if revert else p["temp_offset_c"]
        self._ov.cloud = None if revert else 0.05
        self._ov.dewpoint_offset_c = 0.0 if revert else 1.0

    def _apply_rainfall(self, p, revert):
        self._ov.rain_mm_h = None if revert else p["rain_mm_h"]

    def _apply_cloudy(self, p, revert):
        self._ov.cloud = None if revert else p["cloud"]

    def _apply_cold_night(self, p, revert):
        self._ov.temp_offset_c = 0.0 if revert else p["temp_offset_c"]
        self._ov.cloud = None if revert else 0.0

    # ------------------------------------------------------------------ state disturbances

    def _apply_humidity_spike(self, p, revert):
        if revert:
            return
        for zm in self._zones(p["zone"]):
            zm.state.chi = psychro.concentration_from_rh(p["rh_pct"], zm.state.temp_c)
            zm.refresh_air()

    def _apply_dry_soil(self, p, revert):
        if revert:
            return
        for zm in self._zones(p["zone"]):
            target = p["vwc"] if p["vwc"] is not None else zm.cfg.soil.wilting_point + 0.03
            zm.state.vwc = target

    def _apply_water_shortage(self, p, revert):
        if not revert:
            t = self.engine.tank
            t.volume_l = t.capacity_l * p["level_pct"] / 100

    _apply_refill_tank = _apply_water_shortage

    # ------------------------------------------------------------------ faults

    def _apply_pump_failure(self, p, revert):
        self._apply_actuator_fault(
            {"actuator": self.engine.gh.pump.id, "fault": p["fault"]}, revert
        )

    def _apply_actuator_fault(self, p, revert):
        act = self.engine.actuators[p["actuator"]]
        act.fault = None if revert else ActuatorFault(p["fault"])

    def _apply_sensor_failure(self, p, revert):
        sensor = self.engine.sensors[p["sensor"]]
        if revert:
            sensor.inject_fault(None)
        else:
            sensor.inject_fault(SensorFault(p["fault"]), p["magnitude"], self.engine.clock.now)
