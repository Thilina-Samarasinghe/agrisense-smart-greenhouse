"""Closed-loop scenario tests: the controller must handle every documented situation."""

from collections import Counter

import pytest

from agrisense_core.control.controller import GreenhouseController
from agrisense_core.control.modes import Mode
from agrisense_core.devices.bus import MessageBus
from agrisense_core.runtime import GreenhouseRuntime

H = 3600


@pytest.fixture
def rt(config):
    return GreenhouseRuntime(config, seed=5, step_s=10.0)


def actual(rt, aid):
    return rt.engine.actuators[aid].actual


def codes(rt):
    return rt.controller.alerts.codes()


def rules(rt, aid):
    return [d.rule for d in rt.controller.decisions if d.actuator_id == aid]


def run_until(rt, predicate, max_s, step_s=10):
    for _ in range(int(max_s / step_s)):
        rt.run_for(step_s)
        if predicate():
            return True
    return False


# --------------------------------------------------------------------------- basics


def test_controller_without_any_data_fails_safe(config):
    ctl = GreenhouseController(config, bus=MessageBus())
    from datetime import datetime

    ctl.tick(datetime(2026, 3, 21, 12))
    active = ctl.alerts.codes()
    assert {"TANK_LEVEL_UNKNOWN", "FAILSAFE_CLIMATE", "FAILSAFE_IRRIGATION"} <= active
    assert ctl.last["pump1"].level == 0  # dry-run protection
    assert ctl.last["A.fan"].rule == "FAILSAFE_NO_TEMP" and ctl.last["A.fan"].level == 0.5


def test_decisions_are_explained_and_published(rt):
    msgs = []
    rt.engine.bus.subscribe("agrisense/gh1/control/decision", lambda t, p: msgs.append(p))
    rt.engine.scenarios.start("dry_soil", zone="A", vwc=0.24)
    rt.run_for(60)
    d = next(d for d in rt.controller.decisions if d.actuator_id == "A.valve")
    assert d.rule == "SOIL_LOW" and "Zone A · Valve ON · SOIL_LOW · VWC" in d.message
    assert any(m["actuator_id"] == "A.valve" for m in msgs)


def test_closed_loop_is_deterministic(config):
    def run():
        r = GreenhouseRuntime(config, seed=9, step_s=10.0)
        r.run_for(8 * H)
        return [d.message for d in r.controller.decisions]

    assert run() == run()


# --------------------------------------------------------------------------- climate


def test_hot_day_controller_keeps_zone_far_cooler_than_open_loop(config):
    def peak_rise(control):
        r = GreenhouseRuntime(config, seed=3, step_s=10.0, control=control)
        r.engine.scenarios.start("hot_day", duration_h=24)
        rises = []
        r.run_for(
            16 * H,
            lambda x: rises.append(
                x.engine.zones["A"].state.temp_c - x.engine.weather.state.temp_c
            ),
        )
        return max(rises[int(11 * H / 10) :]), r

    closed, r = peak_rise(True)
    open_loop, _ = peak_rise(False)
    assert closed < 4.0
    assert open_loop - closed > 6.0
    fan_rules = set(rules(r, "A.fan"))
    assert fan_rules & {"CLIMATE_HIGH_T", "CLIMATE_VERY_HIGH_T"}


def test_normal_day_has_no_equipment_chatter(config):
    r = GreenhouseRuntime(config, seed=42, step_s=10.0)
    r.run_for(24 * H)
    per = Counter(d.actuator_id for d in r.controller.decisions)
    for zone in "ABC":
        assert per[f"{zone}.fan"] <= 40, per
        assert per[f"{zone}.valve"] <= 6, per
    assert per["pump1"] <= 8
    # Each actuator's state changes respect its minimum on/off times.
    fan = [d for d in r.controller.decisions if d.actuator_id == "A.fan"]
    for prev, cur in zip(fan, fan[1:], strict=False):
        gap = (cur.ts - prev.ts).total_seconds()
        if prev.to_level > 0 and cur.to_level == 0:
            assert gap >= 300 - 10
        if prev.to_level == 0 and cur.to_level > 0:
            assert gap >= 120 - 10


