"""Hysteresis switches and minimum on/off timing.

A plain threshold makes equipment chatter: a fan switching at exactly 28.0 degC would turn on
and off every few seconds as the reading wobbles around 28.0. Hysteresis uses two thresholds
(ON at 28.0, OFF at 26.5) and minimum run/rest times protect motors and relays.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Hysteresis:
    """Two-threshold switch.

    rising=True: ON when value >= on_at, OFF when value <= off_at (cooling, ventilation).
    rising=False: ON when value <= on_at, OFF when value >= off_at (irrigation, heating).
    """

    on_at: float
    off_at: float
    rising: bool = True
    state: bool = False

    def __post_init__(self) -> None:
        if self.rising and self.off_at > self.on_at:
            raise ValueError("rising hysteresis needs off_at <= on_at")
        if not self.rising and self.off_at < self.on_at:
            raise ValueError("falling hysteresis needs off_at >= on_at")

    def update(self, value: float, on_at: float | None = None, off_at: float | None = None) -> bool:
        """Feed a new value; thresholds may be changed on the fly (e.g. day vs night targets)."""
        if on_at is not None:
            self.on_at = on_at
        if off_at is not None:
            self.off_at = off_at
        if self.rising:
            if not self.state and value >= self.on_at:
                self.state = True
            elif self.state and value <= self.off_at:
                self.state = False
        else:
            if not self.state and value <= self.on_at:
                self.state = True
            elif self.state and value >= self.off_at:
                self.state = False
        return self.state


@dataclass
class MinTimes:
    """Remembers when an actuator last changed and holds it for its minimum on/off time."""

    min_on_s: float = 0.0
    min_off_s: float = 0.0
    level: float = 0.0
    changed_at: datetime | None = None

    def allowed(self, desired: float, now: datetime) -> float:
        """Return the level to use: `desired` unless a minimum time forbids switching."""
        if self.changed_at is None:
            return desired
        elapsed = (now - self.changed_at).total_seconds()
        if self.level > 0 and desired == 0 and elapsed < self.min_on_s:
            return self.level
        if self.level == 0 and desired > 0 and elapsed < self.min_off_s:
            return 0.0
        return desired

    def record(self, level: float, now: datetime) -> None:
        if (level > 0) != (self.level > 0) or self.changed_at is None:
            self.changed_at = now
        self.level = level
