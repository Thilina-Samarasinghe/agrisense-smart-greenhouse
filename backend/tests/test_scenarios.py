import pytest

from agrisense_core.sim.scenarios import CATALOG


def test_catalog_has_all_documented_scenarios():
    for name in [
        "hot_day",
        "heatwave",
        "rainfall",
        "cloudy",
        "cold_night",
        "humidity_spike",
        "dry_soil",
        "water_shortage",
        "pump_failure",
        "sensor_failure",
    ]:
        assert name in CATALOG


def test_hot_day_raises_outside_temperature_and_reverts(engine):
    engine.run_for(60)
    base = engine.weather.state.temp_c
    sc = engine.scenarios.start("hot_day", duration_h=1)
    engine.run_for(60)
    assert engine.weather.state.temp_c > base + 4
    engine.run_for(3600)
    assert sc not in engine.scenarios.active
    assert engine.weather.overrides.temp_offset_c == 0


def test_water_shortage_and_humidity_spike(engine):
    engine.scenarios.start("water_shortage")
    assert engine.tank.level_frac == pytest.approx(0.05)
    engine.scenarios.start("humidity_spike", zone="B")
    assert engine.zones["B"].state.rh_pct == pytest.approx(97, abs=0.1)
    assert engine.zones["A"].state.rh_pct < 97


def test_dry_soil_defaults_near_wilting_point(engine):
    engine.scenarios.start("dry_soil", zone="A")
    z = engine.zones["A"]
    assert z.state.vwc == pytest.approx(z.cfg.soil.wilting_point + 0.03)


def test_pump_failure_stops_flow_and_flow_meter_shows_it(engine):
    engine.scenarios.start("pump_failure", duration_h=1)
    engine.command("pump1", 1)
    engine.command("A.valve", 1)
    engine.run_for(120)
    assert engine.flow_total_l == 0
    assert engine.latest[("flow", "flow_lpm")].value == 0
    assert engine.actuators["pump1"].energy_wh > 0


def test_sensor_failure_scenario(engine):
    engine.scenarios.start("sensor_failure", sensor="A.air", fault="dropout", duration_h=1)
    engine.run_for(30)
    assert engine.latest[("A.air", "air_temp")].value is None
    engine.run_for(3600)
    assert engine.latest[("A.air", "air_temp")].value is not None


def test_unknown_scenario_or_param_rejected(engine):
    with pytest.raises(KeyError):
        engine.scenarios.start("meteor")
    with pytest.raises(ValueError):
        engine.scenarios.start("hot_day", banana=1)
