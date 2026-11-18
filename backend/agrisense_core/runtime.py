"""Closed-loop runtime: the simulated greenhouse plus the automation controller.

The two parts only talk through the message bus (sensor readings in, actuator commands out),
so the same controller can later drive real hardware over MQTT.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from agrisense_core.config import AgriSenseConfig, load_config
from agrisense_core.control.controller import GreenhouseController
from agrisense_core.sim.engine import GreenhouseEngine


class GreenhouseRuntime:
    def __init__(
        self,
        config: AgriSenseConfig | None = None,
        seed: int | None = None,
        speed: float = 1.0,
        step_s: float | None = None,
        control: bool = True,
    ) -> None:
        self.config = config or load_config()
        self.engine = GreenhouseEngine(self.config, seed=seed, speed=speed, step_s=step_s)
        self.controller = (
            GreenhouseController(self.config, bus=self.engine.bus) if control else None
        )
        self._interval = timedelta(seconds=self.config.control.interval_s)
        self._next_tick = self.engine.now

    @property
    def now(self):
        return self.engine.now

    def step(self) -> None:
        self.engine.step()
        if self.controller is not None and self.engine.now >= self._next_tick:
            self.controller.tick(self.engine.now)
            self._next_tick = self.engine.now + self._interval

    def run_for(
        self, sim_seconds: float, callback: Callable[[GreenhouseRuntime], None] | None = None
    ) -> None:
        for _ in range(int(round(sim_seconds / self.engine.clock.step_s))):
            self.step()
            if callback:
                callback(self)

    def advance_real(self, real_seconds: float) -> None:
        for _ in range(self.engine.clock.steps_for_real(real_seconds)):
            self.step()

    def snapshot(self) -> dict[str, Any]:
        snap = self.engine.snapshot()
        snap["control"] = self.controller.status() if self.controller else None
        return snap
