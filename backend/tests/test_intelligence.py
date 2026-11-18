import numpy as np
import pytest

from agrisense_core.intelligence import optimize
from agrisense_core.intelligence.advisor import advise
from agrisense_core.intelligence.anomaly import AnomalyDetector
from agrisense_core.intelligence.dataset import RunSpec, fault_schedule, load_runs
from agrisense_core.intelligence.features import (
    FORECAST,
    hours_to_next_irrigation,
    lag,
    linear_baseline,
    minutes_since_change,
    rolling_mean,
    rolling_std,
)
from agrisense_core.intelligence.forecast import IrrigationForecaster
from agrisense_core.intelligence.live import LiveIntelligence
from agrisense_core.runtime import GreenhouseRuntime

# --------------------------------------------------------------------------- feature helpers


def test_rolling_mean_and_std_ignore_nan():
    x = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    m = rolling_mean(x, 2)
    assert m[0] == 1.0 and m[1] == 1.5 and m[2] == 2.0 and m[3] == 4.0 and m[4] == 4.5
    assert rolling_std(np.array([2.0, 2.0, 2.0]), 3)[-1] == pytest.approx(0.0)
    assert np.isnan(rolling_mean(np.array([np.nan, np.nan]), 2)).all()


def test_lag_and_minutes_since_change():
    x = np.array([1.0, 1.0, 1.0, 2.0, 2.0])
    assert np.isnan(lag(x, 2)[:2]).all() and lag(x, 2)[3] == 1.0
    assert minutes_since_change(x).tolist() == [0, 1, 2, 0, 1]


def test_hours_to_next_irrigation_target():
    irr = np.zeros(300)
    irr[120:150] = 1  # irrigation starts at minute 120
    y = hours_to_next_irrigation(irr, cap_h=48)
    assert y[0] == pytest.approx(2.0) and y[60] == pytest.approx(1.0)
    assert np.isnan(y[130])  # not forecast while irrigating
    assert np.isnan(y[200])  # censored: no later event, run too short to know


def test_linear_baseline_extrapolates_trend():
    x = np.zeros((2, len(FORECAST)))
    x[:, FORECAST.index("gap_to_start")] = 2.0  # 2 % above the start threshold
    x[0, FORECAST.index("slope180")] = -0.5  # drying 0.5 %/h
    x[1, FORECAST.index("slope180")] = 0.1  # wetting
    assert linear_baseline(x).tolist() == [4.0, 48.0]


def test_fault_schedule_is_reproducible_and_never_overlaps_on_a_sensor():
    a = fault_schedule(7, 4, ["A", "B", "C"])
    assert a == fault_schedule(7, 4, ["A", "B", "C"]) and len(a) >= 10
    by_sensor: dict[str, int] = {}
    for ev in sorted(a, key=lambda e: e.start_min):
        assert ev.start_min >= by_sensor.get(ev.sensor, 0)
        by_sensor[ev.sensor] = ev.start_min + int(ev.duration_h * 60)


# --------------------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def tiny_models(tmp_path_factory, config):
    cache = tmp_path_factory.mktemp("ml")
    specs = [RunSpec("healthy", 11, 1.0), RunSpec("healthy", 12, 0.6), RunSpec("fault", 13, 1.0)]
    healthy, calib, faulty = load_runs(specs, cache, workers=1, progress=lambda *_: None)
    zones = ["A", "B", "C"]
    det = AnomalyDetector().fit([healthy], [calib], [faulty], zones, progress=lambda *_: None)
    fc = IrrigationForecaster().fit([healthy, faulty], config)
    return det, fc, faulty


def test_detectors_train_and_evaluate(tiny_models):
    det, _, faulty = tiny_models
    res = det.evaluate([faulty])
    assert set(res["methods"]) == {"rules", "isolation", "virtual", "supervised"}
    for m in res["methods"].values():
        assert 0 <= m["precision"] <= 1 and 0 <= m["recall"] <= 1
    # The supervised model has seen these exact faults: it must find most of them.
    assert res["methods"]["supervised"]["recall"] > 0.5


def test_virtual_sensor_flags_an_offset(tiny_models, config):
    import joblib

    det, fc, _ = tiny_models
    rt = GreenhouseRuntime(config, seed=21, step_s=10.0)
    live = LiveIntelligence(config, ml_dir=__import__("pathlib").Path("does-not-exist"))
    live.bundle = {"anomaly": det, "forecaster": fc, "meta": {"trained_at": "test"}}
    for _ in range(240):
        rt.run_for(60)
        live.record(rt)
    rt.engine.scenarios.start("sensor_failure", sensor="B.air", fault="offset", magnitude=5.0)
    for _ in range(45):
        rt.run_for(60)
        live.record(rt)
    rows = {a["channel"]: a for a in live.anomalies()}
    assert rows["B.air/air_temp"]["flagged"]
    assert rows["B.air/air_temp"]["residual"] > 2
    forecast = live.forecast()
    assert {f["zone_id"] for f in forecast} == {"A", "B", "C"}
    assert all(f["irrigating_now"] or 0 <= f["hours_model"] <= 48 for f in forecast)
    del joblib


# --------------------------------------------------------------------------- optimisation & advice


def test_apply_params_overrides_control_config(config):
    tuned = optimize.apply(config, {"climate.stage1_level": 0.7, "climate.temp_band_c": 2.0})
    assert tuned.control.climate.stage1_level == 0.7 and tuned.control.climate.temp_band_c == 2.0
    assert config.control.climate.stage1_level == 0.5  # original untouched
    assert set(optimize.default_params(config)) == {f"{s}.{k}" for s, k in optimize.SPACE}


def _summary(**zone_over):
    zone = {
        "name": "Zone C",
        "crop": "lettuce",
        "samples": 1440,
        "temp_c": {"min": 25.0, "mean": 28.0, "max": 32.0},
        "rh_pct": {"min": 60.0, "mean": 84.0, "max": 95.0},
        "vwc": {"min": 0.30, "mean": 0.31, "max": 0.33},
        "co2_ppm": {"min": 300.0, "mean": 410.0, "max": 470.0},
        "water": {"irrigation_l": 100.0, "et_l": 200.0},
        "irrigation_minutes": 60,
        "violation_minutes": {"temp": 22 * 60, "rh": 14 * 60, "vwc": 0},
        "equipment": {"C.fan": {"energy_kwh": 5.0, "runtime_h": 20.0, "activations": 3}},
    }
    zone.update(zone_over)
    return {
        "hours": 24.0,
        "zones": {"C": zone},
        "alerts_by_code": {"IRRIGATION_TIMEOUT": 1},
        "energy_kwh_by_kind": {"fan": 9.0, "pump": 0.1},
        "energy_kwh_total": 9.1,
    }


def test_advisor_explains_hot_lettuce_and_other_issues(config):
    advice = advise(_summary(), config)
    titles = " | ".join(a["title"] for a in advice)
    hot = next(a for a in advice if "too warm" in a["title"])
    assert hot["zone_id"] == "C" and "cool-season" in hot["detail"] and "shade" in hot["detail"]
    assert "humidity high" in titles and "CO₂" in titles and "time limit" in titles
    assert "Fans use" in titles
    assert all(a["evidence"] for a in advice)
    assert [a["severity"] for a in advice] == sorted(
        (a["severity"] for a in advice), key=["critical", "warning", "info"].index
    )


def test_advisor_needs_history(config):
    s = _summary()
    s["hours"] = 2
    assert advise(s, config)[0]["title"] == "Not enough history yet"
