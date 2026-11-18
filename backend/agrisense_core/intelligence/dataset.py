"""Generate labelled datasets by running the closed-loop greenhouse (simulator + controller).

Healthy runs train the "virtual sensor" models and the irrigation forecaster. Fault runs inject
random sensor faults on a schedule; every minute records the fault label, so detectors can be
scored exactly. Runs use separate seed ranges for training, calibration and testing.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from agrisense_core.config import load_config
from agrisense_core.intelligence.recorder import MONITORED, observe, to_arrays
from agrisense_core.runtime import GreenhouseRuntime

# Realistic fault sizes per quantity: offset (units), drift (units per hour), spike (units).
MAGNITUDES = {
    "air_temp": {"offset": (1.5, 4.0), "drift": (0.5, 2.0), "spike": (5.0, 10.0)},
    "soil_vwc": {"offset": (3.0, 8.0), "drift": (1.0, 3.0), "spike": (8.0, 15.0)},
    "co2_ppm": {"offset": (80.0, 200.0), "drift": (50.0, 150.0), "spike": (300.0, 600.0)},
}
FAULT_WEIGHTS = {"stuck": 0.22, "spike": 0.22, "drift": 0.22, "offset": 0.22, "dropout": 0.12}


@dataclass(frozen=True)
class RunSpec:
    kind: str  # "healthy" | "fault"
    seed: int
    days: float
    step_s: float = 10.0


@dataclass
class FaultEvent:
    start_min: int
    sensor: str
    quantity: str
    fault: str
    magnitude: float
    duration_h: float


def fault_schedule(seed: int, days: float, zones: list[str]) -> list[FaultEvent]:
    """Random, non-overlapping-per-sensor faults, roughly one starting every 4 hours."""
    rng = np.random.default_rng(seed + 7919)
    events: list[FaultEvent] = []
    busy_until: dict[str, int] = {}
    t = 180  # leave 3 h of clean warm-up
    total = int(days * 1440)
    names, weights = zip(*FAULT_WEIGHTS.items(), strict=True)
    while True:
        t += int(rng.uniform(150, 330))
        if t > total - 120:
            break
        z = zones[rng.integers(len(zones))]
        suffix, q = MONITORED[rng.integers(len(MONITORED))]
        sensor = f"{z}.{suffix}"
        if busy_until.get(sensor, 0) > t:
            continue
        fault = str(rng.choice(names, p=np.array(weights) / sum(weights)))
        lo, hi = MAGNITUDES[q].get(fault, (0.0, 0.0))
        mag = float(rng.uniform(lo, hi)) * (1 if fault == "spike" or rng.random() < 0.5 else -1)
        dur = float(rng.uniform(1.5, 5.0))
        events.append(FaultEvent(t, sensor, q, fault, mag, dur))
        busy_until[sensor] = t + int(dur * 60) + 60
    return events


def simulate_run(spec: RunSpec, config_dir: str | None = None) -> dict[str, np.ndarray]:
    config = load_config(config_dir)
    rt = GreenhouseRuntime(config, seed=spec.seed, step_s=spec.step_s)
    zones = [z.id for z in config.greenhouse.zones]
    schedule = fault_schedule(spec.seed, spec.days, zones) if spec.kind == "fault" else []
    rows = []
    for minute in range(int(spec.days * 1440)):
        for ev in schedule:
            if ev.start_min == minute:
                rt.engine.scenarios.start(
                    "sensor_failure",
                    duration_h=ev.duration_h,
                    sensor=ev.sensor,
                    fault=ev.fault,
                    magnitude=ev.magnitude,
                )
        rt.run_for(60)
        rows.append(observe(rt))
    arrays = to_arrays(rows)
    arrays["meta:seed"] = np.array([spec.seed])
    return arrays


def _path(cache: Path, spec: RunSpec) -> Path:
    return cache / f"{spec.kind}_{spec.seed}_{spec.days:g}d_{spec.step_s:g}s.npz"


def _run_and_save(args: tuple[RunSpec, str, str | None]) -> str:
    spec, cache, config_dir = args
    path = _path(Path(cache), spec)
    if not path.exists():
        arrays = simulate_run(spec, config_dir)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **{k.replace("/", "|"): v for k, v in arrays.items()})
        tmp.replace(path)
    return str(path)


def load_runs(
    specs: list[RunSpec],
    cache_dir: str | Path,
    workers: int = 4,
    config_dir: str | None = None,
    progress=print,
) -> list[dict[str, np.ndarray]]:
    """Simulate (in parallel) any runs not cached yet, then load them all."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    todo = [s for s in specs if not _path(cache, s).exists()]
    if todo:
        sim_days = sum(s.days for s in todo)
        progress(
            f"  simulating {len(todo)} runs ({sim_days:g} greenhouse-days) on {workers} workers..."
        )
        args = [(s, str(cache), config_dir) for s in todo]
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_run_and_save, args))
        else:
            for a in args:
                _run_and_save(a)
    runs = []
    for s in specs:
        with np.load(_path(cache, s)) as f:
            runs.append({k.replace("|", "/"): f[k] for k in f.files})
    return runs
