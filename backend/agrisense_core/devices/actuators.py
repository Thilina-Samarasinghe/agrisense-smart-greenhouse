"""Simulated actuators with real-world behaviour: start-up delay, power draw, metering, faults
and command time-to-live (the same fail-safe the ESP32 firmware will implement)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from agrisense_core.devices.interfaces import ActuatorStatus, Command


class ActuatorFault(StrEnum):
    FAILED = "failed"  # receives power but produces no effect (seized pump, broken fan belt)
    STUCK_ON = "stuck_on"  # relay welded closed: runs regardless of commands
    STUCK_OFF = "stuck_off"  # relay or wiring open: never runs


class SimActuator:
    def __init__(
        self,
        actuator_id: str,
        kind: str,
        zone_id: str | None,
        power_w: float,
        startup_delay_s: float = 0.0,
        proportional: bool = False,
    ) -> None:
        self.actuator_id = actuator_id
        self.kind = kind
        self.zone_id = zone_id
        self.power_w = power_w
        self.startup_delay_s = startup_delay_s
        self.proportional = proportional  # True for PWM fans; False means on/off only
        self.commanded = 0.0
        self.actual = 0.0
        self.reason = "init"
        self.fault: ActuatorFault | None = None
        self.runtime_s = 0.0
        self.energy_wh = 0.0
        self.starts = 0
        self._pending_s = 0.0
        self._expires_at: datetime | None = None

    # -- driver interface ------------------------------------------------------------------

    def command(self, cmd: Command, now: datetime) -> None:
        level = max(0.0, min(1.0, cmd.level))
        if not self.proportional:
            level = 1.0 if level >= 0.5 else 0.0
        if level > 0 and self.commanded == 0:
            self._pending_s = self.startup_delay_s
        self.commanded = level
        self.reason = cmd.reason
        self._expires_at = now + timedelta(seconds=cmd.ttl_s) if cmd.ttl_s else None

    def status(self) -> ActuatorStatus:
        return ActuatorStatus(
            actuator_id=self.actuator_id,
            kind=self.kind,
            zone_id=self.zone_id,
            commanded=self.commanded,
            actual=self.actual,
            fault=str(self.fault) if self.fault else None,
            runtime_s=self.runtime_s,
            energy_wh=self.energy_wh,
            starts=self.starts,
            reason=self.reason,
        )

    # -- simulation ------------------------------------------------------------------------

    def update(self, dt: float, now: datetime) -> None:
        if self._expires_at is not None and now >= self._expires_at:
            self.commanded = 0.0
            self.reason = "ttl_expired"
            self._expires_at = None

        target = self.commanded
        if self.fault is ActuatorFault.STUCK_ON:
            target = 1.0
        elif self.fault is ActuatorFault.STUCK_OFF:
            target = 0.0

        was_running = self.actual > 0
        if target == 0:
            self.actual = 0.0
        elif self._pending_s > 0 and self.fault is not ActuatorFault.STUCK_ON:
            self._pending_s = max(0.0, self._pending_s - dt)
            self.actual = 0.0 if self._pending_s > 0 else target
        else:
            self.actual = target

        if self.actual > 0:
            if not was_running:
                self.starts += 1
            self.runtime_s += dt
            self.energy_wh += self.power_w * self.actual * dt / 3600

    @property
    def output(self) -> float:
        """Effective physical output 0..1 (zero if the device failed mechanically)."""
        return 0.0 if self.fault is ActuatorFault.FAILED else self.actual
