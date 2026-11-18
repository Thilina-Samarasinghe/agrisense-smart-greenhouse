import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(**kw):
    base = {"database_url": "sqlite://", "autostart": False, "sim_step_s": 10.0, "seed": 5}
    return Settings(**{**base, **kw})


@pytest.fixture
def client():
    app = create_app(_settings())
    with TestClient(app) as c:
        c.svc = app.state.service
        yield c


def advance(c, hours):
    r = c.post("/api/sim/advance", json={"hours": hours})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- state


def test_config_describes_zones_equipment_and_scenarios(client):
    cfg = client.get("/api/config").json()
    assert [z["id"] for z in cfg["zones"]] == ["A", "B", "C"]
    assert cfg["zones"][0]["targets"]["vwc"] == [0.25, 0.30]
    assert "A.fan" in cfg["actuators"] and cfg["actuators"]["pump1"]["kind"] == "pump"
    assert any(s["name"] == "hot_day" for s in cfg["scenarios"])


def test_live_state_shape(client):
    advance(client, 0.1)
    st = client.get("/api/state").json()
    assert {
        "time",
        "speed",
        "paused",
        "weather",
        "tank",
        "zones",
        "actuators",
        "alerts",
        "decisions",
        "scenarios",
        "emergency_stop",
    } <= st.keys()
    a = st["zones"]["A"]
    assert a["true"]["temp_c"] is not None and a["measured"]["temp"] is not None
    assert st["actuators"]["A.fan"]["mode"] == "auto"


def test_sensors_endpoint_reports_health(client):
    advance(client, 0.1)
    rows = client.get("/api/sensors").json()
    air = next(r for r in rows if r["sensor_id"] == "A.air" and r["quantity"] == "air_temp")
    assert air["model"] == "sht31" and air["health"] == "ok" and air["unit"] == "degC"


def test_speed_pause_resume(client):
    assert client.post("/api/sim/speed", json={"speed": 600}).json() == {"speed": 600}
    assert client.svc.runtime.engine.clock.speed == 600
    assert client.post("/api/sim/speed", json={"speed": 0}).status_code == 422
    client.post("/api/sim/pause")
    assert client.get("/api/state").json()["paused"] is True
    client.post("/api/sim/resume")
    assert client.get("/api/state").json()["paused"] is False


# --------------------------------------------------------------------------- history


def test_history_is_stored_every_sim_minute(client):
    advance(client, 2)
    h = client.get("/api/history/zones/A", params={"hours": 2, "bucket_min": 1}).json()
    assert 115 <= len(h["points"]) <= 122
    p = h["points"][-1]
    assert {"temp_c", "measured_temp_c", "vwc", "fan", "valve"} <= p.keys()
    coarse = client.get("/api/history/zones/A", params={"hours": 2, "bucket_min": 10}).json()
    assert 11 <= len(coarse["points"]) <= 13
    gh = client.get("/api/history/greenhouse", params={"hours": 2}).json()
    assert gh["points"] and "tank_pct" in gh["points"][0]
    assert client.get("/api/history/zones/Z").status_code == 404


def test_decisions_alerts_and_analytics(client):
    client.post("/api/scenarios", json={"name": "dry_soil", "params": {"zone": "A", "vwc": 0.13}})
    advance(client, 6)
    decisions = client.get("/api/decisions", params={"actuator": "A.valve"}).json()
    assert decisions and decisions[-1]["rule"] == "SOIL_LOW"
    alerts = client.get("/api/alerts").json()
    assert any(a["code"] == "SOIL_DRY" for a in alerts)
    s = client.get("/api/analytics/summary", params={"hours": 6}).json()
    a = s["zones"]["A"]
    assert a["water"]["irrigation_l"] > 100
    assert a["irrigation_minutes"] > 30
    assert a["equipment"]["A.valve"]["activations"] >= 1
    assert s["pump"]["runtime_h"] > 0.5
    assert {"pump", "valve", "fan"} <= s["energy_kwh_by_kind"].keys()
    assert set(a["violation_minutes"]) == {"temp", "rh", "vwc"}


