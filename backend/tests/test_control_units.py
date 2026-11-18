from datetime import datetime, timedelta

import pytest

from agrisense_core.config import SensorHealthControl
from agrisense_core.control.alerts import AlertManager, Severity
from agrisense_core.control.health import Health, HealthMonitor
from agrisense_core.control.hysteresis import Hysteresis, MinTimes

T0 = datetime(2026, 3, 21, 12)


# --------------------------------------------------------------------------- hysteresis


def test_rising_hysteresis_does_not_chatter():
    h = Hysteresis(on_at=28.0, off_at=26.5)
    states = [h.update(v) for v in (27.9, 28.0, 27.9, 27.0, 26.6, 26.5, 27.9)]
    assert states == [False, True, True, True, True, False, False]


def test_falling_hysteresis_and_threshold_change():
    h = Hysteresis(on_at=25.0, off_at=28.0, rising=False)
    assert h.update(24.9) is True
    assert h.update(27.0) is True
    assert h.update(28.0) is False
    assert h.update(26.0, on_at=26.5, off_at=29.0) is True


def test_invalid_hysteresis_rejected():
    with pytest.raises(ValueError):
        Hysteresis(on_at=26.0, off_at=28.0, rising=True)


def test_min_times_hold_switching():
    m = MinTimes(min_on_s=300, min_off_s=120)
    m.record(1.0, T0)
    assert m.allowed(0.0, T0 + timedelta(seconds=100)) == 1.0  # must stay on
    assert m.allowed(0.0, T0 + timedelta(seconds=300)) == 0.0
    m.record(0.0, T0 + timedelta(seconds=300))
    assert m.allowed(1.0, T0 + timedelta(seconds=360)) == 0.0  # must rest
    assert m.allowed(1.0, T0 + timedelta(seconds=420)) == 1.0
    m.record(0.5, T0 + timedelta(seconds=420))
    assert m.allowed(1.0, T0 + timedelta(seconds=421)) == 1.0  # speed change while on is free


# --------------------------------------------------------------------------- alerts


def test_alerts_deduplicate_clear_and_latch():
    seen = []
    am = AlertManager(on_change=seen.append)
    a = am.raise_("TANK_LOW", Severity.WARNING, "low", T0, subject="tank")
    assert am.raise_("TANK_LOW", Severity.WARNING, "low again", T0, subject="tank") is a
    am.clear("TANK_LOW", T0, "tank")
    assert not am.is_active("TANK_LOW", "tank") and a.cleared_at == T0

    am.raise_("PUMP_NO_FLOW", Severity.CRITICAL, "no flow", T0, subject="pump1", latched=True)
    am.clear("PUMP_NO_FLOW", T0, "pump1")
    assert am.is_active("PUMP_NO_FLOW", "pump1")  # latched: cause gone is not enough
    am.clear("PUMP_NO_FLOW", T0, "pump1", force=True)
    assert not am.is_active("PUMP_NO_FLOW", "pump1")
    assert len(seen) == 4


# --------------------------------------------------------------------------- sensor health


CFG = SensorHealthControl(
    ranges={"air_temp": (-10, 60)},
    max_rate_per_s={"air_temp": 0.5},
    stuck_quantities=["air_temp"],
)


def _monitor():
    hm = HealthMonitor(CFG)
    hm.register("A.air", "A", "air_temp", 5)
    return hm


def _msg(value, t, quality="ok"):
    return {
        "sensor_id": "A.air",
        "zone_id": "A",
        "quantity": "air_temp",
        "value": value,
        "unit": "degC",
        "raw": None,
        "quality": quality,
        "ts": t.isoformat(),
    }


def _feed(hm, values, start=T0, step=5):
    t = start
    for v in values:
        hm.ingest(_msg(v, t))
        t += timedelta(seconds=step)
    hm.evaluate(t)
    return t


def _ch(hm):
    return hm.channel("A.air", "air_temp")


def test_healthy_channel_is_usable():
    hm = _monitor()
    _feed(hm, [25.0, 25.1, 25.05])
    assert _ch(hm).health is Health.OK and hm.value("A.air", "air_temp") == 25.05


def test_no_data_and_stale():
    hm = _monitor()
    hm.evaluate(T0)
    assert _ch(hm).health is Health.NO_DATA
    t = _feed(hm, [25.0])
    hm.evaluate(t + timedelta(seconds=31))
    assert _ch(hm).health is Health.STALE and hm.value("A.air", "air_temp") is None


def test_dropouts_make_channel_stale():
    hm = _monitor()
    t = _feed(hm, [25.0])
    for i in range(10):
        hm.ingest(_msg(None, t + timedelta(seconds=5 * i), quality="timeout"))
    hm.evaluate(t + timedelta(seconds=50))
    assert _ch(hm).health is Health.STALE


def test_out_of_range():
    hm = _monitor()
    _feed(hm, [25.0, 85.0])
    assert _ch(hm).health is Health.OUT_OF_RANGE


def test_spikes_detected():
    hm = _monitor()
    _feed(hm, [25.0, 31.0, 25.1, 19.0, 25.0, 31.2, 25.1])
    assert _ch(hm).health is Health.SPIKES
    assert _ch(hm).value == pytest.approx(25.1)  # spikes never became the accepted value


def test_genuine_step_change_is_accepted():
    hm = _monitor()
    _feed(hm, [25.0, 25.0, 30.0, 30.1, 30.0, 30.1])
    assert _ch(hm).value == pytest.approx(30.1)
    assert _ch(hm).health is Health.OK


def test_stuck_value_detected():
    hm = _monitor()
    _feed(hm, [25.0, 25.1] + [25.2] * 130)
    assert _ch(hm).health is Health.STUCK


def test_warming_up_then_ok():
    hm = _monitor()
    hm.ingest(_msg(400.0, T0, quality="warming_up"))
    hm.evaluate(T0)
    assert _ch(hm).health is Health.WARMING_UP and not _ch(hm).usable
    hm.ingest(_msg(25.0, T0 + timedelta(seconds=5)))
    hm.evaluate(T0 + timedelta(seconds=5))
    assert _ch(hm).usable


def test_saturated_reading_still_usable():
    hm = _monitor()
    hm.ingest(_msg(25.0, T0, quality="saturated"))
    hm.evaluate(T0)
    assert _ch(hm).health is Health.SATURATED and _ch(hm).usable
