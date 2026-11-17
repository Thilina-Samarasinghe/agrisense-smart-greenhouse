"""Hardware-independent device contracts.

Simulated drivers implement these today; MQTT drivers for real ESP32 devices implement the same
contracts later, so the automation engine and the API never know which one they are talking to.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Quality(StrEnum):
    OK = "ok"
    SATURATED = "saturated"  # reading clipped at the sensor's range limit
    WARMING_UP = "warming_up"
    FAULT = "fault"  # device reports an error or returns garbage
    TIMEOUT = "timeout"  # no response (e.g. ultrasonic echo lost)


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    zone_id: str | None
    quantity: str  # e.g. "air_temp", "soil_vwc"
    value: float | None
    unit: str
    raw: float | None
    quality: Quality
    ts: datetime

    def to_message(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        d["quality"] = str(self.quality)
        return d


@dataclass(frozen=True)
class Command:
    actuator_id: str
    level: float  # 0 = off, 1 = fully on; fans may use 0..1 for PWM speed
    reason: str = "manual"
    ttl_s: float | None = None  # fail-safe: actuator turns off when the command expires


@dataclass
class ActuatorStatus:
    actuator_id: str
    kind: str
    zone_id: str | None
    commanded: float
    actual: float
    fault: str | None
    runtime_s: float
    energy_wh: float
    starts: int
    reason: str
    extra: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class SensorDriver(Protocol):
    sensor_id: str
    zone_id: str | None

    def due(self, now: datetime) -> bool: ...

    def read(self, now: datetime) -> list[Reading]: ...


@runtime_checkable
class ActuatorDriver(Protocol):
    actuator_id: str

    def command(self, cmd: Command, now: datetime) -> None: ...

    def status(self) -> ActuatorStatus: ...


# MQTT-compatible topic layout shared by the in-process bus and future real devices.


def sensor_topic(greenhouse_id: str, zone_id: str | None, sensor_id: str) -> str:
    return f"agrisense/{greenhouse_id}/{zone_id or 'gh'}/sensor/{sensor_id}"


def actuator_set_topic(greenhouse_id: str, zone_id: str | None, actuator_id: str) -> str:
    return f"agrisense/{greenhouse_id}/{zone_id or 'gh'}/actuator/{actuator_id}/set"


def actuator_state_topic(greenhouse_id: str, zone_id: str | None, actuator_id: str) -> str:
    return f"agrisense/{greenhouse_id}/{zone_id or 'gh'}/actuator/{actuator_id}/state"
