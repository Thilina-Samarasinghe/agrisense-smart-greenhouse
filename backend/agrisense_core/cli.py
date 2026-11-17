"""Command-line runner for the simulator.

Examples
--------
    python -m agrisense_core.cli simulate --hours 24 --out day.csv
    python -m agrisense_core.cli simulate --hours 48 --scenario hot_day --fans-daytime
    python -m agrisense_core.cli scenarios
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from agrisense_core.config import load_config
from agrisense_core.sim.engine import GreenhouseEngine
from agrisense_core.sim.scenarios import CATALOG


def _row(engine: GreenhouseEngine) -> dict[str, object]:
    w = engine.weather.state
    row: dict[str, object] = {
        "time": engine.now.isoformat(timespec="seconds"),
        "out_temp_c": round(w.temp_c, 2),
        "out_rh_pct": round(w.rh_pct, 1),
        "solar_w_m2": round(w.solar_w_m2, 1),
        "cloud": round(w.cloud, 2),
        "rain_mm_h": round(w.rain_mm_h, 1),
        "tank_pct": round(engine.tank.level_frac * 100, 2),
    }
    for zid, zm in engine.zones.items():
        s = zm.state
        row.update(
            {
                f"{zid}_temp_c": round(s.temp_c, 2),
                f"{zid}_rh_pct": round(s.rh_pct, 1),
                f"{zid}_vpd_kpa": round(s.vpd_kpa, 3),
                f"{zid}_co2_ppm": round(s.co2_ppm, 1),
                f"{zid}_vwc": round(s.vwc, 4),
                f"{zid}_soil_temp_c": round(s.soil_temp_c, 2),
                f"{zid}_par_umol": round(s.par_umol, 1),
                f"{zid}_dli_mol": round(s.dli_mol, 3),
                f"{zid}_et_mm_h": round(s.transpiration_mm_h, 4),
            }
        )
        sensed = engine.latest.get((f"{zid}.air", "air_temp"))
        row[f"{zid}_sensor_temp_c"] = sensed.value if sensed else None
        for aid in ("fan", "valve", "light"):
            act = engine.actuators.get(f"{zid}.{aid}")
            if act:
                row[f"{zid}_{aid}"] = act.actual
    row["pump"] = engine.actuators[engine.gh.pump.id].actual
    return row


def cmd_simulate(args: argparse.Namespace) -> int:
    engine = GreenhouseEngine(load_config(args.config), seed=args.seed, step_s=args.step)
    for name in args.scenario or []:
        engine.scenarios.start(name)

    rows: list[dict[str, object]] = []
    interval_steps = max(1, round(args.interval_min * 60 / engine.clock.step_s))
    total_steps = round(args.hours * 3600 / engine.clock.step_s)
    t0 = time.perf_counter()
    for i in range(total_steps):
        if args.fans_daytime:
            level = 1.0 if 7 <= engine.clock.hour_of_day < 18 else 0.0
            for zid in engine.zones:
                if engine.actuators[f"{zid}.fan"].commanded != level:
                    engine.command(f"{zid}.fan", level, reason="cli_schedule")
        engine.step()
        if i % interval_steps == 0:
            rows.append(_row(engine))
    elapsed = time.perf_counter() - t0

    if args.out:
        out = Path(args.out)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows to {out}")

    print(
        f"simulated {args.hours:g} h in {elapsed:.1f} s "
        f"(seed {engine.seed}, step {engine.clock.step_s:g} s)"
    )
    for zid, zm in engine.zones.items():
        temps = [r[f"{zid}_temp_c"] for r in rows]
        t = zm.state.totals
        print(
            f"  zone {zid} ({zm.cfg.crop}): temp {min(temps):.1f}..{max(temps):.1f} degC, "
            f"VWC now {zm.state.vwc:.3f}, ET total {t['et_l']:.0f} L, "
            f"irrigation {t['irrigation_l']:.0f} L"
        )
    print(f"  tank {engine.tank.level_frac * 100:.1f} %")
    return 0


def cmd_scenarios(_: argparse.Namespace) -> int:
    for s in CATALOG.values():
        dur = "instant" if s.default_duration_h == 0 else f"{s.default_duration_h:g} h"
        print(f"{s.name:16} {dur:>8}  {s.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agrisense", description="AgriSense simulator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sim = sub.add_parser("simulate", help="run the simulator and optionally write a CSV")
    sim.add_argument("--hours", type=float, default=24)
    sim.add_argument("--seed", type=int, default=None)
    sim.add_argument("--step", type=float, default=None, help="physics step in seconds (<= 10)")
    sim.add_argument("--interval-min", type=float, default=1.0, help="CSV row interval")
    sim.add_argument("--out", type=str, default=None, help="CSV output path")
    sim.add_argument("--config", type=str, default=None, help="directory with YAML profiles")
    sim.add_argument(
        "--scenario",
        action="append",
        choices=list(CATALOG),
        help="start a scenario at t=0 (repeatable)",
    )
    sim.add_argument(
        "--fans-daytime",
        action="store_true",
        help="run fans 07:00-18:00 (simple schedule until the Phase 2 controller)",
    )
    sim.set_defaults(func=cmd_simulate)

    sc = sub.add_parser("scenarios", help="list available scenarios")
    sc.set_defaults(func=cmd_scenarios)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
