"""Crop advisor: turns analytics, live state and model outputs into recommendations.

Rule-based and fully explainable: every recommendation carries the evidence that triggered it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agrisense_core.config import AgriSenseConfig

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Advice:
    severity: str  # critical | warning | info
    zone_id: str | None
    title: str
    detail: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def advise(
    summary: dict[str, Any],
    config: AgriSenseConfig,
    live: dict[str, Any] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
    optimisation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[Advice] = []
    hours = max(summary.get("hours", 0.0), 1e-6)
    if hours < 6:
        return [
            Advice(
                "info",
                None,
                "Not enough history yet",
                "Recommendations need at least 6 simulated hours of data.",
                f"{hours:.1f} h recorded",
            ).to_dict()
        ]

    for z in config.greenhouse.zones:
        zs = summary["zones"].get(z.id)
        if not zs or not zs.get("temp_c"):
            continue
        crop = config.crops[z.crop]
        t = crop.targets
        name = f"{z.name} ({crop.display_name})"
        viol = zs["violation_minutes"]
        fan = zs["equipment"].get(f"{z.id}.fan", {})
        fan_share = fan.get("runtime_h", 0) / hours

        # Temperature
        f_temp = viol["temp"] / 60 / hours
        if f_temp > 0.5:
            if fan_share > 0.5:
                detail = (
                    "Fans already run most of the time, and ventilation cannot cool below the outside "
                    "air. Add cooling capacity: a shade screen (cuts the solar load by 30 to 50 %) or "
                    "pad-and-fan evaporative cooling"
                )
                if t.temp_day_c[1] <= 22:
                    detail += (
                        f". {crop.display_name} is a cool-season crop: in this climate a cooler season "
                        "or a highland site would suit it better"
                    )
                detail += "."
            else:
                detail = (
                    "Fans are not running most of the time. Check fan thresholds and the "
                    "ventilation benefit settings in control.yaml."
                )
            out.append(
                Advice(
                    "warning",
                    z.id,
                    f"{name} is too warm {f_temp:.0%} of the time",
                    detail,
                    f"mean {zs['temp_c']['mean']:.1f} °C, max {zs['temp_c']['max']:.1f} °C; "
                    f"fans ran {fan_share:.0%} of the time",
                )
            )
        elif f_temp > 0.15:
            out.append(
                Advice(
                    "info",
                    z.id,
                    f"{name} is outside its temperature target {f_temp:.0%} of the time",
                    "Consider tighter fan thresholds or earlier fog cooling.",
                    f"range {zs['temp_c']['min']:.1f} to {zs['temp_c']['max']:.1f} °C",
                )
            )

        # Humidity
        f_rh = viol["rh"] / 60 / hours
        if f_rh > 0.3 and zs["rh_pct"]["mean"] > t.rh_pct[1] - 5:
            out.append(
                Advice(
                    "warning",
                    z.id,
                    f"{name}: humidity high {f_rh:.0%} of the time",
                    "Prolonged high humidity raises the risk of fungal disease (botrytis, mildew). "
                    "Venting only helps when outside air is drier; consider wider plant spacing, "
                    "morning ventilation when outside air dries out, or removing lower leaves "
                    "for air movement.",
                    f"mean RH {zs['rh_pct']['mean']:.0f} % vs target {t.rh_pct[0]:g} to {t.rh_pct[1]:g} %",
                )
            )

        # Soil moisture
        f_vwc = viol["vwc"] / 60 / hours
        vwc_mean = zs["vwc"]["mean"]
        if f_vwc > 0.25 and vwc_mean < t.vwc[0]:
            out.append(
                Advice(
                    "warning",
                    z.id,
                    f"{name}: soil drier than target {f_vwc:.0%} of the time",
                    "Irrigation may be too slow or starting too late: add emitters, or raise the "
                    "crop's minimum VWC.",
                    f"mean VWC {vwc_mean * 100:.1f} % vs target {t.vwc[0] * 100:g} to {t.vwc[1] * 100:g} %",
                )
            )
        elif f_vwc > 0.25 and vwc_mean > t.vwc[1]:
            out.append(
                Advice(
                    "info",
                    z.id,
                    f"{name}: soil wetter than target {f_vwc:.0%} of the time",
                    "Wet roots lose oxygen. Lower the irrigation stop level.",
                    f"mean VWC {vwc_mean * 100:.1f} %",
                )
            )

        # CO2
        co2 = zs.get("co2_ppm")
        if co2 and co2["min"] < 330:
            out.append(
                Advice(
                    "info",
                    z.id,
                    f"{name}: CO₂ drops to {co2['min']:.0f} ppm",
                    "Photosynthesis draws CO₂ below outside levels when the greenhouse is closed. "
                    "More daytime air exchange, or CO₂ enrichment, would raise growth.",
                    f"min {co2['min']:.0f} ppm, mean {co2['mean']:.0f} ppm",
                )
            )

        # Light (from live controller estimate)
        if live:
            zl = live.get("zones", {}).get(z.id, {})
            dli = zl.get("dli_estimate")
            if dli is not None and dli > t.dli_mol_m2d[1] * 1.15:
                out.append(
                    Advice(
                        "info",
                        z.id,
                        f"{name}: light above the crop's maximum today",
                        "A shade screen would cut excess light and heat at the same time.",
                        f"DLI so far {dli:.1f} mol/m² vs maximum {t.dli_mol_m2d[1]:g}",
                    )
                )

        # Water balance
        w = zs["water"]
        if hours >= 24 and w["et_l"] > 0 and w["irrigation_l"] > 1.6 * w["et_l"]:
            out.append(
                Advice(
                    "info",
                    z.id,
                    f"{name}: irrigation well above crop water use",
                    "Some water is likely draining past the roots. Check the irrigation stop level.",
                    f"irrigated {w['irrigation_l']:.0f} L vs crop use {w['et_l']:.0f} L",
                )
            )

    alerts = summary.get("alerts_by_code", {})
    if alerts.get("IRRIGATION_TIMEOUT"):
        out.append(
            Advice(
                "warning",
                None,
                "Irrigation cycles are hitting the time limit",
                "A zone did not reach its target within the maximum cycle. Check for clogged "
                "emitters, leaks or a probe outside the wetted area.",
                f"{alerts['IRRIGATION_TIMEOUT']} timeout(s)",
            )
        )
    if alerts.get("TANK_CRITICAL") or alerts.get("TANK_LOW"):
        out.append(
            Advice(
                "warning",
                None,
                "Water tank ran low",
                "Add storage, more roof catchment, or a mains top-up valve.",
                f"{alerts.get('TANK_CRITICAL', 0)} critical, {alerts.get('TANK_LOW', 0)} low alerts",
            )
        )
    if alerts.get("PUMP_NO_FLOW"):
        out.append(
            Advice(
                "critical",
                None,
                "Pump failure detected",
                "The pump ran without flow. Inspect the pump, intake and filter, then reset the alarm.",
                f"{alerts['PUMP_NO_FLOW']} alarm(s)",
            )
        )
    sensor_issues = alerts.get("SENSOR_FAULT", 0) + alerts.get("SENSOR_DISAGREE", 0)
    if sensor_issues:
        out.append(
            Advice(
                "warning",
                None,
                "Sensor problems were reported",
                "Check wiring and placement; recalibrate soil probes that disagree.",
                f"{sensor_issues} sensor alert(s)",
            )
        )

    for a in anomalies or []:
        if a.get("flagged"):
            out.append(
                Advice(
                    "warning",
                    a.get("zone_id"),
                    f"Sensor {a['channel']} looks wrong",
                    "Its reading no longer matches what the other sensors and equipment imply "
                    "(possible drift, offset or a stuck value). Check or recalibrate it.",
                    f"deviation {a.get('residual', 0):+.2f} from the expected value",
                )
            )

    energy = summary.get("energy_kwh_by_kind", {})
    total = summary.get("energy_kwh_total", 0)
    if total > 0 and energy.get("fan", 0) / total > 0.7:
        detail = "Fans dominate energy use."
        if optimisation and optimisation.get("change_pct"):
            ch = optimisation["change_pct"]
            comfort = "no more" if ch["violation_h"] <= 0 else f"{ch['violation_h']:.0f} % more"
            detail += (
                f" The tuned setpoints in ml/reports/optimized_control.yaml used "
                f"{-ch['energy_kwh']:.0f} % less energy in validation with {comfort} "
                "time outside crop targets."
            )
        out.append(
            Advice(
                "info",
                None,
                f"Fans use {energy['fan'] / total:.0%} of equipment energy",
                detail,
                f"{energy['fan']:.1f} of {total:.1f} kWh",
            )
        )

    out.sort(key=lambda a: (SEVERITY_ORDER[a.severity], a.zone_id or ""))
    return [a.to_dict() for a in out]
