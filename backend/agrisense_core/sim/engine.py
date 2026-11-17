"""Greenhouse engine: ties weather, zone physics, hydraulics, actuators and sensors together.

One call to `step()` advances simulated time by one fixed physics step. Sensors sample on
their own intervals and publish readings to the message bus using MQTT-style topics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from agrisense_core.config import AgriSenseConfig, SensorInstall, load_config
from agrisense_core.devices.actuators import SimActuator
from agrisense_core.devices.bus import MessageBus
from agrisense_core.devices.interfaces import (
    Command,
    Reading,
    actuator_set_topic,
    actuator_state_topic,
    sensor_topic,
)
from agrisense_core.devices.sensors import SENSOR_MODELS, SimSensor
from agrisense_core.sim.clock import SimClock
from agrisense_core.sim.physics import ZoneInputs, ZoneModel
from agrisense_core.sim.scenarios import ScenarioManager
from agrisense_core.sim.weather import WeatherModel


@dataclass
class Tank:
    capacity_l: float
    volume_l: float
    height_m: float
    inflow_total_l: float = 0.0
    outflow_total_l: float = 0.0
    overflow_total_l: float = 0.0

    @property
    def level_frac(self) -> float:
        return self.volume_l / self.capacity_l


class GreenhouseEngine:
    def __init__(
        self,
        config: AgriSenseConfig | None = None,
        seed: int | None = None,
        speed: float = 1.0,
        step_s: float | None = None,
    ) -> None:
        self.config = config or load_config()
        gh = self.config.greenhouse
        self.gh = gh
        self.seed = gh.simulation.seed if seed is None else seed
        seeds = np.random.SeedSequence(self.seed)
        self._seed_iter = iter(seeds.spawn(1000))

        self.clock = SimClock(gh.simulation.start, step_s or gh.simulation.step_s, speed)
        self.bus = MessageBus()
        self.weather = WeatherModel(gh.weather, gh.location, self._rng())
        self.weather.step(0.0, self.clock.hour_of_day, self.clock.day_of_year)

        self.zones: dict[str, ZoneModel] = {}
        for z in gh.zones:
            model = ZoneModel(z, self.config.crop_stage(z), gh)
            model.initialise(self.weather.state)
            self.zones[z.id] = model

        self.tank = Tank(
            gh.tank.capacity_l,
            gh.tank.capacity_l * gh.tank.initial_level_pct / 100,
            gh.tank.height_m,
        )
        self.flow_total_l = 0.0
        self.irrigation_lps: dict[str, float] = {z: 0.0 for z in self.zones}

        self.actuators: dict[str, SimActuator] = {}
        self._build_actuators()
        self.sensors: dict[str, SimSensor] = {}
        self._build_sensors()

        self.latest: dict[tuple[str, str], Reading] = {}
        self.scenarios = ScenarioManager(self)
        self._day = self.clock.now.date()
        self.bus.subscribe(f"agrisense/{gh.id}/+/actuator/+/set", self._on_command_message)

    # ------------------------------------------------------------------ construction

    def _rng(self) -> np.random.Generator:
        return np.random.default_rng(next(self._seed_iter))

    def _add(self, act: SimActuator) -> None:
        self.actuators[act.actuator_id] = act

    def _build_actuators(self) -> None:
        p = self.gh.pump
        self._add(SimActuator(p.id, "pump", None, p.power_w, p.startup_delay_s))
        for z in self.gh.zones:
            e = z.equipment
            self._add(
                SimActuator(
                    f"{z.id}.fan",
                    "fan",
                    z.id,
                    e.fan.power_w * e.fan.count,
                    e.fan.startup_delay_s,
                    proportional=True,
                )
            )
            self._add(
                SimActuator(
                    f"{z.id}.valve", "valve", z.id, e.valve.power_w, e.valve.startup_delay_s
                )
            )
            if e.grow_light:
                self._add(
                    SimActuator(
                        f"{z.id}.light",
                        "grow_light",
                        z.id,
                        e.grow_light.power_w,
                        e.grow_light.startup_delay_s,
                    )
                )
            if e.mister:
                self._add(
                    SimActuator(
                        f"{z.id}.mister", "mister", z.id, e.mister.power_w, e.mister.startup_delay_s
                    )
                )
            if e.heater:
                self._add(
                    SimActuator(
                        f"{z.id}.heater",
                        "heater",
                        z.id,
                        e.heater.power_w,
                        e.heater.startup_delay_s,
                        proportional=True,
                    )
                )

    def _zone_truth(self, zone_id: str, vwc_offset: float):
        def truth() -> dict[str, float]:
            s = self.zones[zone_id].state
            return {
                "air_temp": s.temp_c,
                "air_rh": s.rh_pct,
                "soil_vwc": max(0.0, s.vwc + vwc_offset),
                "soil_temp": s.soil_temp_c,
                "lux": s.lux,
                "co2_ppm": s.co2_ppm,
            }

        return truth

    def _gh_truth(self) -> dict[str, float]:
        w = self.weather.state
        return {
            "air_temp": w.temp_c,
            "air_rh": w.rh_pct,
            "tank_level_frac": self.tank.level_frac,
            "tank_height_m": self.tank.height_m,
            "flow_total_l": self.flow_total_l,
        }

    def _make_sensor(
        self, inst: SensorInstall, sensor_id: str, zone_id: str | None, truth
    ) -> SimSensor | None:
        if inst.source != "sim":
            return None  # real device: values arrive over MQTT (Phase 6)
        cls = SENSOR_MODELS[inst.model]
        return cls(sensor_id, zone_id, inst.sample_interval_s, truth, self._rng(), inst.calibration)

    def _build_sensors(self) -> None:
        layout = self.config.sensors
        spatial = self._rng()
        for z in self.gh.zones:
            for inst in layout.zone:
                # Soil moisture varies across a bed; each probe sees a slightly different value.
                offset = float(spatial.normal(0, 0.008)) if inst.model == "capacitive_soil" else 0.0
                s = self._make_sensor(
                    inst, f"{z.id}.{inst.id}", z.id, self._zone_truth(z.id, offset)
                )
                if s:
                    self.sensors[s.sensor_id] = s
        for inst in layout.greenhouse:
            s = self._make_sensor(inst, inst.id, None, self._gh_truth)
            if s:
                self.sensors[s.sensor_id] = s

    # ------------------------------------------------------------------ commands

    def command(
        self, actuator_id: str, level: float, reason: str = "manual", ttl_s: float | None = None
    ) -> None:
        if actuator_id not in self.actuators:
            raise KeyError(f"unknown actuator '{actuator_id}'")
        self.actuators[actuator_id].command(
            Command(actuator_id, level, reason, ttl_s), self.clock.now
        )

    def _on_command_message(self, topic: str, payload: dict[str, Any]) -> None:
        actuator_id = topic.split("/")[-2]
        if actuator_id in self.actuators:
            self.command(
                actuator_id,
                float(payload.get("level", 0)),
                payload.get("reason", "bus"),
                payload.get("ttl_s"),
            )

    def publish_command(
        self, actuator_id: str, level: float, reason: str = "manual", ttl_s: float | None = None
    ) -> None:
        """Send a command through the bus, exactly as a remote controller would."""
        act = self.actuators[actuator_id]
        self.bus.publish(
            actuator_set_topic(self.gh.id, act.zone_id, actuator_id),
            {"level": level, "reason": reason, "ttl_s": ttl_s},
            retain=False,
        )

    # ------------------------------------------------------------------ simulation

    def _output(self, actuator_id: str) -> float:
        a = self.actuators.get(actuator_id)
        return a.output if a else 0.0

    def _hydraulics(self, dt: float) -> dict[str, float]:
        """Distribute pump flow to open zone valves, limited by pump capacity and tank water."""
        demand = {}
        for zid, zm in self.zones.items():
            if self._output(f"{zid}.valve") > 0:
                em = zm.cfg.equipment.emitters
                demand[zid] = em.count * em.flow_lph / 3600
        flows = {zid: 0.0 for zid in self.zones}
        pump_on = self._output(self.gh.pump.id) > 0
        total_demand = sum(demand.values())
        if pump_on and total_demand > 0 and self.tank.volume_l > 0:
            supply = min(total_demand, self.gh.pump.max_flow_lpm / 60, self.tank.volume_l / dt)
            for zid, d in demand.items():
                flows[zid] = supply * d / total_demand
        return flows

    def step(self) -> list[Reading]:
        dt = self.clock.step_s
        now = self.clock.now
        self.scenarios.update(now)
        w = self.weather.step(dt, self.clock.hour_of_day, self.clock.day_of_year)
        for act in self.actuators.values():
            act.update(dt, now)

        flows = self._hydraulics(dt)
        irrigation_total = sum(flows.values())

        mist_total = 0.0
        for zid, zm in self.zones.items():
            e = zm.cfg.equipment
            mist_lps = 0.0
            if e.mister and self._output(f"{zid}.mister") > 0 and self.tank.volume_l > 0:
                mist_lps = e.mister.flow_lph / 3600
            mist_total += mist_lps
            light = self.actuators.get(f"{zid}.light")
            heater = self.actuators.get(f"{zid}.heater")
            inputs = ZoneInputs(
                fan_flow_m3s=self._output(f"{zid}.fan") * e.fan.count * e.fan.airflow_m3h / 3600,
                irrigation_lps=flows[zid],
                lamp_ppfd=(light.output * e.grow_light.ppfd_umol_m2s) if light else 0.0,
                lamp_power_w=(light.actual * e.grow_light.power_w) if light else 0.0,
                mist_lps=mist_lps,
                heater_w=(heater.output * e.heater.power_w) if heater else 0.0,
            )
            zm.step(dt, w, inputs)
            self.irrigation_lps[zid] = flows[zid]

        # Tank: pump draw, misting draw, rain-water harvesting from the roof.
        out_l = min(self.tank.volume_l, (irrigation_total + mist_total) * dt)
        t = self.gh.tank
        in_l = w.rain_mm_h / 3600 * t.catchment_area_m2 * t.catchment_efficiency * dt
        self.tank.volume_l += in_l - out_l
        self.tank.outflow_total_l += out_l
        self.tank.inflow_total_l += in_l
        if self.tank.volume_l > self.tank.capacity_l:
            self.tank.overflow_total_l += self.tank.volume_l - self.tank.capacity_l
            self.tank.volume_l = self.tank.capacity_l
        self.flow_total_l += irrigation_total * dt

        self.clock.tick()
        if self.clock.now.date() != self._day:
            self._day = self.clock.now.date()
            for zm in self.zones.values():
                zm.reset_daily()

        return self._sample_sensors()

    def _sample_sensors(self) -> list[Reading]:
        now = self.clock.now
        out: list[Reading] = []
        for sensor in self.sensors.values():
            if sensor.due(now):
                for r in sensor.read(now):
                    out.append(r)
                    self.latest[(r.sensor_id, r.quantity)] = r
                    self.bus.publish(
                        sensor_topic(self.gh.id, r.zone_id, r.sensor_id) + f"/{r.quantity}",
                        r.to_message(),
                    )
        return out

    def run_for(self, sim_seconds: float, callback=None) -> None:
        steps = int(round(sim_seconds / self.clock.step_s))
        for _ in range(steps):
            readings = self.step()
            if callback:
                callback(self, readings)

    def advance_real(self, real_seconds: float) -> list[Reading]:
        """Advance by wall-clock time at the clock's speed multiplier (used by the API)."""
        out: list[Reading] = []
        for _ in range(self.clock.steps_for_real(real_seconds)):
            out.extend(self.step())
        return out

    # ------------------------------------------------------------------ reporting

    @property
    def now(self) -> datetime:
        return self.clock.now

    def publish_actuator_states(self) -> None:
        for act in self.actuators.values():
            st = act.status()
            self.bus.publish(
                actuator_state_topic(self.gh.id, act.zone_id, act.actuator_id),
                {
                    "level": st.actual,
                    "commanded": st.commanded,
                    "confirmed": st.actual == st.commanded and st.fault is None,
                },
            )

    def snapshot(self) -> dict[str, Any]:
        w = self.weather.state
        zones = {}
        for zid, zm in self.zones.items():
            s = zm.state
            zones[zid] = {
                "name": zm.cfg.name,
                "crop": zm.cfg.crop,
                "stage": zm.cfg.stage,
                "true": {
                    "air_temp_c": round(s.temp_c, 3),
                    "rh_pct": round(s.rh_pct, 2),
                    "vpd_kpa": round(s.vpd_kpa, 3),
                    "co2_ppm": round(s.co2_ppm, 1),
                    "soil_vwc": round(s.vwc, 4),
                    "soil_temp_c": round(s.soil_temp_c, 2),
                    "par_umol": round(s.par_umol, 1),
                    "lux": round(s.lux),
                    "dli_mol": round(s.dli_mol, 3),
                    "transpiration_mm_h": round(s.transpiration_mm_h, 4),
                    "et_mm_today": round(s.et_mm_today, 3),
                    "water_stress_ks": round(s.water_stress_ks, 3),
                    "ventilation_ach": round(s.ventilation_ach, 1),
                    "condensing": s.condensing,
                },
                "irrigation_lpm": round(self.irrigation_lps[zid] * 60, 3),
            }
        return {
            "time": self.clock.now.isoformat(),
            "speed": self.clock.speed,
            "weather": {
                k: (round(v, 3) if isinstance(v, float) else v) for k, v in vars(w).items()
            },
            "tank": {
                "volume_l": round(self.tank.volume_l, 2),
                "level_pct": round(self.tank.level_frac * 100, 2),
            },
            "zones": zones,
            "actuators": {aid: vars(a.status()) for aid, a in self.actuators.items()},
            "readings": {f"{sid}/{q}": r.to_message() for (sid, q), r in self.latest.items()},
            "scenarios": self.scenarios.active_summary(),
        }
