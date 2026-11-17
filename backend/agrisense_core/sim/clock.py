"""Simulated clock with a speed multiplier and fixed physics sub-steps."""

from __future__ import annotations

from datetime import datetime, timedelta


class SimClock:
    """Keeps simulated time separate from wall-clock time.

    `advance_real(real_seconds)` converts elapsed wall time into a whole number of fixed
    physics steps, carrying any remainder so long runs never drift.
    """

    def __init__(self, start: datetime, step_s: float = 1.0, speed: float = 1.0) -> None:
        if step_s <= 0:
            raise ValueError("step_s must be positive")
        self.start = start
        self.step_s = step_s
        self.speed = speed
        self.elapsed_s = 0.0
        self._carry_s = 0.0

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        if value <= 0:
            raise ValueError("speed must be positive")
        self._speed = value

    @property
    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed_s)

    @property
    def hour_of_day(self) -> float:
        n = self.now
        return n.hour + n.minute / 60 + (n.second + n.microsecond / 1e6) / 3600

    @property
    def day_of_year(self) -> int:
        return self.now.timetuple().tm_yday

    def steps_for_real(self, real_seconds: float) -> int:
        """How many physics steps cover `real_seconds` of wall time at the current speed."""
        self._carry_s += real_seconds * self.speed
        n = int(self._carry_s // self.step_s)
        self._carry_s -= n * self.step_s
        return n

    def tick(self) -> None:
        self.elapsed_s += self.step_s
