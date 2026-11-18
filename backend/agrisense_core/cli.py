"""Command-line runner for the simulator and automation controller.

Examples
--------
    agrisense simulate --hours 24 --out day.csv                 # closed loop (controller on)
    agrisense simulate --hours 48 --scenario hot_day --log decisions.txt
    agrisense simulate --hours 24 --no-control --fans-daytime   # open loop, Phase 1 style
    agrisense scenarios
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

from agrisense_core.config import load_config
from agrisense_core.runtime import GreenhouseRuntime
from agrisense_core.sim.scenarios import CATALOG


def _row(rt: GreenhouseRuntime) -> dict[str, object]:
    engine = rt.engine
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
        for aid in ("fan", "valve", "light", "mister"):
            act = engine.actuators.get(f"{zid}.{aid}")
            if act:
                row[f"{zid}_{aid}"] = act.actual
    row["pump"] = engine.actuators[engine.gh.pump.id].actual
    if rt.controller:
        row["alerts_active"] = len(rt.controller.alerts.active)
    return row


def cmd_simulate(args: argparse.Namespace) -> int:
    if args.fans_daytime and not args.no_control:
        print("--fans-daytime needs --no-control (the controller manages the fans)")
        return 2
    rt = GreenhouseRuntime(
        load_config(args.config), seed=args.seed, step_s=args.step, control=not args.no_control
    )
    engine = rt.engine
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
        rt.step()
        if i % interval_steps == 0:
            rows.append(_row(rt))
    elapsed = time.perf_counter() - t0

    if args.out:
        out = Path(args.out)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows to {out}")

    mode = "closed loop" if rt.controller else "open loop"
    print(
        f"simulated {args.hours:g} h in {elapsed:.1f} s "
        f"({mode}, seed {engine.seed}, step {engine.clock.step_s:g} s)"
    )
    for zid, zm in engine.zones.items():
        temps = [r[f"{zid}_temp_c"] for r in rows]
        vwcs = [r[f"{zid}_vwc"] for r in rows]
        t = zm.state.totals
        print(
            f"  zone {zid} ({zm.cfg.crop}): temp {min(temps):.1f}..{max(temps):.1f} degC, "
            f"VWC {min(vwcs):.3f}..{max(vwcs):.3f}, ET {t['et_l']:.0f} L, "
            f"irrigation {t['irrigation_l']:.0f} L"
        )
    energy = sum(a.energy_wh for a in engine.actuators.values()) / 1000
    print(f"  tank {engine.tank.level_frac * 100:.1f} %, equipment energy {energy:.1f} kWh")

    ctl = rt.controller
    if ctl:
        per_actuator = Counter(d.actuator_id for d in ctl.decisions)
        print(
            f"  decisions: {len(ctl.decisions)} ("
            + ", ".join(f"{a} {n}" for a, n in sorted(per_actuator.items()))
            + ")"
        )
        raised = Counter(a.code for a in ctl.alerts.history)
        print("  alerts raised: " + (", ".join(f"{c} x{n}" for c, n in raised.items()) or "none"))
        if args.log:
            with Path(args.log).open("w", encoding="utf-8") as fh:
                for d in ctl.decisions:
                    fh.write(f"{d.ts:%Y-%m-%d %H:%M:%S}  {d.message}\n")
                for a in ctl.alerts.history:
                    end = f" (cleared {a.cleared_at:%H:%M})" if a.cleared_at else ""
                    fh.write(
                        f"{a.raised_at:%Y-%m-%d %H:%M:%S}  ALERT {a.severity} {a.code}: "
                        f"{a.message}{end}\n"
                    )
            print(f"  decision and alert log written to {args.log}")
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
    sim.add_argument("--log", type=str, default=None, help="write decisions and alerts here")
    sim.add_argument("--config", type=str, default=None, help="directory with YAML profiles")
    sim.add_argument(
        "--scenario",
        action="append",
        choices=list(CATALOG),
        help="start a scenario at t=0 (repeatable)",
    )
    sim.add_argument("--no-control", action="store_true", help="disable the automation controller")
    sim.add_argument(
        "--fans-daytime",
        action="store_true",
        help="with --no-control: run fans 07:00-18:00 on a fixed schedule",
    )
    sim.set_defaults(func=cmd_simulate)

    sc = sub.add_parser("scenarios", help="list available scenarios")
    sc.set_defaults(func=cmd_scenarios)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
