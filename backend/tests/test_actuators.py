from datetime import datetime, timedelta

from agrisense_core.devices.actuators import ActuatorFault, SimActuator
from agrisense_core.devices.interfaces import Command

T0 = datetime(2026, 1, 1)


def _run(a, seconds, start=T0):
    for i in range(seconds):
        a.update(1.0, start + timedelta(seconds=i))


def test_startup_delay_and_metering():
    a = SimActuator("p", "pump", None, power_w=60, startup_delay_s=3)
    a.command(Command("p", 1), T0)
    _run(a, 2)
    assert a.actual == 0
    _run(a, 3600)
    assert a.actual == 1 and a.starts == 1
    assert abs(a.energy_wh - 60) < 0.2


def test_on_off_device_rounds_level_and_pwm_fan_keeps_it():
    valve = SimActuator("v", "valve", "A", 5)
    valve.command(Command("v", 0.7), T0)
    fan = SimActuator("f", "fan", "A", 240, proportional=True)
    fan.command(Command("f", 0.4), T0)
    _run(valve, 1)
    _run(fan, 1)
    assert valve.actual == 1 and fan.actual == 0.4


def test_ttl_fail_safe():
    a = SimActuator("f", "fan", "A", 100)
    a.command(Command("f", 1, ttl_s=10), T0)
    _run(a, 20)
    assert a.actual == 0 and a.reason == "ttl_expired"


def test_faults():
    a = SimActuator("p", "pump", None, 60)
    a.fault = ActuatorFault.FAILED
    a.command(Command("p", 1), T0)
    _run(a, 5)
    assert a.actual == 1 and a.output == 0 and a.energy_wh > 0  # draws power, does nothing
    a.fault = ActuatorFault.STUCK_ON
    a.command(Command("p", 0), T0)
    _run(a, 1)
    assert a.output == 1
    a.fault = ActuatorFault.STUCK_OFF
    a.command(Command("p", 1), T0)
    _run(a, 1)
    assert a.output == 0
