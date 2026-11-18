"""Sensor health monitoring.

Every reading the controller uses passes through here first. A channel (one quantity of one
sensor) is only *usable* when its latest accepted reading is fresh, plausible and not flagged.

Detected problems
-----------------
STALE         no good reading for a while (dropout, wiring, dead device)
OUT_OF_RANGE  physically implausible value
SPIKES        repeated jumps faster than physics allows (loose connector, EMI)
STUCK         value frozen although the quantity always fluctuates
SATURATED     at the sensor's range limit; still usable as a lower/upper bound
WARMING_UP    device not ready yet (e.g. NDIR CO2 sensor)

Gradual drift or a constant offset on a single sensor cannot be detected by rules alone; it
needs a redundant sensor (soil probes are compared) or the Phase 4 anomaly detector.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from agrisense_core.config import SensorHealthControl


class Health(StrEnum):
    OK = "ok"
    SATURATED = "saturated"
    WARMING_UP = "warming_up"
    STALE = "stale"
    OUT_OF_RANGE = "out_of_range"
    SPIKES = "spikes"
    STUCK = "stuck"
    NO_DATA = "no_data"


USABLE = {Health.OK, Health.SATURATED}


@dataclass
class Channel:
    sensor_id: str
    zone_id: str | None
    quantity: str
    sample_interval_s: float
    value: float | None = None  # last accepted value
    accepted_at: datetime | None = None
    last_seen: datetime | None = None
    last_quality: str = "ok"
    last_change_at: datetime | None = None
    health: Health = Health.NO_DATA
    rejected: deque[datetime] = field(default_factory=deque)
    candidates: list[float] = field(default_factory=list)
    range_violation: bool = False

    @property
    def usable(self) -> bool:
        return self.health in USABLE and self.value is not None


class HealthMonitor:
    def __init__(self, cfg: SensorHealthControl) -> None:
        self.cfg = cfg
        self.channels: dict[tuple[str, str], Channel] = {}

    def register(
        self, sensor_id: str, zone_id: str | None, quantity: str, sample_interval_s: float
    ) -> Channel:
        ch = Channel(sensor_id, zone_id, quantity, sample_interval_s)
        self.channels[(sensor_id, quantity)] = ch
        return ch

    def channel(self, sensor_id: str, quantity: str) -> Channel | None:
        return self.channels.get((sensor_id, quantity))

    # ------------------------------------------------------------------ ingest

    def ingest(self, msg: dict[str, Any]) -> None:
        """Accept a reading message as published on the bus (Reading.to_message())."""
        key = (msg["sensor_id"], msg["quantity"])
        ch = self.channels.get(key)
        if ch is None:
            ch = self.register(msg["sensor_id"], msg.get("zone_id"), msg["quantity"], 10.0)
        ts = msg["ts"] if isinstance(msg["ts"], datetime) else datetime.fromisoformat(msg["ts"])
        ch.last_seen = ts
        ch.last_quality = msg["quality"]
        value = msg["value"]
        if value is None or msg["quality"] in ("timeout", "fault"):
            return  # nothing to accept; staleness is evaluated in evaluate()
        if msg["quality"] == "warming_up":
            ch.health = Health.WARMING_UP
            return

        lo, hi = self.cfg.ranges.get(ch.quantity, (float("-inf"), float("inf")))
        ch.range_violation = not (lo <= value <= hi)
        if ch.range_violation:
            return

        if self._is_spike(ch, value, ts):
            return

        if ch.value is None or value != ch.value:
            ch.last_change_at = ts
        ch.value = value
        ch.accepted_at = ts
        ch.candidates.clear()

    def _is_spike(self, ch: Channel, value: float, ts: datetime) -> bool:
        rate = self.cfg.max_rate_per_s.get(ch.quantity)
        if rate is None or ch.value is None or ch.accepted_at is None:
            return False
        dt = max(1.0, (ts - ch.accepted_at).total_seconds())
        if abs(value - ch.value) <= rate * dt:
            return False
        # A genuine step change (e.g. a door opening) produces consistent new readings:
        # three mutually consistent "jumps" re-baseline the channel instead of being rejected.
        ch.candidates.append(value)
        tol = rate * ch.sample_interval_s * 2
        if len(ch.candidates) >= 3 and max(ch.candidates) - min(ch.candidates) <= tol:
            ch.candidates.clear()
            return False
        ch.rejected.append(ts)
        return True

    # ------------------------------------------------------------------ evaluate

    def evaluate(self, now: datetime) -> None:
        c = self.cfg
        for ch in self.channels.values():
            while ch.rejected and (now - ch.rejected[0]).total_seconds() > c.spike_window_s:
                ch.rejected.popleft()
            stale_after = max(c.stale_after_s, 3 * ch.sample_interval_s)

            if ch.health is Health.WARMING_UP and ch.last_quality == "warming_up":
                continue
            if ch.accepted_at is None and ch.last_seen is None:
                ch.health = Health.NO_DATA
            elif (
                ch.range_violation
                and ch.last_seen is not None
                and (ch.accepted_at is None or ch.last_seen > ch.accepted_at)
            ):
                ch.health = Health.OUT_OF_RANGE
            elif len(ch.rejected) >= c.spike_limit:
                ch.health = Health.SPIKES
            elif ch.accepted_at is None or (now - ch.accepted_at).total_seconds() > stale_after:
                ch.health = Health.STALE
            elif (
                ch.quantity in c.stuck_quantities
                and ch.last_change_at is not None
                and ch.last_quality != "saturated"
                and (now - ch.last_change_at).total_seconds() > c.stuck_window_s
            ):
                ch.health = Health.STUCK
            elif ch.last_quality == "saturated":
                ch.health = Health.SATURATED
            else:
                ch.health = Health.OK

    def value(self, sensor_id: str, quantity: str) -> float | None:
        ch = self.channels.get((sensor_id, quantity))
        return ch.value if ch and ch.usable else None

    def summary(self) -> dict[str, dict[str, Any]]:
        return {
            f"{ch.sensor_id}/{ch.quantity}": {
                "health": str(ch.health),
                "value": ch.value,
                "accepted_at": ch.accepted_at.isoformat() if ch.accepted_at else None,
            }
            for ch in self.channels.values()
        }
