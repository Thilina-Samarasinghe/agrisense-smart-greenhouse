"""Predictive irrigation: hours until each zone's next irrigation starts.

Baseline: straight-line extrapolation of the last 3 h soil moisture trend to the start threshold.
Model: gradient-boosted regression on soil moisture, its trends, time of day, climate and light.
Soil drying is strongly non-linear over a day (fast at midday, near zero at night), which is
exactly what a straight line misses.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from agrisense_core.config import AgriSenseConfig
from agrisense_core.intelligence.features import (
    forecast_frame,
    hours_to_next_irrigation,
    linear_baseline,
)

WARMUP_MIN = 240
CAP_H = 48.0
BUCKETS = [(0, 6), (6, 24), (24, 48)]


def _zone_info(config: AgriSenseConfig) -> list[tuple[str, str, float]]:
    return [
        (z.id, z.crop, config.crops[z.crop].targets.vwc[0] * 100) for z in config.greenhouse.zones
    ]


def build(runs: list[dict], config: AgriSenseConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs, ys, zs = [], [], []
    for r in runs:
        for zid, crop, start in _zone_info(config):
            f = forecast_frame(r, zid, crop, start)
            y = hours_to_next_irrigation(f["irrigating"], CAP_H)
            keep = ~np.isnan(y) & ~np.isnan(f["x"][:, 0])
            keep[:WARMUP_MIN] = False
            xs.append(f["x"][keep])
            ys.append(y[keep])
            zs.extend([zid] * int(keep.sum()))
    return np.vstack(xs), np.concatenate(ys), np.array(zs)


class IrrigationForecaster:
    def __init__(self, seed: int = 0) -> None:
        self.model = HistGradientBoostingRegressor(
            loss="absolute_error", max_iter=400, learning_rate=0.06, random_state=seed
        )

    def fit(self, runs: list[dict], config: AgriSenseConfig) -> IrrigationForecaster:
        x, y, _ = build(runs, config)
        self.model.fit(x, y)
        self.n_train = len(y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.clip(self.model.predict(x), 0, CAP_H)

    def evaluate(self, runs: list[dict], config: AgriSenseConfig) -> dict[str, Any]:
        x, y, _ = build(runs, config)
        pred, base = self.predict(x), linear_baseline(x, CAP_H)
        known = y < CAP_H  # an irrigation actually happened within the horizon
        out: dict[str, Any] = {"test_minutes": int(known.sum()), "buckets": {}}
        for name, p in (("model", pred), ("baseline", base)):
            out[f"{name}_mae_h"] = round(float(np.mean(np.abs(p[known] - y[known]))), 2)
        for lo, hi in BUCKETS:
            m = known & (y >= lo) & (y < hi)
            if m.any():
                out["buckets"][f"{lo}-{hi} h"] = {
                    "minutes": int(m.sum()),
                    "model_mae_h": round(float(np.mean(np.abs(pred[m] - y[m]))), 2),
                    "baseline_mae_h": round(float(np.mean(np.abs(base[m] - y[m]))), 2),
                }
        # Practical question: is the next irrigation correctly predicted within 6 hours?
        soon = y < 6
        for name, p in (("model", pred), ("baseline", base)):
            said_soon = p < 6
            tp = int((said_soon & soon).sum())
            out[f"{name}_within_6h_precision"] = round(tp / max(int(said_soon.sum()), 1), 3)
            out[f"{name}_within_6h_recall"] = round(tp / max(int(soon.sum()), 1), 3)
        return out
