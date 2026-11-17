import pytest

from agrisense_core.config import load_config
from agrisense_core.sim.engine import GreenhouseEngine


def test_same_seed_is_deterministic(config):
    def run(seed):
        e = GreenhouseEngine(config, seed=seed, step_s=10.0)
        e.run_for(3 * 3600)
        return [e.zones[z].state.temp_c for z in "ABC"], e.latest[("A.air", "air_temp")].value

    assert run(11) == run(11)
    assert run(11) != run(12)


def test_irrigation_conserves_water(engine):
    soil_before = {z: m.soil_water_l() for z, m in engine.zones.items()}
    tank_before = engine.tank.volume_l
    engine.command("pump1", 1)
    engine.command("A.valve", 1)
    engine.command("C.valve", 1)
    engine.run_for(3600)

    irrigated = sum(m.state.totals["irrigation_l"] for m in engine.zones.values())
    assert irrigated > 100
    tank = engine.tank
    drawn = tank_before + tank.inflow_total_l - tank.overflow_total_l - tank.volume_l
    assert drawn == pytest.approx(irrigated, rel=1e-9)  # inflow = rain harvested from the roof
    assert engine.flow_total_l == pytest.approx(irrigated, rel=1e-9)
    assert engine.zones["B"].state.totals["irrigation_l"] == 0
    for z, m in engine.zones.items():
        t = m.state.totals
        expected = soil_before[z] + t["irrigation_l"] - t["et_l"] - t["drainage_l"]
        assert m.soil_water_l() == pytest.approx(expected, rel=1e-6)


def test_irrigation_raises_soil_moisture(engine):
    before = engine.zones["A"].state.vwc
    engine.command("pump1", 1)
    engine.command("A.valve", 1)
    engine.run_for(3600)
    assert engine.zones["A"].state.vwc > before


def test_pump_flow_is_limited_by_capacity(config):
    gh = config.greenhouse
    small_pump = gh.pump.model_copy(update={"max_flow_lpm": 6.0})
    cfg = config.model_copy(update={"greenhouse": gh.model_copy(update={"pump": small_pump})})
    e = GreenhouseEngine(cfg, seed=7, step_s=5.0)
    e.command("pump1", 1)
    for z in "ABC":
        e.command(f"{z}.valve", 1)
    e.run_for(600)
    # Zones demand 11.5 L/min in total; a 6 L/min pump shares its flow in proportion.
    assert sum(e.irrigation_lps.values()) == pytest.approx(6.0 / 60, rel=1e-9)
    assert e.irrigation_lps["A"] / e.irrigation_lps["C"] == pytest.approx(250 / 200)


def test_no_flow_without_open_valve_or_from_empty_tank(engine):
    engine.command("pump1", 1)
    engine.run_for(300)
    assert engine.flow_total_l == 0
    engine.tank.volume_l = 0
    engine.command("A.valve", 1)
    engine.run_for(300)
    assert engine.flow_total_l == 0


def test_rain_refills_tank_from_roof(engine):
    engine.tank.volume_l = 500
    engine.scenarios.start("rainfall", duration_h=1, rain_mm_h=10)
    engine.run_for(3600)
    # 10 mm/h on 150 m2 at 80 % efficiency = 1200 L
    assert engine.tank.volume_l == pytest.approx(1700, abs=5)


def test_fans_cool_a_hot_zone(config):
    e = GreenhouseEngine(config, seed=4, step_s=5.0)
    e.weather.overrides.cloud = 0.1
    e.run_for(12 * 3600)
    hot = e.zones["A"].state.temp_c
    e.command("A.fan", 1)
    e.run_for(600)
    assert e.zones["A"].state.temp_c < hot - 5


def test_grow_lights_add_light_and_energy(engine):
    engine.command("C.light", 1)
    engine.run_for(3600)
    s = engine.zones["C"].state
    assert s.par_umol == pytest.approx(200, abs=1)  # night: lamps only
    assert engine.actuators["C.light"].energy_wh == pytest.approx(4000, rel=0.01)


def test_commands_via_message_bus(engine):
    engine.publish_command("A.fan", 1, reason="remote", ttl_s=60)
    engine.run_for(30)
    assert engine.actuators["A.fan"].actual == 1
    engine.run_for(60)
    assert engine.actuators["A.fan"].actual == 0
    assert engine.actuators["A.fan"].reason == "ttl_expired"


def test_sensors_publish_on_mqtt_topics(engine):
    received = []
    engine.bus.subscribe("agrisense/gh1/A/sensor/+/air_temp", lambda t, p: received.append(p))
    engine.run_for(30)
    assert received and received[-1]["unit"] == "degC"
    assert abs(received[-1]["value"] - engine.zones["A"].state.temp_c) < 2


def test_snapshot_is_json_serialisable(engine):
    import json

    engine.run_for(60)
    json.dumps(engine.snapshot())


def test_real_sensor_source_is_not_simulated(tmp_path):
    from importlib import resources

    for name in ("greenhouse.yaml", "crops.yaml", "sensors.yaml"):
        text = resources.files("agrisense_core.profiles").joinpath(name).read_text(encoding="utf-8")
        if name == "sensors.yaml":
            text = text.replace(
                "{id: co2,   model: scd30,       source: sim",
                "{id: co2,   model: scd30,       source: mqtt",
            )
        (tmp_path / name).write_text(text, encoding="utf-8")
    e = GreenhouseEngine(load_config(tmp_path))
    assert "A.co2" not in e.sensors and "A.air" in e.sensors
