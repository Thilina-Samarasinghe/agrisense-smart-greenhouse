"""Operating modes and manual overrides per actuator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Mode(StrEnum):
    AUTO = "auto"  # automation rules decide
    MANUAL = "manual"  # operator level holds until changed (or until the override expires)
    OFF = "off"  # forced off; only safety interlocks may still switch it on


@dataclass
class ActuatorMode:
    mode: Mode = Mode.AUTO
    manual_level: float = 0.0
    expires_at: datetime | None = None  # timed override returns to AUTO at this time
    set_by: str = "system"

    def expire(self, now: datetime) -> bool:
        """Return to AUTO when a timed override runs out. Returns True if it expired."""
        if self.expires_at is not None and now >= self.expires_at:
            self.mode = Mode.AUTO
            self.expires_at = None
            self.manual_level = 0.0
            return True
        return False
