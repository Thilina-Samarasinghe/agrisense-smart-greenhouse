"""Sensor anomaly detection: four detectors trained and scored on simulated, labelled faults.

Detectors
---------
rules       Phase 2 health monitor (stale / range / spikes / stuck / probe disagreement)
isolation   IsolationForest on window + residual features, trained on healthy data only
virtual     "Virtual sensor" (analytical redundancy): a model trained on healthy data predicts
            each sensor from its peers in other zones, the outside sensor, light and equipment
            state. A persistent residual against the sensor's own recent baseline means the
            sensor (not the greenhouse) changed. Unsupervised: needs no fault examples.
supervised  Gradient-boosted classifier on all features, trained on labelled fault runs.
            Strongest on the simulator's fault types, but it has only seen simulated faults.

Dropout is excluded from the ML comparison: a missing value is trivially detected by the rules.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    IsolationForest,
)

from agrisense_core.intelligence.features import (
    QUANTITIES,
    channel_frames,
    residual_features,
    rolling_mean,
)
from agrisense_core.intelligence.recorder import FAULT_NAMES

WARMUP_MIN = 150
DEBOUNCE_MIN, DEBOUNCE_OF = 5, 10  # alarm when flagged in 5 of the last 10 minutes
ISOLATION_RATIO = 0.6  # keep a flag only if close to the most deviant sensor of its kind
EVAL_FAULTS = [1, 3, 4, 5]  # stuck, spike, drift, offset
DROPOUT = 2
METHODS = ["rules", "isolation", "virtual", "supervised"]


def debounce(flag: np.ndarray) -> np.ndarray:
    """k-of-n alarm filter: one-minute blips never alarm, persistent faults still do."""
    return rolling_mean(flag.astype(float), DEBOUNCE_OF) >= DEBOUNCE_MIN / DEBOUNCE_OF - 1e-9


def _frames(runs: list[dict[str, np.ndarray]], zones: list[str]) -> list[list[dict]]:
    return [channel_frames(r, zones) for r in runs]


class AnomalyDetector:
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.regressors: dict[str, HistGradientBoostingRegressor] = {}
        self.thresholds: dict[str, dict[str, float]] = {}
        self.iforest: dict[str, IsolationForest] = {}
        self.classifier: HistGradientBoostingClassifier | None = None
        self.zones: list[str] = []

    # ------------------------------------------------------------------ features

    def _resid(self, f: dict) -> np.ndarray:
        reg = self.regressors[f["quantity"]]
        pred = np.full(len(f["value"]), np.nan)
        ok = ~np.all(np.isnan(f["ctx"]), axis=1)
        pred[ok] = reg.predict(f["ctx"][ok])
        return residual_features(f["value"], pred)

    def _all_features(self, f: dict, resid: np.ndarray) -> np.ndarray:
        q = np.column_stack(
            [np.full(len(f["value"]), f["quantity"] == x, dtype=float) for x in QUANTITIES]
        )
        return np.column_stack([f["ctx"], f["win"], resid, q])

    @staticmethod
    def _iso_features(f: dict, resid: np.ndarray) -> np.ndarray:
        x = np.column_stack([f["win"][:, 1:], resid])  # all but the raw value (scale-free-ish)
        return np.nan_to_num(x, nan=0.0)

    # ------------------------------------------------------------------ training

    def fit(
        self,
        healthy: list[dict],
        calibration: list[dict],
        faulty: list[dict],
        zones: list[str],
        progress=print,
    ) -> AnomalyDetector:
        self.zones = zones
        hf, cf, ff = _frames(healthy, zones), _frames(calibration, zones), _frames(faulty, zones)

        # 1. Virtual sensors: predict each quantity from context, on healthy data.
        for q in QUANTITIES:
            xs, ys = [], []
            for run in hf:
                for f in run:
                    if f["quantity"] != q:
                        continue
                    ok = ~np.isnan(f["value"])
                    ok[:WARMUP_MIN] = False
                    xs.append(f["ctx"][ok])
                    ys.append(f["value"][ok])
            reg = HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.08, random_state=self.seed
            )
            reg.fit(np.vstack(xs), np.concatenate(ys))
            self.regressors[q] = reg
            progress(f"    virtual sensor for {q}: {sum(len(y) for y in ys):,} healthy minutes")

        # 2. Calibrate residual thresholds on separate healthy runs (99.7th percentile).
        for q in QUANTITIES:
            day, inst, since = [], [], []
            for run in cf:
                for f in run:
                    if f["quantity"] != q:
                        continue
                    r = self._resid(f)[WARMUP_MIN:]
                    day.append(np.abs(r[:, 3]))
                    inst.append(np.abs(r[:, 0] - r[:, 2]))
                    since.append(f["win"][WARMUP_MIN:, 5])
            cat = lambda a: np.concatenate(a)[~np.isnan(np.concatenate(a))]  # noqa: E731
            self.thresholds[q] = {
                "resid_vs_day": float(np.percentile(cat(day), 99.7)) * 1.2,
                "resid_inst": float(np.percentile(cat(inst), 99.9)) * 1.5,
                "since_change": float(max(np.max(cat(since)) + 5, 20)),
            }

        # 3. IsolationForest per quantity on healthy runs; threshold calibrated like the residuals.
        for q in QUANTITIES:
            xs = [
                self._iso_features(f, self._resid(f))[WARMUP_MIN:]
                for run in hf
                for f in run
                if f["quantity"] == q
            ]
            iso = IsolationForest(n_estimators=200, random_state=self.seed).fit(np.vstack(xs))
            self.iforest[q] = iso
            cal = [
                -iso.score_samples(self._iso_features(f, self._resid(f))[WARMUP_MIN:])
                for run in cf
                for f in run
                if f["quantity"] == q
            ]
            self.thresholds[q]["isolation"] = float(np.percentile(np.concatenate(cal), 99.7))

        # 4. Supervised classifier on labelled fault runs (dropout excluded).
        xs, ys = [], []
        for run in ff:
            for f in run:
                x = self._all_features(f, self._resid(f))
                lab = f["label"]
                keep = np.arange(len(lab)) >= WARMUP_MIN
                keep &= lab != DROPOUT
                xs.append(x[keep])
                ys.append((lab[keep] > 0).astype(int))
        y = np.concatenate(ys)
        self.classifier = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, class_weight="balanced", random_state=self.seed
        ).fit(np.vstack(xs), y)
        progress(f"    supervised classifier: {len(y):,} minutes, {y.mean():.1%} faulty")
        return self

    # ------------------------------------------------------------------ scoring

    def _raw(self, f: dict) -> dict[str, np.ndarray]:
        """Undebounced scores for one channel (each normalised so that > 1 means anomalous)."""
        q = f["quantity"]
        resid = self._resid(f)
        th = self.thresholds[q]
        r_day = np.abs(np.nan_to_num(resid[:, 3]))
        r_inst = np.abs(np.nan_to_num(resid[:, 0] - resid[:, 2]))
        since = f["win"][:, 5]
        virtual = np.maximum.reduce(
            [r_day / th["resid_vs_day"], r_inst / th["resid_inst"], since / th["since_change"]]
        )
        iso = -self.iforest[q].score_samples(self._iso_features(f, resid)) / th["isolation"]
        proba = self.classifier.predict_proba(self._all_features(f, resid))[:, 1]
        return {"virtual": virtual, "isolation": iso, "proba": proba, "residual": resid[:, 3]}

    def score_run(self, frames: list[dict]) -> list[dict[str, np.ndarray]]:
        """Score all channels of a run together, with fault isolation and debouncing.

        Fault isolation: each virtual sensor uses the other zones' readings as context, so one
        faulty sensor also shifts its peers' residuals. At every minute, within a group of the same
        quantity, a channel only keeps its flag if its score is close to the group's highest
        (>= ISOLATION_RATIO of it): the sensor that deviates most takes the blame, while two
        genuinely faulty sensors with similar scores are both kept.
        """
        raw = [self._raw(f) for f in frames]
        out = [None] * len(frames)
        for q in {f["quantity"] for f in frames}:
            idx = [i for i, f in enumerate(frames) if f["quantity"] == q]
            for key in ("virtual", "isolation"):
                stack = np.vstack([raw[i][key] for i in idx])
                top = stack.max(axis=0)
                for row, i in enumerate(idx):
                    raw[i][f"{key}_isolated"] = (stack[row] > 1.0) & (
                        stack[row] >= ISOLATION_RATIO * top
                    )
        for i, f in enumerate(frames):
            r = raw[i]
            out[i] = {
                "rules": f["rule"] > 0,  # the health monitor already debounces internally
                "isolation": debounce(r["isolation_isolated"]),
                "virtual": debounce(r["virtual_isolated"]),
                "supervised": debounce(r["proba"] > 0.5),
                "virtual_score": r["virtual"],
                "supervised_proba": r["proba"],
                "residual": r["residual"],
            }
        return out

    # ------------------------------------------------------------------ evaluation

    def evaluate(self, runs: list[dict]) -> dict[str, Any]:
        point = {m: {k: 0 for k in ("tp", "fp", "fn", "tn")} for m in METHODS}
        events = {m: {ft: [] for ft in EVAL_FAULTS + [DROPOUT]} for m in METHODS}
        false_alarm_episodes = {m: 0 for m in METHODS}
        healthy_channel_minutes = 0

        for run in _frames(runs, self.zones):
            for f, s in zip(run, self.score_run(run), strict=True):
                lab = f["label"].astype(int)
                valid = np.arange(len(lab)) >= WARMUP_MIN
                healthy = valid & (lab == 0)
                healthy_channel_minutes += int(healthy.sum())
                for m in METHODS:
                    flag = s[m]
                    ev_mask = valid & (lab != DROPOUT)
                    pos = lab > 0
                    point[m]["tp"] += int((flag & pos & ev_mask).sum())
                    point[m]["fp"] += int((flag & ~pos & ev_mask).sum())
                    point[m]["fn"] += int((~flag & pos & ev_mask).sum())
                    point[m]["tn"] += int((~flag & ~pos & ev_mask).sum())
                    # False-alarm episodes: rising edges of the flag during healthy minutes.
                    edges = flag[1:] & ~flag[:-1] & healthy[1:]
                    false_alarm_episodes[m] += int(edges.sum())
                    # Fault events: contiguous segments of one fault type.
                    i = WARMUP_MIN
                    while i < len(lab):
                        if lab[i] > 0:
                            j = i
                            while j < len(lab) and lab[j] == lab[i]:
                                j += 1
                            hit = np.nonzero(flag[i:j])[0]
                            events[m][lab[i]].append(None if len(hit) == 0 else int(hit[0]))
                            i = j
                        else:
                            i += 1

        days = healthy_channel_minutes / 1440
        result: dict[str, Any] = {"channel_days_healthy": round(days, 1), "methods": {}}
        for m in METHODS:
            p = point[m]
            prec = p["tp"] / max(p["tp"] + p["fp"], 1)
            rec = p["tp"] / max(p["tp"] + p["fn"], 1)
            by_type = {}
            for ft, delays in events[m].items():
                found = [d for d in delays if d is not None]
                by_type[FAULT_NAMES[ft]] = {
                    "events": len(delays),
                    "detected": len(found),
                    "recall": round(len(found) / len(delays), 3) if delays else None,
                    "median_delay_min": float(np.median(found)) if found else None,
                }
            eval_events = [d for ft in EVAL_FAULTS for d in events[m][ft]]
            result["methods"][m] = {
                "precision": round(prec, 3),
                "recall": round(rec, 3),
                "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 3),
                "event_recall": round(
                    sum(d is not None for d in eval_events) / max(len(eval_events), 1), 3
                ),
                "false_alarms_per_channel_day": round(false_alarm_episodes[m] / max(days, 1e-9), 3),
                "by_fault": by_type,
            }
        return result
