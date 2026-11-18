"""Alert management: deduplicated, clearable and (for dangerous faults) latched alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    id: int
    code: str
    severity: Severity
    message: str
    zone_id: str | None
    subject: str | None  # sensor or actuator the alert is about
    raised_at: datetime
    latched: bool = False  # needs a manual reset even after the cause is gone
    cleared_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.cleared_at is None

    def to_message(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = str(self.severity)
        d["raised_at"] = self.raised_at.isoformat()
        d["cleared_at"] = self.cleared_at.isoformat() if self.cleared_at else None
        d["active"] = self.active
        return d


Key = tuple[str, str | None]


class AlertManager:
    def __init__(self, on_change: Callable[[Alert], None] | None = None) -> None:
        self.active: dict[Key, Alert] = {}
        self.history: list[Alert] = []
        self._next_id = 1
        self._on_change = on_change

    def raise_(
        self,
        code: str,
        severity: Severity,
        message: str,
        now: datetime,
        zone_id: str | None = None,
        subject: str | None = None,
        latched: bool = False,
    ) -> Alert:
        key = (code, subject or zone_id)
        existing = self.active.get(key)
        if existing:
            return existing
        alert = Alert(self._next_id, code, severity, message, zone_id, subject, now, latched)
        self._next_id += 1
        self.active[key] = alert
        self.history.append(alert)
        if self._on_change:
            self._on_change(alert)
        return alert

    def clear(
        self, code: str, now: datetime, scope: str | None = None, force: bool = False
    ) -> None:
        """Clear an alert whose cause is gone. Latched alerts only clear with force=True."""
        alert = self.active.get((code, scope))
        if alert is None or (alert.latched and not force):
            return
        alert.cleared_at = now
        del self.active[(code, scope)]
        if self._on_change:
            self._on_change(alert)

    def is_active(self, code: str, scope: str | None = None) -> bool:
        return (code, scope) in self.active

    def codes(self) -> set[str]:
        return {a.code for a in self.active.values()}
