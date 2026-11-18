"""Vectorised feature engineering over per-minute observation arrays.

The same functions build training data offline and score the latest minute online, so the live
models see exactly the features they were trained on.
"""

from __future__ import annotations

import warnings

import numpy as np

from agrisense_core.intelligence.recorder import MONITORED, channel_key

QUANTITIES = ["air_temp", "soil_vwc", "co2_ppm"]


# ------------------------------------------------------------------ NaN-aware rolling helpers


def rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Trailing mean over the last `w` samples, ignoring NaN (NaN if the window is empty)."""
    valid = ~np.isnan(x)
    cs = np.concatenate([[0.0], np.cumsum(np.where(valid, x, 0.0))])
    cn = np.concatenate([[0], np.cumsum(valid)])
    idx = np.arange(1, len(x) + 1)
    lo = np.maximum(idx - w, 0)
    n = cn[idx] - cn[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, (cs[idx] - cs[lo]) / np.maximum(n, 1), np.nan)


def rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    m = rolling_mean(x, w)
    m2 = rolling_mean(x * x, w)
    return np.sqrt(np.maximum(m2 - m * m, 0.0))


def lag(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    if k < len(x):
        out[k:] = x[:-k] if k > 0 else x
    return out


def minutes_since_change(x: np.ndarray, cap: int = 240) -> np.ndarray:
    out = np.zeros(len(x))
    run = 0
    for i in range(1, len(x)):
        same = x[i] == x[i - 1] or (np.isnan(x[i]) and np.isnan(x[i - 1]))
        run = run + 1 if same else 0
        out[i] = min(run, cap)
    return out


def _col(a: dict[str, np.ndarray], key: str, n: int) -> np.ndarray:
    return a.get(key, np.full(n, np.nan))


# ------------------------------------------------------------------ anomaly features

CONTEXT = [
    "out_temp",
    "out_rh",
    "lux",
    "fan",
    "mister",
    "valve",
    "light",
    "hour_sin",
    "hour_cos",
    "peer",
    "sibling",
    "rh_same_device",
]
WINDOW = [
    "value",
    "d1",
    "std30",
    "dev_mean120",
    "slope60",
    "since_change",
    "minus_peer",
    "minus_sibling",
]
RESIDUAL = ["resid", "resid_mean30", "resid_mean120", "resid_vs_day"]


def channel_frames(a: dict[str, np.ndarray], zones: list[str]) -> list[dict]:
    """For every monitored channel: target values, context matrix, window-feature matrix, labels."""
    n = len(a["t"])
    out = []
    for z in zones:
        for suffix, q in MONITORED:
            key = channel_key(f"{z}.{suffix}", q)
            v = _col(a, key, n)
            peers = [_col(a, channel_key(f"{o}.{suffix}", q), n) for o in zones if o != z]
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # all peers missing -> NaN is fine
                peer = np.nanmean(np.vstack(peers), axis=0) if peers else np.full(n, np.nan)
            if q == "soil_vwc":
                other = "soil2" if suffix == "soil1" else "soil1"
                sibling = _col(a, channel_key(f"{z}.{other}", q), n)
            else:
                sibling = np.zeros(n)  # not applicable: constant, so models simply ignore it
            # RH comes from the same SHT31 package: useful context, but it shares the fault, so it
            # is only used for the CO2 and soil models, never for air temperature.
            rh_same = (
                _col(a, channel_key(f"{z}.air", "air_rh"), n) if q != "air_temp" else np.zeros(n)
            )
            ctx = np.column_stack(
                [
                    _col(a, "outside/air_temp", n),
                    _col(a, "outside/air_rh", n),
                    _col(a, channel_key(f"{z}.light", "light_lux"), n) / 1000,
                    _col(a, f"{z}.fan", n),
                    _col(a, f"{z}.mister", n),
                    _col(a, f"{z}.valve", n),
                    _col(a, f"{z}.light", n),
                    a["hour_sin"],
                    a["hour_cos"],
                    peer,
                    sibling,
                    rh_same,
                ]
            )
            win = np.column_stack(
                [
                    v,
                    v - lag(v, 1),
                    rolling_std(v, 30),
                    v - rolling_mean(v, 120),
                    (v - lag(v, 60)) / 60,
                    minutes_since_change(v),
                    v - peer,
                    v - sibling if q == "soil_vwc" else np.zeros(n),
                ]
            )
            out.append(
                {
                    "zone": z,
                    "channel": key,
                    "quantity": q,
                    "value": v,
                    "ctx": ctx,
                    "win": win,
                    "label": _col(a, f"label:{key}", n),
                    "rule": _col(a, f"rule:{key}", n),
                    "t": a["t"],
                }
            )
    return out


def residual_features(v: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Residual of the virtual sensor, smoothed, and relative to its own recent baseline.

    Comparing with the residual's own 24 h mean removes each probe's installation bias, so a new
    offset or drift stands out even though every greenhouse's probes differ slightly.
    """
    r = v - pred
    base = lag(rolling_mean(r, 24 * 60), 120)  # baseline excludes the last 2 h
    base = np.where(np.isnan(base), 0.0, base)
    return np.column_stack(
        [r, rolling_mean(r, 30), rolling_mean(r, 120), rolling_mean(r, 30) - base]
    )