def test_high_temperature_emergency_overrides_mode_off(rt):
    for z in "A":
        rt.controller.set_mode(f"{z}.fan", Mode.OFF)
        rt.controller.set_mode(f"{z}.mister", Mode.OFF)
    rt.engine.scenarios.start("hot_day", duration_h=24)
    assert run_until(rt, lambda: "HIGH_TEMP_EMERGENCY" in codes(rt), 14 * H, step_s=60)
    rt.run_for(30)
    assert actual(rt, "A.fan") == 1.0
    assert rt.controller.last["A.fan"].source == "interlock"


# --------------------------------------------------------------------------- irrigation


def test_dry_soil_starts_irrigation_and_stops_at_target(rt):
    rt.engine.scenarios.start("dry_soil", zone="A", vwc=0.245)
    rt.run_for(60)
    assert actual(rt, "A.valve") == 1 and actual(rt, "pump1") == 1
    assert run_until(rt, lambda: actual(rt, "A.valve") == 0, 4 * H, step_s=60)
    vwc = rt.engine.zones["A"].state.vwc
    assert 0.27 <= vwc <= 0.30  # stop target 28 % measured by imperfect probes
    rt.run_for(120)
    assert actual(rt, "pump1") == 0


def test_soil_near_wilting_point_raises_critical_alert(rt):
    rt.engine.scenarios.start("dry_soil", zone="B", vwc=0.13)  # wilting point 0.12
    rt.run_for(120)
    assert "SOIL_DRY" in codes(rt)
    assert actual(rt, "B.valve") == 1


def test_water_shortage_locks_out_pump_until_refilled(rt):
    rt.engine.scenarios.start("water_shortage")
    rt.engine.scenarios.start("dry_soil", zone="A", vwc=0.24)
    rt.run_for(300)
    assert "TANK_CRITICAL" in codes(rt)
    assert actual(rt, "pump1") == 0 and actual(rt, "A.valve") == 0
    assert rt.engine.flow_total_l == 0
    # An operator cannot override the dry-run protection.
    rt.controller.override("pump1", 1.0, 600, rt.now)
    rt.run_for(60)
    assert actual(rt, "pump1") == 0
    rt.engine.scenarios.start("refill_tank")
    rt.run_for(120)
    assert "TANK_CRITICAL" not in codes(rt)
    assert actual(rt, "A.valve") == 1


def test_pump_failure_latches_alarm_until_reset(rt):
    rt.engine.scenarios.start("dry_soil", zone="A", vwc=0.24)
    sc = rt.engine.scenarios.start("pump_failure", duration_h=10)
    assert run_until(rt, lambda: "PUMP_NO_FLOW" in codes(rt), 300)
    rt.run_for(30)
    assert actual(rt, "pump1") == 0 and actual(rt, "A.valve") == 0
    rt.engine.scenarios.stop(sc.id)  # pump repaired...
    rt.run_for(300)
    assert "PUMP_NO_FLOW" in codes(rt)  # ...but the alarm stays until acknowledged
    assert actual(rt, "pump1") == 0
    rt.controller.reset_alarm("PUMP_NO_FLOW", rt.now, scope="pump1")
    rt.run_for(120)
    assert actual(rt, "pump1") == 1 and rt.engine.flow_total_l > 0


# --------------------------------------------------------------------------- sensor faults


def test_air_sensor_dropout_puts_climate_in_failsafe(rt):
    rt.run_for(12 * H)
    rt.engine.scenarios.start("sensor_failure", sensor="A.air", fault="dropout")
    rt.run_for(120)
    assert "SENSOR_FAULT" in codes(rt) and "FAILSAFE_CLIMATE" in codes(rt)
    assert rt.controller.last["A.fan"].rule in ("FAILSAFE_NO_TEMP", "MIN_TIME_HOLD")
    rt.run_for(600)
    assert actual(rt, "A.fan") == 0.5  # daytime fail-safe level


