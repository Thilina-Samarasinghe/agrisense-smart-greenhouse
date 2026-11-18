"""Greenhouse automation controller.

The controller sees the greenhouse only through sensor readings arriving on the message bus,
exactly as it will with real ESP32 hardware, and acts only by publishing actuator commands
(with a time-to-live, so equipment fails safe if the controller stops).

Every control tick evaluates each actuator through strict priority layers:

    1. Emergency stop      everything OFF, latched until reset
    2. Safety interlocks   may FORCE (high-temperature fans) or BLOCK (dry tank, no flow, ...)
    3. Operator mode       MANUAL level / timed override, or OFF
    4. Automatic rules     crop-specific targets with hysteresis
    5. Minimum on/off      protects motors and relays (automatic decisions only)

Every change of an actuator is recorded as a Decision with the rule and readings behind it.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from agrisense_core.config import AgriSenseConfig, CropTargets, ZoneConfig, hhmm_to_hours
from agrisense_core.control.alerts import Alert, AlertManager, Severity
from agrisense_core.control.health import Health, HealthMonitor
from agrisense_core.control.hysteresis import Hysteresis, MinTimes
from agrisense_core.control.modes import ActuatorMode, Mode
from agrisense_core.devices.bus import MessageBus
from agrisense_core.devices.interfaces import actuator_set_topic
from agrisense_core.sim import psychro
from agrisense_core.units import LUX_PER_UMOL_LED, LUX_PER_UMOL_SUN

MODEL_QUANTITIES: dict[str, tuple[str, ...]] = {
    "sht31": ("air_temp", "air_rh"),
    "capacitive_soil": ("soil_vwc",),
    "ds18b20": ("soil_temp",),
    "bh1750": ("light_lux",),
    "scd30": ("co2_ppm",),
    "jsn_sr04t": ("tank_level",),
    "yf_s201": ("flow_lpm",),
}

KIND_LABEL = {
    "pump": "Pump",
    "valve": "Valve",
    "fan": "Fans",
    "grow_light": "Grow lights",
    "mister": "Mister",
    "heater": "Heater",
}


@dataclass(frozen=True)
class Proposal:
    level: float
    rule: str
    reason: str
    source: str = "auto"  # auto | manual | mode | interlock | estop


@dataclass
class Decision:
    ts: datetime
    actuator_id: str
    zone_id: str | None
    from_level: float
    to_level: float
    rule: str
    source: str
    message: str

    def to_message(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


@dataclass
class ZoneControl:
    """Per-zone controller state."""

    cfg: ZoneConfig
    targets: CropTargets
    air: str | None
    soil: list[str]
    light: str | None
    actuators: dict[str, str]  # kind -> actuator id
    fan_stage: int = 0
    rh_vent: Hysteresis = field(default_factory=lambda: Hysteresis(1e9, 1e9))
    outside_drier: bool = False
    humidity_venting: bool = False
    mist_mode: str | None = None
    fog_cooling_until: datetime | None = None
    heater: Hysteresis = field(default_factory=lambda: Hysteresis(-1e9, -1e9, rising=False))
    irrigation: str = "idle"  # idle | watering | soak | fallback
    irrigation_started: datetime | None = None
    soak_until: datetime | None = None
    last_irrigation_end: datetime | None = None
    light_on: bool = False
    dli_estimate: float = 0.0
    dli_date: date | None = None
    temp_violation_since: datetime | None = None
    rh_violation_since: datetime | None = None
    violation_s: dict[str, float] = field(
        default_factory=lambda: {"temp": 0.0, "rh": 0.0, "vwc": 0.0}
    )
    measured: dict[str, float | None] = field(default_factory=dict)


def _in_window(hour: float, window: tuple[float, float]) -> bool:
    start, end = window
    return start <= hour < end if start <= end else (hour >= start or hour < end)


def _fmt_level(level: float) -> str:
    if level <= 0:
        return "OFF"
    return "ON" if level >= 1 else f"ON {level:.0%}"


class GreenhouseController:
    def __init__(
        self,
        config: AgriSenseConfig,
        bus: MessageBus | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
        decision_log_size: int = 5000,
    ) -> None:
        self.config = config
        self.gh = config.greenhouse
        self.ctl = config.control
        self.health = HealthMonitor(self.ctl.sensors)
        self.alerts = AlertManager(on_change=self._publish_alert)
        self.decisions: deque[Decision] = deque(maxlen=decision_log_size)
        self.now: datetime | None = None
        self.estop = False
        self.estop_reason = ""

        self._bus = bus
        self._publish = publish or (bus.publish if bus else None)
        self.kinds: dict[str, str] = {}
        self.actuator_zone: dict[str, str | None] = {}
        self.zones: dict[str, ZoneControl] = {}
        self._build()
        self.modes = {aid: ActuatorMode() for aid in self.kinds}
        min_times = self.ctl.min_times_s
        self.timing = {
            aid: MinTimes(*min_times.get(kind, (0.0, 0.0))) for aid, kind in self.kinds.items()
        }
        self.last: dict[str, Proposal] = {
            aid: Proposal(0.0, "INIT", "startup") for aid in self.kinds
        }

        self._tank_lockout = False
        self._pump_cooldown_until: datetime | None = None
        self._high_temp: dict[str, bool] = {z: False for z in self.zones}
        self._last_tick: datetime | None = None

        if bus is not None:
            bus.subscribe(f"agrisense/{self.gh.id}/+/sensor/#", lambda _t, p: self.health.ingest(p))

    # ------------------------------------------------------------------ setup

    def _build(self) -> None:
        layout = self.config.sensors
        self.pump_id = self.gh.pump.id
        self._add_actuator(self.pump_id, "pump", None)
        for z in self.gh.zones:
            e = z.equipment
            acts = {"fan": f"{z.id}.fan", "valve": f"{z.id}.valve"}
            if e.grow_light:
                acts["grow_light"] = f"{z.id}.light"
            if e.mister:
                acts["mister"] = f"{z.id}.mister"
            if e.heater:
                acts["heater"] = f"{z.id}.heater"
            for kind, aid in acts.items():
                self._add_actuator(aid, kind, z.id)

            air = soil_temp = light = None
            soil: list[str] = []
            for inst in layout.zone:
                sid = f"{z.id}.{inst.id}"
                for q in MODEL_QUANTITIES[inst.model]:
                    self.health.register(sid, z.id, q, inst.sample_interval_s)
                if inst.model == "sht31":
                    air = sid
                elif inst.model == "capacitive_soil":
                    soil.append(sid)
                elif inst.model == "bh1750":
                    light = sid
                elif inst.model == "ds18b20":
                    soil_temp = sid
            del soil_temp  # monitored for health; not used by rules yet
            self.zones[z.id] = ZoneControl(
                z, self.config.crops[z.crop].targets, air, soil, light, acts
            )

        self.outside = self.tank_sensor = self.flow_sensor = None
        for inst in layout.greenhouse:
            for q in MODEL_QUANTITIES[inst.model]:
                self.health.register(inst.id, None, q, inst.sample_interval_s)
            if inst.model == "sht31":
                self.outside = inst.id
            elif inst.model == "jsn_sr04t":
                self.tank_sensor = inst.id
            elif inst.model == "yf_s201":
                self.flow_sensor = inst.id

    def _add_actuator(self, aid: str, kind: str, zone_id: str | None) -> None:
        self.kinds[aid] = kind
        self.actuator_zone[aid] = zone_id

    # ------------------------------------------------------------------ operator API

    def set_mode(
        self, actuator_id: str, mode: Mode | str, level: float = 0.0, by: str = "operator"
    ) -> None:
        if actuator_id not in self.modes:
            raise KeyError(f"unknown actuator '{actuator_id}'. Known: {', '.join(self.modes)}")
        m = self.modes[actuator_id]
        m.mode = Mode(mode)
        m.manual_level = max(0.0, min(1.0, level)) if m.mode is Mode.MANUAL else 0.0
        m.expires_at = None
        m.set_by = by

    def override(
        self, actuator_id: str, level: float, duration_s: float, now: datetime, by: str = "operator"
    ) -> None:
        """Timed manual override: holds `level`, then returns to AUTO automatically."""
        self.set_mode(actuator_id, Mode.MANUAL, level, by)
        self.modes[actuator_id].expires_at = now + timedelta(seconds=duration_s)

    def emergency_stop(self, now: datetime, reason: str = "operator", by: str = "operator") -> None:
        self.estop = True
        self.estop_reason = f"{reason} (by {by})"
        self.alerts.raise_(
            "EMERGENCY_STOP",
            Severity.CRITICAL,
            f"Emergency stop: {self.estop_reason}",
            now,
            latched=True,
        )
        self.tick(now)  # act immediately, not at the next scheduled tick

    def reset_emergency(self, now: datetime, by: str = "operator") -> None:
        self.estop = False
        self.alerts.clear("EMERGENCY_STOP", now, force=True)

    def reset_alarm(self, code: str, now: datetime, scope: str | None = None) -> None:
        """Acknowledge and clear a latched alarm (e.g. PUMP_NO_FLOW after repairing the pump)."""
        self.alerts.clear(code, now, scope, force=True)

    # ------------------------------------------------------------------ main loop

    def tick(self, now: datetime) -> list[Decision]:
        dt = (now - self._last_tick).total_seconds() if self._last_tick else 0.0
        self._last_tick = now
        self.now = now
        hour = now.hour + now.minute / 60 + now.second / 3600
        is_day = _in_window(hour, tuple(map(hhmm_to_hours, self.ctl.day_window)))

        self.health.evaluate(now)
        self._sensor_alerts(now)
        for m in self.modes.values():
            m.expire(now)

        out_t = self.health.value(self.outside, "air_temp") if self.outside else None
        out_rh = self.health.value(self.outside, "air_rh") if self.outside else None

        auto: dict[str, Proposal] = {}
        for z in self.zones.values():
            self._measure(z)
            self._track_violations(z, now, is_day, dt)
            auto.update(self._climate_rules(z, now, is_day, out_t, out_rh))
            auto.update(self._irrigation_rules(z, now))
            auto.update(self._lighting_rules(z, now, hour, dt))

        forces, blocks = self._interlocks(now)

        final: dict[str, Proposal] = {}
        for aid in self.kinds:
            if aid != self.pump_id:
                final[aid] = self._arbitrate(aid, auto.get(aid), forces, blocks, now)
        open_valves = [
            aid for aid, k in self.kinds.items() if k == "valve" and final[aid].level > 0
        ]
        pump_auto = (
            Proposal(1.0, "IRRIGATION_DEMAND", "open valves: " + ", ".join(open_valves))
            if open_valves
            else Proposal(0.0, "NO_DEMAND", "no zone is irrigating")
        )
        final[self.pump_id] = self._arbitrate(self.pump_id, pump_auto, forces, blocks, now)

        return self._apply(final, now)

    # ------------------------------------------------------------------ measurements

    def _measure(self, z: ZoneControl) -> None:
        h = self.health
        probes = [v for s in z.soil if (v := h.value(s, "soil_vwc")) is not None]
        z.measured = {
            "temp": h.value(z.air, "air_temp") if z.air else None,
            "rh": h.value(z.air, "air_rh") if z.air else None,
            "vwc_pct": sum(probes) / len(probes) if probes else None,
            "lux": h.value(z.light, "light_lux") if z.light else None,
        }
        scope = z.cfg.id
        if len(probes) >= 2 and max(probes) - min(probes) > self.ctl.sensors.disagreement_vwc_pct:
            self.alerts.raise_(
                "SENSOR_DISAGREE",
                Severity.WARNING,
                f"Zone {scope}: soil probes disagree ({min(probes):.1f} % vs "
                f"{max(probes):.1f} %); check probe placement or calibration",
                self.now,
                zone_id=scope,
            )
        else:
            self.alerts.clear("SENSOR_DISAGREE", self.now, scope)

    def _sensor_alerts(self, now: datetime) -> None:
        for ch in self.health.channels.values():
            subject = f"{ch.sensor_id}/{ch.quantity}"
            if ch.health in (Health.NO_DATA, Health.WARMING_UP) or ch.usable:
                self.alerts.clear("SENSOR_FAULT", now, subject)
            else:
                self.alerts.raise_(
                    "SENSOR_FAULT",
                    Severity.WARNING,
                    f"Sensor {subject} is {ch.health}",
                    now,
                    zone_id=ch.zone_id,
                    subject=subject,
                )

    def _track_violations(self, z: ZoneControl, now: datetime, is_day: bool, dt: float) -> None:
        t, rh = z.measured["temp"], z.measured["rh"]
        tmin, tmax = z.targets.temp_day_c if is_day else z.targets.temp_night_c
        rhmin, rhmax = z.targets.rh_pct
        sustain = self.ctl.violation_sustain_s
        zid = z.cfg.id
        for kind, value, lo, hi, attr in (
            ("TEMP", t, tmin, tmax, "temp_violation_since"),
            ("RH", rh, rhmin, rhmax, "rh_violation_since"),
        ):
            code = f"{kind}_OUT_OF_RANGE"
            if value is None or lo <= value <= hi:
                setattr(z, attr, None)
                self.alerts.clear(code, now, zid)
                continue
            z.violation_s[kind.lower()] += dt
            since = getattr(z, attr) or now
            setattr(z, attr, since)
            if (now - since).total_seconds() >= sustain:
                unit = "degC" if kind == "TEMP" else "%"
                self.alerts.raise_(
                    code,
                    Severity.WARNING,
                    f"Zone {zid}: {kind.lower()} {value:.1f} {unit} outside target "
                    f"{lo:g}-{hi:g} {unit} for over {sustain / 60:.0f} min",
                    now,
                    zone_id=zid,
                )
        vwc = z.measured["vwc_pct"]
        lo, hi = z.targets.vwc
        if vwc is not None and not (lo * 100 <= vwc <= hi * 100):
            z.violation_s["vwc"] += dt

    # ------------------------------------------------------------------ rules: climate

    def _climate_rules(
        self, z: ZoneControl, now: datetime, is_day: bool, out_t: float | None, out_rh: float | None
    ) -> dict[str, Proposal]:
        c = self.ctl.climate
        zid = z.cfg.id
        t, rh = z.measured["temp"], z.measured["rh"]
        tmin, tmax = z.targets.temp_day_c if is_day else z.targets.temp_night_c
        rhmin, rhmax = z.targets.rh_pct
        fan = z.actuators["fan"]
        out: dict[str, Proposal] = {}

        if t is None:
            level = c.stage1_level if is_day else 0.0
            self.alerts.raise_(
                "FAILSAFE_CLIMATE",
                Severity.WARNING,
                f"Zone {zid}: no valid air temperature; fans in fail-safe "
                f"({_fmt_level(level)} {'by day' if is_day else 'at night'})",
                now,
                zone_id=zid,
            )
            out[fan] = Proposal(level, "FAILSAFE_NO_TEMP", "air temperature sensor unavailable")
            for kind in ("mister", "heater"):
                if kind in z.actuators:
                    out[z.actuators[kind]] = Proposal(0.0, "FAILSAFE_NO_TEMP", "sensor unavailable")
            return out
        self.alerts.clear("FAILSAFE_CLIMATE", now, zid)

        # Mister: evaporative cooling when hot and dry, or humidifying when too dry.
        if "mister" in z.actuators and rh is not None:
            mode = z.mist_mode
            cooling_done = mode == "cool" and (rh >= rhmax or t < tmax)
            humidifying_done = mode == "humid" and rh >= rhmin + c.humidity_band_pct
            if cooling_done or humidifying_done:
                mode = None
            if mode is None:
                if t >= tmax + c.mist_cooling_offset_c and rh < rhmax - c.mist_rh_margin_pct:
                    mode = "cool"
                elif rh <= rhmin - c.humidity_band_pct:
                    mode = "humid"
            z.mist_mode = mode
            if mode == "cool":
                z.fog_cooling_until = now + timedelta(minutes=10)
            mister = z.actuators["mister"]
            if mode == "cool":
                out[mister] = Proposal(
                    1.0, "MIST_COOLING", f"temp {t:.1f} degC hot, RH {rh:.0f} % dry enough"
                )
            elif mode == "humid":
                out[mister] = Proposal(1.0, "MIST_HUMIDIFY", f"RH {rh:.0f} % < {rhmin:g} %")
            else:
                out[mister] = Proposal(0.0, "MIST_OK", f"RH {rh:.0f} %")

        # Fans, temperature: staged with hysteresis, only when outside air can actually cool.
        delta = None if out_t is None else t - out_t
        benefit_on = delta is None or delta >= c.vent_benefit_on_c
        # Fan-and-fog: while misting for cooling the fans must keep exchanging air, even if
        # the evaporative cooling has pulled the inside below the outside temperature.
        fogging = z.fog_cooling_until is not None and now < z.fog_cooling_until
        # By day a small inside/outside difference is what working fans achieve against the sun,
        # so keep going; at night there is no solar load, so a small difference means no benefit.
        off_limit = c.vent_benefit_off_c if is_day else c.vent_benefit_off_night_c
        benefit_off = delta is not None and delta <= off_limit and not fogging
        stage = z.fan_stage
        if stage == 0:
            if t >= tmax and benefit_on:
                stage = 2 if t >= tmax + c.stage2_offset_c else 1
        elif t <= tmax - c.temp_band_c or benefit_off:
            stage = 0
        elif stage == 1 and t >= tmax + c.stage2_offset_c:
            stage = 2
        elif stage == 2 and t <= tmax + c.stage2_offset_c - c.temp_band_c:
            stage = 1
        z.fan_stage = stage
        temp_level = (0.0, c.stage1_level, 1.0)[stage]

        # Fans, humidity: vent humid air only if outside air holds less water.
        hum_level = 0.0
        if rh is not None and out_t is not None and out_rh is not None:
            ratio = psychro.concentration_from_rh(out_rh, out_t) / psychro.concentration_from_rh(
                rh, t
            )
            limit = c.humidity_vent_stop_ratio if z.outside_drier else c.humidity_vent_start_ratio
            z.outside_drier = ratio < limit
        else:
            z.outside_drier = True  # no outside sensor: assume venting helps
        rh_high = rh is not None and z.rh_vent.update(
            rh, rhmax + c.humidity_band_pct, rhmax - c.humidity_band_pct / 2
        )
        # Temperature has priority: never vent for humidity if it would heat a hot zone.
        heat_limit = c.vent_benefit_off_c - (1.0 if z.humidity_venting else 0.0)  # hysteresis
        vent_heats = delta is not None and delta <= heat_limit and t >= tmax
        if rh_high and z.outside_drier and not vent_heats:
            hum_level = c.stage1_level
        z.humidity_venting = hum_level > 0

        if temp_level >= hum_level and temp_level > 0:
            limit = tmax + c.stage2_offset_c if stage == 2 else tmax
            out[fan] = Proposal(
                temp_level,
                "CLIMATE_HIGH_T" if stage == 1 else "CLIMATE_VERY_HIGH_T",
                f"temp {t:.1f} degC > {limit:g} degC"
                + (f", {delta:+.1f} degC vs outside" if delta is not None else ""),
            )
        elif hum_level > 0:
            out[fan] = Proposal(
                hum_level, "CLIMATE_HIGH_RH", f"RH {rh:.0f} % > {rhmax:g} %, outside air drier"
            )
        else:
            if t >= tmax:
                why = (
                    f"temp {t:.1f} degC high but outside air would not cool "
                    f"(delta {delta:+.1f} degC)"
                )
                if rh_high:
                    why += f"; RH {rh:.0f} % high but venting would heat the zone"
            elif rh_high:
                why = f"RH {rh:.0f} % high but outside air is not drier"
            else:
                why = f"temp {t:.1f} degC within target"
            out[fan] = Proposal(0.0, "CLIMATE_OK", why)

        if "heater" in z.actuators:
            on = z.heater.update(t, tmin, tmin + c.temp_band_c)
            out[z.actuators["heater"]] = (
                Proposal(1.0, "CLIMATE_LOW_T", f"temp {t:.1f} degC < {tmin:g} degC")
                if on
                else Proposal(0.0, "CLIMATE_OK", f"temp {t:.1f} degC")
            )
        return out

    # ------------------------------------------------------------------ rules: irrigation

    def _irrigation_rules(self, z: ZoneControl, now: datetime) -> dict[str, Proposal]:
        ic = self.ctl.irrigation
        zid = z.cfg.id
        valve = z.actuators["valve"]
        vwc = z.measured["vwc_pct"]
        lo, hi = z.targets.vwc
        start = lo * 100
        stop = (lo + ic.stop_fraction * (hi - lo)) * 100

        # A safety block closed the valve: abandon the running cycle and start fresh later.
        if self.last[valve].source == "interlock" and z.irrigation in ("watering", "fallback"):
            z.irrigation = "idle"

        if vwc is None:
            self.alerts.raise_(
                "FAILSAFE_IRRIGATION",
                Severity.WARNING,
                f"Zone {zid}: no valid soil moisture reading; irrigating on a "
                f"timer ({ic.fallback_duration_s / 60:.0f} min every "
                f"{ic.fallback_interval_s / 3600:.0f} h)",
                now,
                zone_id=zid,
            )
            if z.irrigation == "fallback":
                if (now - z.irrigation_started).total_seconds() >= ic.fallback_duration_s:
                    z.irrigation = "idle"
                    z.last_irrigation_end = now
            elif z.last_irrigation_end is None or (
                (now - z.last_irrigation_end).total_seconds() >= ic.fallback_interval_s
            ):
                z.irrigation = "fallback"
                z.irrigation_started = now
            if z.irrigation == "fallback":
                return {
                    valve: Proposal(
                        1.0, "FAILSAFE_TIMER", "timed irrigation, soil sensors unavailable"
                    )
                }
            return {valve: Proposal(0.0, "FAILSAFE_TIMER", "waiting for next timed irrigation")}

        self.alerts.clear("FAILSAFE_IRRIGATION", now, zid)
        if z.irrigation == "fallback":
            z.irrigation = "idle"

        dry_limit = (z.cfg.soil.wilting_point + ic.critical_dry_margin) * 100
        if vwc < dry_limit:
            self.alerts.raise_(
                "SOIL_DRY",
                Severity.CRITICAL,
                f"Zone {zid}: soil moisture {vwc:.1f} % near wilting point",
                now,
                zone_id=zid,
            )
        elif vwc > dry_limit + 1:
            self.alerts.clear("SOIL_DRY", now, zid)

        if z.irrigation == "idle" and vwc <= start:
            z.irrigation = "watering"
            z.irrigation_started = now
        elif z.irrigation == "watering":
            if vwc >= stop:
                z.irrigation = "idle"
                z.last_irrigation_end = now
                self.alerts.clear("IRRIGATION_TIMEOUT", now, zid)
            elif (now - z.irrigation_started).total_seconds() >= ic.max_cycle_s:
                z.irrigation = "soak"
                z.soak_until = now + timedelta(seconds=ic.soak_s)
                z.last_irrigation_end = now
                self.alerts.raise_(
                    "IRRIGATION_TIMEOUT",
                    Severity.WARNING,
                    f"Zone {zid}: target {stop:.1f} % not reached after "
                    f"{ic.max_cycle_s / 60:.0f} min (VWC {vwc:.1f} %); soaking. "
                    "Check for leaks, clogged emitters or sensor placement.",
                    now,
                    zone_id=zid,
                )
        elif z.irrigation == "soak" and now >= z.soak_until:
            z.irrigation = "idle"

        if z.irrigation == "watering":
            return {
                valve: Proposal(
                    1.0, "SOIL_LOW", f"VWC {vwc:.1f} % (start {start:.0f} %, stop {stop:.1f} %)"
                )
            }
        if z.irrigation == "soak":
            return {valve: Proposal(0.0, "SOAK", f"soaking after a long cycle, VWC {vwc:.1f} %")}
        return {
            valve: Proposal(
                0.0, "SOIL_OK", f"VWC {vwc:.1f} % (start {start:.0f} %, stop {stop:.1f} %)"
            )
        }

    # ------------------------------------------------------------------ rules: lighting

    def _lighting_rules(
        self, z: ZoneControl, now: datetime, hour: float, dt: float
    ) -> dict[str, Proposal]:
        if "grow_light" not in z.actuators:
            return {}
        lc = self.ctl.lighting
        zid = z.cfg.id
        light = z.actuators["grow_light"]
        ppfd = z.cfg.equipment.grow_light.ppfd_umol_m2s
        lamp_on = self.last[light].level > 0

        if z.dli_date != now.date():
            z.dli_date = now.date()
            z.dli_estimate = 0.0

        lux = z.measured["lux"]
        if lux is None:
            self.alerts.raise_(
                "FAILSAFE_LIGHTING",
                Severity.WARNING,
                f"Zone {zid}: no valid light reading; grow lights off",
                now,
                zone_id=zid,
            )
            z.light_on = False
            return {light: Proposal(0.0, "FAILSAFE_NO_LIGHT", "light sensor unavailable")}
        self.alerts.clear("FAILSAFE_LIGHTING", now, zid)

        # The sensor also sees the lamps: subtract their contribution to estimate the sun alone.
        sun_par = max(0.0, lux - (ppfd * LUX_PER_UMOL_LED if lamp_on else 0.0)) / LUX_PER_UMOL_SUN
        z.dli_estimate += (sun_par + (ppfd if lamp_on else 0.0)) * dt / 1e6

        start, end = map(hhmm_to_hours, lc.window)
        dmin, _ = z.targets.dli_mol_m2d
        frac = min(1.0, max(0.0, (hour - start) / (end - start)))
        expected = dmin * (1 - math.cos(math.pi * frac)) / 2  # sun-shaped pacing to the minimum
        deficit = expected - z.dli_estimate

        on = z.light_on
        if not _in_window(hour, (start, end)) or z.dli_estimate >= dmin:
            on = False
        elif (
            not on
            and deficit > lc.deficit_on_fraction * dmin
            and sun_par < lc.off_above_sun_par - lc.sun_par_band
        ):
            on = True
        elif on and (deficit <= 0 or sun_par > lc.off_above_sun_par):
            on = False
        z.light_on = on

        info = (
            f"DLI {z.dli_estimate:.1f}/{dmin:g} mol (pace {expected:.1f}), sun {sun_par:.0f} umol"
        )
        if on:
            return {light: Proposal(1.0, "DLI_DEFICIT", info)}
        return {light: Proposal(0.0, "DLI_OK", info)}

    # ------------------------------------------------------------------ interlocks

    def _interlocks(self, now: datetime) -> tuple[dict[str, Proposal], dict[str, tuple[str, str]]]:
        forces: dict[str, Proposal] = {}
        blocks: dict[str, tuple[str, str]] = {}
        water_users = [aid for aid, k in self.kinds.items() if k in ("pump", "valve", "mister")]

        def block(aids, rule, reason):
            for aid in aids:
                blocks.setdefault(aid, (rule, reason))

        # Tank level: dry-run protection with hysteresis.
        tc = self.ctl.tank
        tank = self.health.value(self.tank_sensor, "tank_level") if self.tank_sensor else None
        if tank is None:
            self.alerts.raise_(
                "TANK_LEVEL_UNKNOWN",
                Severity.CRITICAL,
                "Tank level unavailable; pump and misters locked out (dry-run protection)",
                now,
                subject=self.tank_sensor,
            )
            block(water_users, "TANK_LEVEL_UNKNOWN", "tank level unknown")
        else:
            self.alerts.clear("TANK_LEVEL_UNKNOWN", now, self.tank_sensor)
            if self._tank_lockout and tank >= tc.release_pct:
                self._tank_lockout = False
                self.alerts.clear("TANK_CRITICAL", now, self.tank_sensor)
            elif not self._tank_lockout and tank < tc.critical_pct:
                self._tank_lockout = True
                self.alerts.raise_(
                    "TANK_CRITICAL",
                    Severity.CRITICAL,
                    f"Tank at {tank:.0f} %; irrigation and misting disabled until "
                    f"above {tc.release_pct:g} %",
                    now,
                    subject=self.tank_sensor,
                )
            if tank < tc.low_pct:
                self.alerts.raise_(
                    "TANK_LOW",
                    Severity.WARNING,
                    f"Tank low: {tank:.0f} %",
                    now,
                    subject=self.tank_sensor,
                )
            elif tank >= tc.low_pct + 2:
                self.alerts.clear("TANK_LOW", now, self.tank_sensor)
            if self._tank_lockout:
                block(water_users, "TANK_CRITICAL", f"tank {tank:.0f} % < {tc.critical_pct:g} %")

        # Pump: confirm water is actually flowing; limit continuous run time.
        pc = self.ctl.pump
        pump_t = self.timing[self.pump_id]
        pump_on = self.last[self.pump_id].level > 0
        on_for = (now - pump_t.changed_at).total_seconds() if pump_on and pump_t.changed_at else 0.0
        flow_ch = self.health.channel(self.flow_sensor, "flow_lpm") if self.flow_sensor else None
        if pump_on and on_for > pc.no_flow_grace_s and flow_ch is not None and flow_ch.usable:
            fresh = flow_ch.accepted_at > pump_t.changed_at + timedelta(
                seconds=pc.no_flow_grace_s / 2
            )
            if fresh and flow_ch.value < pc.no_flow_lpm:
                self.alerts.raise_(
                    "PUMP_NO_FLOW",
                    Severity.CRITICAL,
                    f"Pump running {on_for:.0f} s but flow is {flow_ch.value:.1f} L/min: "
                    "pump failure, blocked line or empty intake. Reset after repair.",
                    now,
                    subject=self.pump_id,
                    latched=True,
                )
        if self.alerts.is_active("PUMP_NO_FLOW", self.pump_id):
            block(water_users, "PUMP_NO_FLOW", "pump failure alarm latched")

        if (
            not pump_on
            and flow_ch is not None
            and flow_ch.usable
            and flow_ch.value > pc.no_flow_lpm
        ):
            off_for = (now - pump_t.changed_at).total_seconds() if pump_t.changed_at else 1e9
            if off_for > pc.no_flow_grace_s:
                self.alerts.raise_(
                    "UNEXPECTED_FLOW",
                    Severity.WARNING,
                    f"Flow {flow_ch.value:.1f} L/min with the pump off: stuck relay or leak",
                    now,
                    subject=self.flow_sensor,
                )
        elif flow_ch is not None and flow_ch.usable and flow_ch.value <= pc.no_flow_lpm:
            self.alerts.clear("UNEXPECTED_FLOW", now, self.flow_sensor)

        if pump_on and on_for >= pc.max_run_s:
            self._pump_cooldown_until = now + timedelta(seconds=pc.cooldown_s)
            self.alerts.raise_(
                "PUMP_MAX_RUNTIME",
                Severity.WARNING,
                f"Pump ran {on_for / 60:.0f} min continuously; resting "
                f"{pc.cooldown_s / 60:.0f} min",
                now,
                subject=self.pump_id,
            )
        if self._pump_cooldown_until and now < self._pump_cooldown_until:
            block([self.pump_id], "PUMP_COOLDOWN", "pump resting after maximum run time")
        elif self._pump_cooldown_until:
            self._pump_cooldown_until = None
            self.alerts.clear("PUMP_MAX_RUNTIME", now, self.pump_id)

        # High temperature emergency: fans to 100 % regardless of mode.
        cc = self.ctl.climate
        for zid, z in self.zones.items():
            t = z.measured["temp"]
            if t is not None and t >= cc.emergency_temp_c:
                self._high_temp[zid] = True
            elif t is None or t <= cc.emergency_clear_c:
                self._high_temp[zid] = False
            if self._high_temp[zid]:
                self.alerts.raise_(
                    "HIGH_TEMP_EMERGENCY",
                    Severity.CRITICAL,
                    f"Zone {zid}: {t:.1f} degC >= {cc.emergency_temp_c:g} degC; "
                    "fans forced to 100 %",
                    now,
                    zone_id=zid,
                )
                forces[z.actuators["fan"]] = Proposal(
                    1.0,
                    "HIGH_TEMP_EMERGENCY",
                    f"temp {t:.1f} degC >= {cc.emergency_temp_c:g} degC",
                    "interlock",
                )
            else:
                self.alerts.clear("HIGH_TEMP_EMERGENCY", now, zid)
        return forces, blocks

    # ------------------------------------------------------------------ arbitration

    def _arbitrate(
        self,
        aid: str,
        auto: Proposal | None,
        forces: dict[str, Proposal],
        blocks: dict[str, tuple[str, str]],
        now: datetime,
    ) -> Proposal:
        if self.estop:
            return Proposal(0.0, "EMERGENCY_STOP", self.estop_reason, "estop")
        if aid in forces:
            return forces[aid]
        m = self.modes[aid]
        if m.mode is Mode.MANUAL:
            until = f" until {m.expires_at:%H:%M}" if m.expires_at else ""
            p = Proposal(m.manual_level, "MANUAL", f"set by {m.set_by}{until}", "manual")
        elif m.mode is Mode.OFF:
            p = Proposal(0.0, "MODE_OFF", f"switched off by {m.set_by}", "mode")
        else:
            p = auto or Proposal(0.0, "IDLE", "no rule active")
        if p.level > 0 and aid in blocks:
            rule, reason = blocks[aid]
            return Proposal(0.0, rule, reason, "interlock")
        if p.source == "auto":
            allowed = self.timing[aid].allowed(p.level, now)
            if allowed != p.level:
                held = "minimum on-time" if allowed > 0 else "minimum off-time"
                return Proposal(allowed, "MIN_TIME_HOLD", f"{held} ({p.rule}: {p.reason})", "auto")
        return p

    def _apply(self, final: dict[str, Proposal], now: datetime) -> list[Decision]:
        changes: list[Decision] = []
        for aid, p in final.items():
            prev = self.last[aid]
            self.timing[aid].record(p.level, now)
            self.last[aid] = p
            if p.level != prev.level:
                zid = self.actuator_zone[aid]
                where = f"Zone {zid}" if zid else "Greenhouse"
                label = KIND_LABEL[self.kinds[aid]]
                msg = f"{where} · {label} {_fmt_level(p.level)} · {p.rule} · {p.reason}"
                d = Decision(now, aid, zid, prev.level, p.level, p.rule, p.source, msg)
                self.decisions.append(d)
                changes.append(d)
                if self._publish:
                    self._publish(f"agrisense/{self.gh.id}/control/decision", d.to_message())
            if self._publish:
                ttl = None if p.source == "estop" else self.ctl.command_ttl_s
                self._publish(
                    actuator_set_topic(self.gh.id, self.actuator_zone[aid], aid),
                    {"level": p.level, "reason": p.rule, "ttl_s": ttl},
                )
        return changes

    def _publish_alert(self, alert: Alert) -> None:
        if self._publish:
            self._publish(f"agrisense/{self.gh.id}/control/alert", alert.to_message())

    # ------------------------------------------------------------------ reporting

    def status(self) -> dict[str, Any]:
        return {
            "time": self.now.isoformat() if self.now else None,
            "emergency_stop": self.estop,
            "actuators": {
                aid: {
                    "level": p.level,
                    "rule": p.rule,
                    "reason": p.reason,
                    "source": p.source,
                    "mode": str(self.modes[aid].mode),
                    "override_until": self.modes[aid].expires_at.isoformat()
                    if self.modes[aid].expires_at
                    else None,
                }
                for aid, p in self.last.items()
            },
            "zones": {
                zid: {
                    "measured": z.measured,
                    "irrigation": z.irrigation,
                    "fan_stage": z.fan_stage,
                    "dli_estimate": round(z.dli_estimate, 2),
                    "violation_minutes": {k: round(v / 60, 1) for k, v in z.violation_s.items()},
                }
                for zid, z in self.zones.items()
            },
            "alerts": [a.to_message() for a in self.alerts.active.values()],
            "recent_decisions": [d.to_message() for d in list(self.decisions)[-50:]],
            "sensors": self.health.summary(),
        }