# ------------------------------------------------------------------ irrigation forecast features

FORECAST = [
    "vwc",
    "gap_to_start",
    "slope60",
    "slope180",
    "hour_sin",
    "hour_cos",
    "temp",
    "rh",
    "lux",
    "dli_est",
    "out_temp",
    "crop_tomato",
    "crop_chilli",
    "crop_lettuce",
    "straight_line_h",
]


def forecast_frame(a: dict[str, np.ndarray], zone: str, crop: str, start_pct: float) -> dict:
    n = len(a["t"])
    vwc = _col(a, f"{zone}.vwc_measured", n)
    smooth = rolling_mean(vwc, 15)  # probe noise would dominate short slopes
    x = np.column_stack(
        [
            vwc,
            vwc - start_pct,
            (smooth - lag(smooth, 60)) / 60 * 60,  # %/h
            (smooth - lag(smooth, 180)) / 180 * 60,
            a["hour_sin"],
            a["hour_cos"],
            _col(a, channel_key(f"{zone}.air", "air_temp"), n),
            _col(a, channel_key(f"{zone}.air", "air_rh"), n),
            _col(a, channel_key(f"{zone}.light", "light_lux"), n) / 1000,
            _col(a, f"{zone}.dli_estimate", n),
            _col(a, "outside/air_temp", n),
            np.full(n, crop == "tomato", dtype=float),
            np.full(n, crop == "chilli", dtype=float),
            np.full(n, crop == "lettuce", dtype=float),
        ]
    )
    # The physics-like straight-line estimate is itself a feature: the model learns corrections
    # to it (e.g. slower drying overnight) instead of rediscovering it from few events.
    x = np.column_stack([x, linear_baseline(x)])
    return {"x": x, "irrigating": _col(a, f"{zone}.irrigating", n), "t": a["t"]}


def hours_to_next_irrigation(irrigating: np.ndarray, cap_h: float = 48.0) -> np.ndarray:
    """Target: hours from each minute until the next irrigation start (NaN when unknown).

    Minutes after the last start in the run are censored unless the cap is already exceeded.
    """
    n = len(irrigating)
    starts = np.where((irrigating[1:] > 0) & (irrigating[:-1] == 0))[0] + 1
    y = np.full(n, np.nan)
    j = 0
    for i in range(n):
        while j < len(starts) and starts[j] <= i:
            j += 1
        if j < len(starts):
            y[i] = min((starts[j] - i) / 60, cap_h)
        elif (n - i) / 60 >= cap_h:
            y[i] = cap_h
    y[irrigating > 0] = np.nan  # only forecast while idle
    return y


def linear_baseline(x: np.ndarray, cap_h: float = 48.0) -> np.ndarray:
    """Straight-line extrapolation of the 3 h soil moisture trend to the start threshold."""
    gap, slope = x[:, FORECAST.index("gap_to_start")], x[:, FORECAST.index("slope180")]
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(slope < -1e-3, gap / -slope, cap_h)
    return np.clip(np.nan_to_num(h, nan=cap_h), 0, cap_h)
