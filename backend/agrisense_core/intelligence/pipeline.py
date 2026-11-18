"""End-to-end Phase 4 pipeline: simulate datasets, train, evaluate on held-out seeds, optimise
controller setpoints, and write models plus a results report.

    agrisense ml all            # full run (several minutes on 8 cores)
    agrisense ml all --quick    # small smoke run
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import yaml

from agrisense_core import __version__
from agrisense_core.config import load_config
from agrisense_core.intelligence import optimize
from agrisense_core.intelligence.anomaly import METHODS, AnomalyDetector
from agrisense_core.intelligence.dataset import RunSpec, load_runs
from agrisense_core.intelligence.forecast import IrrigationForecaster

DEFAULT_ML_DIR = Path(__file__).resolve().parents[3] / "ml"
MODEL_FILE = "models/agrisense_models.joblib"


@dataclass(frozen=True)
class Plan:
    healthy_train: list[int]
    calib: list[int]
    healthy_test: list[int]
    fault_train: list[int]
    fault_test: list[int]
    healthy_days: float
    calib_days: float
    fault_days: float
    opt_candidates: int
    opt_seeds: list[int]
    opt_days: float
    val_seeds: list[int]
    val_days: float


FULL = Plan(
    healthy_train=list(range(100, 108)),
    calib=[150, 151],
    healthy_test=list(range(200, 204)),
    fault_train=list(range(300, 308)),
    fault_test=list(range(400, 406)),
    healthy_days=5,
    calib_days=3,
    fault_days=3,
    opt_candidates=30,
    opt_seeds=[500, 501],
    opt_days=2,
    val_seeds=[600, 601, 602],
    val_days=3,
)
QUICK = Plan(
    healthy_train=[100, 101],
    calib=[150],
    healthy_test=[200],
    fault_train=[300, 301],
    fault_test=[400],
    healthy_days=2,
    calib_days=1,
    fault_days=1.5,
    opt_candidates=3,
    opt_seeds=[500],
    opt_days=0.5,
    val_seeds=[600],
    val_days=0.5,
)


def _workers(n: int | None) -> int:
    return n or max(1, (os.cpu_count() or 2) - 1)


def train(
    ml_dir: Path = DEFAULT_ML_DIR,
    quick: bool = False,
    workers: int | None = None,
    config_dir: str | None = None,
    progress=print,
) -> dict[str, Any]:
    plan = QUICK if quick else FULL
    w = _workers(workers)
    config = load_config(config_dir)
    zones = [z.id for z in config.greenhouse.zones]
    cache = ml_dir / "data"
    t0 = time.perf_counter()

    progress("1/4 Simulating datasets")
    specs = (
        [RunSpec("healthy", s, plan.healthy_days) for s in plan.healthy_train + plan.healthy_test]
        + [RunSpec("healthy", s, plan.calib_days) for s in plan.calib]
        + [RunSpec("fault", s, plan.fault_days) for s in plan.fault_train + plan.fault_test]
    )
    runs = dict(
        zip(
            [(s.kind, s.seed) for s in specs],
            load_runs(specs, cache, w, config_dir, progress),
            strict=True,
        )
    )
    pick = lambda kind, seeds: [runs[(kind, s)] for s in seeds]  # noqa: E731

    progress("2/4 Training and evaluating the anomaly detectors")
    detector = AnomalyDetector().fit(
        pick("healthy", plan.healthy_train),
        pick("healthy", plan.calib),
        pick("fault", plan.fault_train),
        zones,
        progress,
    )
    anomaly_eval = detector.evaluate(pick("fault", plan.fault_test))

    progress("3/4 Training and evaluating the irrigation forecaster")
    forecaster = IrrigationForecaster().fit(pick("healthy", plan.healthy_train), config)
    forecast_eval = forecaster.evaluate(pick("healthy", plan.healthy_test), config)

    (ml_dir / "models").mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "anomaly": detector,
            "forecaster": forecaster,
            "meta": {
                "trained_at": datetime.now().isoformat(timespec="seconds"),
                "version": __version__,
                "quick": quick,
            },
        },
        ml_dir / MODEL_FILE,
    )

    return {
        "plan": plan.__dict__,
        "anomaly": anomaly_eval,
        "forecast": forecast_eval,
        "training_seconds": round(time.perf_counter() - t0, 1),
    }


def tune(
    ml_dir: Path = DEFAULT_ML_DIR,
    quick: bool = False,
    workers: int | None = None,
    config_dir: str | None = None,
    progress=print,
) -> dict[str, Any]:
    plan = QUICK if quick else FULL
    w = _workers(workers)
    config = load_config(config_dir)
    progress("4/4 Optimising controller setpoints in simulation")
    found = optimize.search(
        config,
        plan.opt_candidates,
        plan.opt_seeds,
        plan.opt_days,
        w,
        config_dir=config_dir,
        progress=progress,
    )
    progress(f"  validating the chosen setting on held-out seeds {plan.val_seeds}...")
    val = optimize.validate(
        config, found["best"]["params"], plan.val_seeds, plan.val_days, w, config_dir
    )
    reports = ml_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    tuned = {"climate": {k.split(".")[1]: v for k, v in found["best"]["params"].items()}}
    with (reports / "optimized_control.yaml").open("w", encoding="utf-8") as fh:
        fh.write(
            "# Controller setpoints found by simulation-based optimisation (agrisense ml optimize).\n"
            "# Merge the `climate` values into backend/agrisense_core/profiles/control.yaml to use them.\n"
        )
        yaml.safe_dump(tuned, fh, sort_keys=True)
    return {
        "search": {k: found[k] for k in ("default", "best", "pareto")},
        "validation": val,
        "candidates": len(found["all"]),
    }


# ------------------------------------------------------------------ reporting


def write_report(ml_dir: Path, results: dict[str, Any]) -> Path:
    reports = ml_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase4_results.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    md = reports / "phase4_results.md"
    md.write_text(render_markdown(results), encoding="utf-8")
    return md


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f} %"


def render_markdown(r: dict[str, Any]) -> str:
    lines = [
        "# AgriSense Phase 4 results",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M}. All numbers are measured on simulation seeds "
        "that were never used for training or tuning.",
        "",
    ]
    if "anomaly" in r:
        a = r["anomaly"]
        lines += [
            "## Sensor anomaly detection",
            "",
            f"Test set: {a['channel_days_healthy']} healthy channel-days plus injected faults. "
            "ML alarms are debounced: a sensor must be flagged in 5 of the last 10 minutes.",
            "",
            "| Detector | Precision | Recall | F1 | Faults detected | False alarms per channel-day |",
            "|---|---|---|---|---|---|",
        ]
        for m in METHODS:
            s = a["methods"][m]
            lines.append(
                f"| {m} | {_pct(s['precision'])} | {_pct(s['recall'])} | {s['f1']:.2f} | "
                f"{_pct(s['event_recall'])} | {s['false_alarms_per_channel_day']:.2f} |"
            )
        lines += [
            "",
            "Faults detected (share of fault events flagged at least once) and median delay:",
            "",
            "| Fault | " + " | ".join(METHODS) + " |",
            "|---|" + "---|" * len(METHODS),
        ]
        for ft in ("stuck", "spike", "drift", "offset", "dropout"):
            cells = []
            for m in METHODS:
                b = a["methods"][m]["by_fault"][ft]
                if not b["events"]:
                    cells.append("n/a")
                    continue
                delay = (
                    f", {b['median_delay_min']:.0f} min"
                    if b["median_delay_min"] is not None
                    else ""
                )
                cells.append(f"{b['detected']}/{b['events']}{delay}")
            lines.append(f"| {ft} | " + " | ".join(cells) + " |")
        lines.append("")
    if "forecast" in r:
        f = r["forecast"]
        lines += [
            "## Predictive irrigation",
            "",
            f"Hours until the next irrigation starts, {f['test_minutes']:,} test minutes.",
            "",
            "| Horizon | Minutes | Model MAE (h) | Straight-line MAE (h) |",
            "|---|---|---|---|",
            f"| all | {f['test_minutes']:,} | {f['model_mae_h']} | {f['baseline_mae_h']} |",
        ]
        for k, b in f["buckets"].items():
            lines.append(f"| {k} | {b['minutes']:,} | {b['model_mae_h']} | {b['baseline_mae_h']} |")
        lines += [
            "",
            '"Irrigation within 6 h" as a yes/no prediction:',
            "",
            "| | Precision | Recall |",
            "|---|---|---|",
            f"| Model | {_pct(f['model_within_6h_precision'])} | {_pct(f['model_within_6h_recall'])} |",
            f"| Straight line | {_pct(f['baseline_within_6h_precision'])} | "
            f"{_pct(f['baseline_within_6h_recall'])} |",
            "",
        ]
    if "optimisation" in r:
        o = r["optimisation"]
        v = o["validation"]
        lines += [
            "## Controller setpoint optimisation",
            "",
            f"{o['candidates']} settings searched; the chosen one validated on seeds {v['seeds']} "
            f"({v['days']:g} days each).",
            "",
            "| Metric | Default | Tuned | Change |",
            "|---|---|---|---|",
        ]
        for k, label in (
            ("energy_kwh", "Equipment energy (kWh)"),
            ("temp_violation_h", "Hours outside temperature targets"),
            ("rh_violation_h", "Hours outside humidity targets"),
            ("water_l", "Water used (L)"),
        ):
            lines.append(
                f"| {label} | {v['default'][k]:.1f} | {v['tuned'][k]:.1f} | {v['change_pct'][k]:+.1f} % |"
            )
        lines += [
            "",
            "Tuned parameters (see `optimized_control.yaml`):",
            "",
            "| Parameter | Default | Tuned |",
            "|---|---|---|",
        ]
        d, b = o["search"]["default"]["params"], o["search"]["best"]["params"]
        for k in d:
            lines.append(f"| `{k}` | {d[k]:g} | {b[k]:g} |")
        lines.append("")
    return "\n".join(lines)


def load_models(ml_dir: Path = DEFAULT_ML_DIR) -> dict[str, Any] | None:
    path = ml_dir / MODEL_FILE
    return joblib.load(path) if path.exists() else None