# --------------------------------------------------------------------------- scenarios & control


def test_scenarios_start_stop_and_validation(client):
    r = client.post("/api/scenarios", json={"name": "hot_day", "duration_h": 2})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.get("/api/scenarios").json()["active"][0]["name"] == "hot_day"
    assert client.delete(f"/api/scenarios/{sid}").status_code == 204
    assert client.get("/api/scenarios").json()["active"] == []
    assert client.post("/api/scenarios", json={"name": "meteor"}).status_code == 404
    bad = client.post("/api/scenarios", json={"name": "hot_day", "params": {"banana": 1}})
    assert bad.status_code == 422
    assert client.delete("/api/scenarios/999").status_code == 404


def test_override_and_mode(client):
    r = client.post("/api/actuators/C.fan/override", json={"level": 1, "duration_min": 30})
    assert r.status_code == 200 and r.json()["mode"] == "manual"
    advance(client, 0.05)
    assert client.get("/api/state").json()["actuators"]["C.fan"]["level"] == 1.0
    client.post("/api/actuators/C.fan/mode", json={"mode": "auto"})
    assert client.svc.runtime.controller.modes["C.fan"].mode == "auto"
    assert client.post("/api/actuators/X.fan/override", json={"level": 1}).status_code == 404
    assert client.post("/api/actuators/A.fan/mode", json={"mode": "turbo"}).status_code == 422


def test_emergency_stop_and_reset(client):
    client.post("/api/actuators/A.fan/override", json={"level": 1})
    advance(client, 0.05)
    assert client.post("/api/emergency-stop", json={"reason": "test"}).json()["emergency_stop"]
    advance(client, 0.1)
    st = client.get("/api/state").json()
    assert st["emergency_stop"] and all(a["level"] == 0 for a in st["actuators"].values())
    assert any(a["code"] == "EMERGENCY_STOP" for a in st["alerts"])
    client.post("/api/emergency-stop/reset")
    advance(client, 0.05)
    assert client.get("/api/state").json()["actuators"]["A.fan"]["level"] == 1.0


def test_latched_alarm_reset(client):
    assert (
        client.post(
            "/api/alerts/reset", json={"code": "PUMP_NO_FLOW", "scope": "pump1"}
        ).status_code
        == 404
    )
    client.post("/api/scenarios", json={"name": "dry_soil", "params": {"zone": "A", "vwc": 0.24}})
    client.post("/api/scenarios", json={"name": "pump_failure", "duration_h": 0.2})
    advance(client, 0.5)
    assert any(a["code"] == "PUMP_NO_FLOW" for a in client.get("/api/state").json()["alerts"])
    r = client.post("/api/alerts/reset", json={"code": "PUMP_NO_FLOW", "scope": "pump1"})
    assert r.status_code == 200
    advance(client, 0.05)
    assert client.svc.runtime.engine.actuators["pump1"].actual == 1


# --------------------------------------------------------------------------- runs


def test_reset_starts_new_run_and_prunes_old_runs():
    app = create_app(_settings(keep_runs=2))
    with TestClient(app) as c:
        first = c.get("/api/runs").json()[0]["id"]
        advance(c, 0.5)
        for _ in range(3):
            c.post("/api/sim/reset", json={"seed": 1})
        runs = c.get("/api/runs").json()
        assert len(runs) == 2 and runs[0]["current"] and first not in [r["id"] for r in runs]
        assert c.get("/api/history/zones/A", params={"hours": 1}).json()["points"] == []


# --------------------------------------------------------------------------- live


def test_websocket_streams_live_state(client):
    with client.websocket_connect("/ws/live") as ws:
        a = ws.receive_json()
        b = ws.receive_json()
    assert a["zones"]["A"]["true"]["temp_c"] is not None
    assert b["run_id"] == a["run_id"]


def test_background_loop_advances_simulation():
    app = create_app(_settings(autostart=True, sim_speed=600, loop_interval_s=0.05))
    with TestClient(app) as c:
        t0 = c.get("/api/state").json()["time"]
        time.sleep(0.6)
        t1 = c.get("/api/state").json()["time"]
    assert t1 > t0