def test_stuck_sensor_detected(rt):
    rt.run_for(H)
    rt.engine.scenarios.start("sensor_failure", sensor="B.air", fault="stuck")
    rt.run_for(15 * 60)
    ch = rt.controller.health.channel("B.air", "air_temp")
    assert ch.health.value == "stuck"
    assert "SENSOR_FAULT" in codes(rt)


def test_spiking_sensor_detected_and_spikes_ignored(rt):
    rt.run_for(H)
    rt.engine.scenarios.start("sensor_failure", sensor="C.air", fault="spike", magnitude=8.0)
    rt.run_for(10 * 60)
    ch = rt.controller.health.channel("C.air", "air_temp")
    assert ch.health.value == "spikes"
    true_t = rt.engine.zones["C"].state.temp_c
    assert abs(ch.value - true_t) < 2.0


def test_soil_sensor_failure_falls_back_to_timed_irrigation(rt):
    for probe in ("B.soil1", "B.soil2"):
        rt.engine.scenarios.start("sensor_failure", sensor=probe, fault="dropout", duration_h=12)
    rt.run_for(120)
    assert "FAILSAFE_IRRIGATION" in codes(rt)
    assert actual(rt, "B.valve") == 1
    rt.run_for(11 * 60)
    assert actual(rt, "B.valve") == 0  # 10 minute timed cycle finished


def test_disagreeing_soil_probes_raise_warning(rt):
    rt.engine.scenarios.start("sensor_failure", sensor="A.soil1", fault="offset", magnitude=10.0)
    rt.run_for(120)
    assert "SENSOR_DISAGREE" in codes(rt)


# --------------------------------------------------------------------------- operator


def test_timed_override_returns_to_auto(rt):
    rt.run_for(60)  # night: fans have no reason to run
    rt.controller.override("C.fan", 1.0, 30 * 60, rt.now)
    rt.run_for(60)
    assert actual(rt, "C.fan") == 1.0
    rt.run_for(31 * 60)
    assert rt.controller.modes["C.fan"].mode is Mode.AUTO
    assert actual(rt, "C.fan") == 0.0


def test_emergency_stop_is_latched_until_reset(rt):
    rt.engine.scenarios.start("dry_soil", zone="A", vwc=0.24)
    rt.run_for(60)
    assert actual(rt, "pump1") == 1
    rt.controller.emergency_stop(rt.now, reason="test")
    rt.run_for(20)
    assert all(a.actual == 0 for a in rt.engine.actuators.values())
    rt.run_for(600)
    assert all(a.actual == 0 for a in rt.engine.actuators.values())
    assert "EMERGENCY_STOP" in codes(rt)
    rt.controller.reset_emergency(rt.now)
    rt.run_for(120)
    assert actual(rt, "pump1") == 1


def test_actuators_fail_safe_when_controller_goes_silent(rt):
    rt.controller.override("A.fan", 1.0, 3600, rt.now)
    rt.run_for(30)
    assert actual(rt, "A.fan") == 1.0
    for _ in range(12):  # 2 minutes of physics with no controller ticks
        rt.engine.step()
    assert actual(rt, "A.fan") == 0.0
    assert rt.engine.actuators["A.fan"].reason == "ttl_expired"


# --------------------------------------------------------------------------- lighting


def test_grow_lights_make_up_light_deficit_on_cloudy_day(config):
    r = GreenhouseRuntime(config, seed=5, step_s=10.0)
    r.engine.scenarios.start("cloudy", duration_h=24)
    r.run_for(19 * H)
    assert "DLI_DEFICIT" in rules(r, "A.light")
    r.run_for(2 * H)  # 21:00: outside the lighting window
    assert actual(r, "A.light") == 0
    est = r.controller.zones["A"].dli_estimate
    true = r.engine.zones["A"].state.dli_mol
    assert est == pytest.approx(true, rel=0.25)  # controller's DLI estimate from the lux sensor
