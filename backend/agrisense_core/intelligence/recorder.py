"""Per-minute observation recorder shared by offline dataset generation and the live API.

An observation contains only what a real controller could know: sensor readings as received
(None when missing or unusable), its own actuator levels and its own estimates. Ground truth and
fault labels are recorded in separate `truth:` / `label:` keys used only for training and
evaluation, never as model inputs.
"""

from __future__ import annotations

import math

import numpy as np

from agrisense_core.runtime import GreenhouseRuntime

FAULT_CODES = {None: 0, "stuck": 1, "dropout": 2, "spike": 3, "drift": 4, "offset": 5}
FAULT_NAMES = {v: k for k, v in FAULT_CODES.items() if k}
NAN = float("nan")

# Channels the anomaly detector monitors in every zone: (sensor suffix, quantity).
MONITORED = [("air", "air_temp"), ("soil1", "soil_vwc"), ("soil2", "soil_vwc"), ("co2", "co2_ppm")]


def channel_key(sensor_id: str, quantity: str) -> str:
    return f"{sensor_id}/{quantity}"


def _v(x: float | None) -> float:
    return NAN if x is None else float(x)


def observe(rt: GreenhouseRuntime) -> dict[str, float]:
    """One flat observation of the greenhouse as the controller sees it, plus truth and labels."""
    e, ctl = rt.engine, rt.controller
    now = e.now
    hour = now.hour + now.minute / 60
    obs: dict[str, float] = {
        "t": now.timestamp() / 60,  # minutes
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
    }
    for (sid, q), r in e.latest.items():
        obs[channel_key(sid, q)] = _v(r.value) if str(r.quality) in ("ok", "saturated") else NAN

    for zid, zm in e.zones.items():
        for kind in ("fan", "valve", "light", "mister"):
            a = e.actuators.get(f"{zid}.{kind}")
            obs[f"{zid}.{kind}"] = a.actual if a else 0.0
        if ctl:
            zc = ctl.zones[zid]
            obs[f"{zid}.vwc_measured"] = _v(zc.measured.get("vwc_pct"))
            obs[f"{zid}.dli_estimate"] = zc.dli_estimate
            obs[f"{zid}.irrigating"] = 1.0 if zc.irrigation in ("watering", "fallback") else 0.0
        s = zm.state
        obs[f"truth:{zid}.temp"] = s.temp_c
        obs[f"truth:{zid}.vwc_pct"] = s.vwc * 100
        obs[f"truth:{zid}.co2"] = s.co2_ppm
        obs[f"truth:{zid}.ks"] = s.water_stress_ks

    for zid in e.zones:
        for suffix, q in MONITORED:
            sid = f"{zid}.{suffix}"
            sensor = e.sensors.get(sid)
            fault = str(sensor.fault) if sensor and sensor.fault else None
            obs[f"label:{channel_key(sid, q)}"] = float(FAULT_CODES[fault])
            if ctl:
                ch = ctl.health.channel(sid, q)
                flagged = (
                    ch is not None
                    and not ch.usable
                    and str(ch.health) not in ("no_data", "warming_up")
                )
                if q == "soil_vwc" and ctl.alerts.is_active("SENSOR_DISAGREE", zid):
                    flagged = True
                obs[f"rule:{channel_key(sid, q)}"] = 1.0 if flagged else 0.0
    obs["energy_wh"] = sum(a.energy_wh for a in e.actuators.values())
    return obs


def to_arrays(rows: list[dict[str, float]]) -> dict[str, np.ndarray]:
    """List of observations to column arrays (missing keys become NaN)."""
    keys = sorted({k for r in rows for k in r})
    return {k: np.array([r.get(k, NAN) for r in rows], dtype=float) for k in keys}
