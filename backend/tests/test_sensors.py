from datetime import datetime, timedelta

import numpy as np
import pytest

from agrisense_core.devices.interfaces import Quality
from agrisense_core.devices.sensors import (
    BH1750,
    DS18B20,
    JSNSR04T,
    SCD30,
    SHT31,
    YFS201,
    CapacitiveSoil,
    SensorFault,
)

T0 = datetime(2026, 3, 21, 12)


def _series(sensor, n, step_s=5):
    return [sensor.read(T0 + timedelta(seconds=i * step_s)) for i in range(n)]


def test_sht31_accuracy_resolution_and_raw_words():
    errs = []
    for seed in range(40):
        s = SHT31(
            "t", "A", 5, lambda: {"air_temp": 25.0, "air_rh": 60.0}, np.random.default_rng(seed)
        )
        r = _series(s, 5)[-1]
        errs.append(r[0].value - 25.0)
        assert 0 <= r[0].raw <= 65535 and isinstance(r[0].raw, int)
    assert max(abs(e) for e in errs) < 0.6  # datasheet +/-0.3 typical, allow tails
    assert np.std(errs) > 0.02  # every unit has its own bias


def test_sht31_lags_a_step_change():
    truth = {"air_temp": 20.0, "air_rh": 50.0}
    s = SHT31("t", "A", 1, lambda: truth, np.random.default_rng(0))
    s.read(T0)
    truth["air_temp"] = 30.0
    first = s.read(T0 + timedelta(seconds=2))[0].value
    later = s.read(T0 + timedelta(seconds=60))[0].value
    assert first < 25 and later > 29


def test_capacitive_soil_calibration_and_raw_counts():
    truth = {"soil_vwc": 0.30, "soil_temp": 25.0}
    s = CapacitiveSoil(
        "s",
        "A",
        10,
        lambda: truth,
        np.random.default_rng(1),
        {"raw_at_vwc0": 3300, "raw_at_vwc50": 1400},
    )
    r = _series(s, 3)[-1][0]
    assert 1400 < r.raw < 3300  # wetter soil = lower ADC count
    assert r.value == pytest.approx(30, abs=2.5)
    assert r.unit == "%"


def test_capacitive_soil_temperature_drift():
    truth = {"soil_vwc": 0.30, "soil_temp": 25.0}
    s = CapacitiveSoil("s", "A", 10, lambda: truth, np.random.default_rng(1))
    cool = np.mean([x[0].value for x in _series(s, 20)])
    truth["soil_temp"] = 40.0
    warm = np.mean([x[0].value for x in _series(s, 20)])
    assert warm < cool  # raw rises with temperature, so the soil reads drier


def test_ds18b20_resolution():
    s = DS18B20("d", "A", 30, lambda: {"soil_temp": 24.3}, np.random.default_rng(0))
    v = s.read(T0)[0].value
    assert (v / 0.0625) == pytest.approx(round(v / 0.0625))


def test_bh1750_saturates_in_full_sun():
    s = BH1750("l", "A", 5, lambda: {"lux": 80000.0}, np.random.default_rng(0))
    r = s.read(T0)[0]
    assert r.quality is Quality.SATURATED
    assert r.value == pytest.approx(65535 / 1.2, abs=1)


def test_scd30_warmup_then_ok():
    s = SCD30("c", "A", 5, lambda: {"co2_ppm": 800.0}, np.random.default_rng(0))
    assert s.read(T0)[0].quality is Quality.WARMING_UP
    r = s.read(T0 + timedelta(seconds=300))[0]
    assert r.quality is Quality.OK and abs(r.value - 800) < 30 + 0.03 * 800 + 20


def test_ultrasonic_tank_level_and_blind_zone():
    truth = {"tank_level_frac": 0.5, "tank_height_m": 1.5, "air_temp": 20.0}
    s = JSNSR04T("u", None, 10, lambda: truth, np.random.default_rng(5))
    ok = [r[0] for r in _series(s, 50) if r[0].quality is Quality.OK]
    assert abs(np.mean([r.value for r in ok]) - 50) < 1.0
    s.MOUNT_GAP_M = 0.1  # mounted too close: a full tank is inside the blind zone
    truth["tank_level_frac"] = 1.0
    assert s.read(T0 + timedelta(hours=1))[0].quality is Quality.TIMEOUT


def test_flow_meter_counts_pulses():
    state = {"flow_total_l": 0.0}
    s = YFS201("f", None, 5, lambda: state, np.random.default_rng(0))
    s.read(T0)
    state["flow_total_l"] = 1.0  # 1 L in 5 s = 12 L/min
    r = s.read(T0 + timedelta(seconds=5))[0]
    assert r.value == pytest.approx(12, rel=0.1)
    assert 400 < r.raw < 500
    state["flow_total_l"] = 1.02  # 0.24 L/min: below the rotor's minimum flow
    assert s.read(T0 + timedelta(seconds=10))[0].value == 0


@pytest.mark.parametrize("fault", list(SensorFault))
def test_fault_injection(fault):
    s = DS18B20("d", "A", 1, lambda: {"soil_temp": 20.0}, np.random.default_rng(0))
    good = _series(s, 5)[-1][0].value
    s.inject_fault(fault, magnitude=5.0, now=T0)
    later = [s.read(T0 + timedelta(hours=1, seconds=i))[0] for i in range(30)]
    if fault is SensorFault.DROPOUT:
        assert all(r.value is None and r.quality is Quality.TIMEOUT for r in later)
    elif fault is SensorFault.STUCK:
        assert all(r.value == good for r in later)
    elif fault in (SensorFault.OFFSET, SensorFault.DRIFT):
        assert all(abs(r.value - 25) < 1 for r in later)  # drift: 5 units/h after 1 h
    elif fault is SensorFault.SPIKE:
        assert any(abs(r.value - 20) > 4 for r in later)
