"""History and analytics queries over stored simulation data."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from agrisense_core.config import AgriSenseConfig, hhmm_to_hours
from app.db.models import ActuatorState, AlertRow, DecisionRow, GreenhouseState, ZoneState

ZONE_FIELDS = [
    "temp_c",
    "rh_pct",
    "vpd_kpa",
    "co2_ppm",
    "vwc",
    "soil_temp_c",
    "par_umol",
    "dli_mol",
    "et_mm_h",
    "measured_temp_c",
    "measured_rh_pct",
    "measured_vwc_pct",
    "measured_lux",
    "fan",
    "valve",
    "light",
    "mister",
    "irrigation_l_total",
    "et_l_total",
]
SUMMARY_ZONE_COLUMNS = [
    "ts",
    "zone_id",
    "temp_c",
    "rh_pct",
    "vwc",
    "co2_ppm",
    "valve",
    "irrigation_l_total",
    "et_l_total",
]
GH_FIELDS = [
    "out_temp_c",
    "out_rh_pct",
    "solar_w_m2",
    "cloud",
    "wind_ms",
    "rain_mm_h",
    "tank_pct",
    "alerts_active",
]


def _bucket(rows: list[Any], fields: list[str], minutes: int) -> list[dict[str, Any]]:
    """Average rows into `minutes`-wide buckets (keeps charts light for long windows)."""
    if minutes <= 1:
        return [{"ts": r.ts.isoformat(), **{f: getattr(r, f) for f in fields}} for r in rows]
    groups: dict[datetime, list[Any]] = defaultdict(list)
    for r in rows:
        key = r.ts.replace(second=0, microsecond=0)
        key -= timedelta(minutes=key.minute % minutes)
        groups[key].append(r)
    out = []
    for key in sorted(groups):
        g = groups[key]
        item: dict[str, Any] = {"ts": key.isoformat()}
        for f in fields:
            vals = [v for r in g if (v := getattr(r, f)) is not None]
            item[f] = round(mean(vals), 4) if vals else None
        out.append(item)
    return out


def auto_bucket(hours: float, max_points: int = 720) -> int:
    return max(1, int(hours * 60 / max_points + 0.999))


def zone_history(
    s: Session, run_id: int, zone_id: str, since: datetime, bucket_min: int
) -> list[dict[str, Any]]:
    rows = s.scalars(
        select(ZoneState)
        .where(ZoneState.run_id == run_id, ZoneState.zone_id == zone_id, ZoneState.ts >= since)
        .order_by(ZoneState.ts)
    ).all()
    return _bucket(list(rows), ZONE_FIELDS, bucket_min)


def greenhouse_history(
    s: Session, run_id: int, since: datetime, bucket_min: int
) -> list[dict[str, Any]]:
    rows = s.scalars(
        select(GreenhouseState)
        .where(GreenhouseState.run_id == run_id, GreenhouseState.ts >= since)
        .order_by(GreenhouseState.ts)
    ).all()
    return _bucket(list(rows), GH_FIELDS, bucket_min)


def _in_window(hour: float, window: tuple[str, str]) -> bool:
    start, end = map(hhmm_to_hours, window)
    return start <= hour < end


def summary(
    s: Session, run_id: int, since: datetime, until: datetime, config: AgriSenseConfig
) -> dict[str, Any]:
    """Water, energy, equipment use and target violations for each zone over a window."""
    gh = config.greenhouse
    day_window = config.control.day_window
    # Everything below is aggregated in the database where possible: on a remote database
    # (e.g. Neon) transferring every stored row would take far longer than the maths.
    zone_rows = s.execute(
        select(*(getattr(ZoneState, c) for c in SUMMARY_ZONE_COLUMNS))
        .where(ZoneState.run_id == run_id, ZoneState.ts >= since)
        .order_by(ZoneState.ts)
    ).all()
    by_zone: dict[str, list[Any]] = defaultdict(list)
    for r in zone_rows:
        by_zone[r.zone_id].append(r)

    # Meters are cumulative: only the first and last row of each actuator are needed.
    bounds = (
        select(
            ActuatorState.actuator_id,
            func.min(ActuatorState.ts).label("t0"),
            func.max(ActuatorState.ts).label("t1"),
        )
        .where(ActuatorState.run_id == run_id, ActuatorState.ts >= since)
        .group_by(ActuatorState.actuator_id)
        .subquery()
    )
    edge_rows = s.scalars(
        select(ActuatorState)
        .join(
            bounds,
            and_(
                ActuatorState.actuator_id == bounds.c.actuator_id,
                or_(ActuatorState.ts == bounds.c.t0, ActuatorState.ts == bounds.c.t1),
            ),
        )
        .where(ActuatorState.run_id == run_id)
        .order_by(ActuatorState.ts)
    ).all()
    first: dict[str, ActuatorState] = {}
    last: dict[str, ActuatorState] = {}
    for r in edge_rows:
        first.setdefault(r.actuator_id, r)
        last[r.actuator_id] = r

    in_window = (DecisionRow.run_id == run_id, DecisionRow.ts >= since)
    decision_count = s.scalar(select(func.count()).select_from(DecisionRow).where(*in_window)) or 0
    activations = Counter(
        dict(
            s.execute(
                select(DecisionRow.actuator_id, func.count())
                .where(*in_window, DecisionRow.from_level == 0, DecisionRow.to_level > 0)
                .group_by(DecisionRow.actuator_id)
            ).all()
        )
    )
    alert_counts = s.execute(
        select(AlertRow.code, AlertRow.severity, func.count())
        .where(AlertRow.run_id == run_id, AlertRow.raised_at >= since)
        .group_by(AlertRow.code, AlertRow.severity)
    ).all()
    by_code: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    for code, severity, n in alert_counts:
        by_code[code] += n
        by_severity[severity] += n

    interval_min = config_interval_min(zone_rows)
    covered_from = max(since, zone_rows[0].ts) if zone_rows else until
    zones_out = {}
    for z in gh.zones:
        rows = by_zone.get(z.id, [])
        targets = config.crops[z.crop].targets
        viol = {"temp": 0.0, "rh": 0.0, "vwc": 0.0}
        for r in rows:
            hour = r.ts.hour + r.ts.minute / 60
            lo, hi = targets.temp_day_c if _in_window(hour, day_window) else targets.temp_night_c
            if not lo <= r.temp_c <= hi:
                viol["temp"] += interval_min
            if not targets.rh_pct[0] <= r.rh_pct <= targets.rh_pct[1]:
                viol["rh"] += interval_min
            if not targets.vwc[0] <= r.vwc <= targets.vwc[1]:
                viol["vwc"] += interval_min

        def stats(attr: str, rows: list[Any] = rows) -> dict[str, float] | None:
            vals = [getattr(r, attr) for r in rows]
            if not vals:
                return None
            return {
                "min": round(min(vals), 3),
                "mean": round(mean(vals), 3),
                "max": round(max(vals), 3),
            }

        def delta(attr: str, rows: list[Any] = rows) -> float:
            return (
                round(getattr(rows[-1], attr) - getattr(rows[0], attr), 2) if len(rows) > 1 else 0.0
            )

        equipment = {}
        for aid in (a for a in last if a.startswith(f"{z.id}.")):
            equipment[aid] = _equipment(first[aid], last[aid], activations[aid])
        zones_out[z.id] = {
            "name": z.name,
            "crop": z.crop,
            "samples": len(rows),
            "temp_c": stats("temp_c"),
            "rh_pct": stats("rh_pct"),
            "vwc": stats("vwc"),
            "co2_ppm": stats("co2_ppm"),
            "water": {"irrigation_l": delta("irrigation_l_total"), "et_l": delta("et_l_total")},
            "irrigation_minutes": round(sum(interval_min for r in rows if r.valve > 0), 1),
            "violation_minutes": {k: round(v, 1) for k, v in viol.items()},
            "equipment": equipment,
        }

    energy_by_kind: dict[str, float] = defaultdict(float)
    for aid in last:
        energy_by_kind[last[aid].kind] += last[aid].energy_wh_total - first[aid].energy_wh_total
    rain_lo, rain_hi = s.execute(  # cumulative counter: min/max are the first/last values
        select(
            func.min(GreenhouseState.tank_inflow_l_total),
            func.max(GreenhouseState.tank_inflow_l_total),
        ).where(GreenhouseState.run_id == run_id, GreenhouseState.ts >= since)
    ).one()
    return {
        "since": covered_from.isoformat(),
        "until": until.isoformat(),
        # Hours actually covered by data (a new run has less than the requested window).
        "hours": round((until - covered_from).total_seconds() / 3600, 2),
        "zones": zones_out,
        "pump": _equipment(first[gh.pump.id], last[gh.pump.id], activations[gh.pump.id])
        if gh.pump.id in last
        else None,
        "energy_kwh_by_kind": {k: round(v / 1000, 3) for k, v in sorted(energy_by_kind.items())},
        "energy_kwh_total": round(sum(energy_by_kind.values()) / 1000, 3),
        "rain_harvested_l": round(rain_hi - rain_lo, 1) if rain_lo is not None else 0.0,
        "alerts_by_code": dict(by_code),
        "alerts_by_severity": dict(by_severity),
        "decisions": decision_count,
    }


def config_interval_min(rows: list[Any]) -> float:
    """Spacing of stored rows in minutes (rows are evenly spaced per zone)."""
    seen: dict[str, datetime] = {}
    for r in rows:
        if r.zone_id in seen:
            return max(1e-6, (r.ts - seen[r.zone_id]).total_seconds() / 60)
        seen[r.zone_id] = r.ts
    return 1.0


def _equipment(a: ActuatorState, b: ActuatorState, activations: int) -> dict[str, float]:
    return {
        "energy_kwh": round((b.energy_wh_total - a.energy_wh_total) / 1000, 3),
        "runtime_h": round((b.runtime_s_total - a.runtime_s_total) / 3600, 2),
        "activations": activations,
    }
