"""Simulation-based tuning of controller setpoints (the digital twin as a test bench).

Each candidate set of climate-control parameters is run in closed loop on several simulated days.
We look for settings that use **less energy without worse crop conditions** than the defaults
(measured as hours outside the crop's temperature and humidity targets). The chosen setting is
then checked on held-out seeds it was never tuned on.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from agrisense_core.config import AgriSenseConfig, hhmm_to_hours, load_config
from agrisense_core.runtime import GreenhouseRuntime

# Parameter search space: (section, key) -> (low, high)
SPACE: dict[tuple[str, str], tuple[float, float]] = {
    ("climate", "stage1_level"): (0.3, 0.8),
    ("climate", "stage2_offset_c"): (1.0, 4.0),
    ("climate", "temp_band_c"): (0.8, 3.0),
    ("climate", "vent_benefit_on_c"): (0.5, 2.5),
    ("climate", "vent_benefit_off_night_c"): (0.1, 1.0),
    ("climate", "mist_cooling_offset_c"): (0.5, 3.5),
    ("climate", "humidity_band_pct"): (3.0, 10.0),
}


def apply(config: AgriSenseConfig, params: dict[str, float]) -> AgriSenseConfig:
    ctl = config.control.model_dump()
    for name, value in params.items():
        section, key = name.split(".")
        ctl[section][key] = value
    return AgriSenseConfig(
        greenhouse=config.greenhouse, crops=config.crops, sensors=config.sensors, control=ctl
    )


def default_params(config: AgriSenseConfig) -> dict[str, float]:
    ctl = config.control.model_dump()
    return {f"{s}.{k}": float(ctl[s][k]) for s, k in SPACE}


def evaluate(
    params: dict[str, float],
    seed: int,
    days: float,
    step_s: float = 10.0,
    config_dir: str | None = None,
) -> dict[str, float]:
    """Run one closed-loop simulation and measure energy, water and time outside targets."""
    config = apply(load_config(config_dir), params)
    rt = GreenhouseRuntime(config, seed=seed, step_s=step_s)
    day_window = tuple(map(hhmm_to_hours, config.control.day_window))
    viol_temp = viol_rh = 0.0
    for _ in range(int(days * 1440)):
        rt.run_for(60)
        now = rt.now
        hour = now.hour + now.minute / 60
        day = day_window[0] <= hour < day_window[1]
        for z in config.greenhouse.zones:
            s = rt.engine.zones[z.id].state
            t = config.crops[z.crop].targets
            lo, hi = t.temp_day_c if day else t.temp_night_c
            viol_temp += (not lo <= s.temp_c <= hi) / 60
            viol_rh += (not t.rh_pct[0] <= s.rh_pct <= t.rh_pct[1]) / 60
    e = rt.engine
    return {
        "energy_kwh": sum(a.energy_wh for a in e.actuators.values()) / 1000,
        "temp_violation_h": viol_temp,
        "rh_violation_h": viol_rh,
        "water_l": sum(
            z.state.totals["irrigation_l"] + z.state.totals["mist_l"] for z in e.zones.values()
        ),
    }


def _eval_job(args: tuple) -> dict[str, float]:
    return evaluate(*args)


def _mean(results: list[dict[str, float]]) -> dict[str, float]:
    return {k: float(np.mean([r[k] for r in results])) for k in results[0]}


def search(
    config: AgriSenseConfig,
    n_candidates: int,
    seeds: list[int],
    days: float,
    workers: int,
    rng_seed: int = 0,
    config_dir: str | None = None,
    progress=print,
) -> dict[str, Any]:
    rng = np.random.default_rng(rng_seed)
    base = default_params(config)
    candidates = [base]
    for _ in range(n_candidates):
        candidates.append(
            {f"{s}.{k}": round(float(rng.uniform(lo, hi)), 2) for (s, k), (lo, hi) in SPACE.items()}
        )
    jobs = [(c, seed, days, 10.0, config_dir) for c in candidates for seed in seeds]
    progress(
        f"  evaluating {len(candidates)} settings x {len(seeds)} seeds x {days:g} days "
        f"({len(jobs) * days:g} greenhouse-days) on {workers} workers..."
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        flat = list(pool.map(_eval_job, jobs))
    results = []
    for i, c in enumerate(candidates):
        m = _mean(flat[i * len(seeds) : (i + 1) * len(seeds)])
        m["violation_h"] = m["temp_violation_h"] + m["rh_violation_h"]
        results.append({"params": c, **m})
    default = results[0]
    # Best = lowest energy among settings whose crop conditions are no worse than the default.
    # The defaults stay in the running: if nothing beats them, they are the answer.
    ok = [r for r in results if r["violation_h"] <= default["violation_h"]]
    best = min(ok, key=lambda r: r["energy_kwh"])
    pareto = sorted(
        (
            r
            for r in results
            if not any(
                o["energy_kwh"] < r["energy_kwh"] and o["violation_h"] < r["violation_h"]
                for o in results
            )
        ),
        key=lambda r: r["energy_kwh"],
    )
    return {"default": default, "best": best, "pareto": pareto, "all": results}


def validate(
    config: AgriSenseConfig,
    params: dict[str, float],
    seeds: list[int],
    days: float,
    workers: int,
    config_dir: str | None = None,
) -> dict[str, Any]:
    base = default_params(config)
    jobs = [(p, s, days, 10.0, config_dir) for p in (base, params) for s in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        flat = list(pool.map(_eval_job, jobs))
    d, t = _mean(flat[: len(seeds)]), _mean(flat[len(seeds) :])
    for m in (d, t):
        m["violation_h"] = m["temp_violation_h"] + m["rh_violation_h"]
    change = {k: round((t[k] - d[k]) / d[k] * 100, 1) if d[k] else 0.0 for k in d}
    per_seed = [
        {"seed": s, "default": flat[i], "tuned": flat[len(seeds) + i]} for i, s in enumerate(seeds)
    ]
    return {
        "default": d,
        "tuned": t,
        "change_pct": change,
        "seeds": seeds,
        "days": days,
        "per_seed": per_seed,
    }
