"""Live scoring for the API: keeps a rolling history of observations and applies the trained
models to the latest minute with exactly the training-time feature code."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from agrisense_core.config import AgriSenseConfig
from agrisense_core.intelligence.features import (
    channel_frames,
    forecast_frame,
    linear_baseline,
)
from agrisense_core.intelligence.pipeline import DEFAULT_ML_DIR, load_models
from agrisense_core.intelligence.recorder import observe, to_arrays
from agrisense_core.runtime import GreenhouseRuntime

HISTORY_MIN = 26 * 60  # enough for the 24 h residual baseline plus warm-up


def _f(x: float) -> float | None:
    return None if x is None or np.isnan(x) else round(float(x), 3)


class LiveIntelligence:
    def __init__(self, config: AgriSenseConfig, ml_dir: Path = DEFAULT_ML_DIR) -> None:
        self.config = config
        self.ml_dir = Path(ml_dir)
        self.history: deque[dict[str, float]] = deque(maxlen=HISTORY_MIN)
        self.bundle = load_models(self.ml_dir)
        self.zones = [z.id for z in config.greenhouse.zones]

    @property
    def available(self) -> bool:
        return self.bundle is not None

    def reload(self) -> bool:
        self.bundle = load_models(self.ml_dir)
        return self.available

    def reset(self) -> None:
        self.history.clear()

    def record(self, rt: GreenhouseRuntime) -> None:
        self.history.append(observe(rt))

    def status(self) -> dict[str, Any]:
        return {
            "models_loaded": self.available,
            "trained_at": self.bundle["meta"]["trained_at"] if self.bundle else None,
            "history_minutes": len(self.history),
            "how_to_train": None if self.available else "cd backend && agrisense ml all",
        }

    def anomalies(self) -> list[dict[str, Any]]:
        if not self.available or len(self.history) < 30:
            return []
        det = self.bundle["anomaly"]
        arrays = to_arrays(list(self.history))
        out = []
        frames = channel_frames(arrays, self.zones)
        for f, s in zip(frames, det.score_run(frames), strict=True):
            out.append(
                {
                    "channel": f["channel"],
                    "zone_id": f["zone"],
                    "quantity": f["quantity"],
                    "value": _f(f["value"][-1]),
                    "residual": _f(s["residual"][-1]),
                    "virtual_score": _f(s["virtual_score"][-1]),
                    "supervised_probability": _f(s["supervised_proba"][-1]),
                    "rule_flag": bool(s["rules"][-1]),
                    "flagged": bool(s["virtual"][-1] or s["supervised"][-1]),
                    "warming_up": len(self.history) < 180,
                }
            )
        return out

    def forecast(self) -> list[dict[str, Any]]:
        if not self.available or len(self.history) < 30:
            return []
        model = self.bundle["forecaster"]
        arrays = to_arrays(list(self.history))
        out = []
        for z in self.config.greenhouse.zones:
            start = self.config.crops[z.crop].targets.vwc[0] * 100
            f = forecast_frame(arrays, z.id, z.crop, start)
            x = f["x"][-1:]
            irrigating = bool(f["irrigating"][-1] > 0)
            out.append(
                {
                    "zone_id": z.id,
                    "irrigating_now": irrigating,
                    "hours_model": None
                    if irrigating or np.isnan(x[0, 0])
                    else round(float(model.predict(x)[0]), 1),
                    "hours_straight_line": None
                    if irrigating or np.isnan(x[0, 0])
                    else round(float(linear_baseline(x)[0]), 1),
                    "vwc_pct": _f(x[0, 0]),
                    "start_pct": round(start, 1),
                }
            )
        return out
