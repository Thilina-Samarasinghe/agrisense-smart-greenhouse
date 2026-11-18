"use client";

import Link from "next/link";

import { ActuatorChip } from "@/components/actuators";
import { AlertList, DecisionFeed } from "@/components/events";
import { Card, Empty, Meter, rangeStatus, Stat, StatusBadge, StatusIcon, type Status } from "@/components/ui";
import { get, type AppConfig, type IrrigationForecast, type LiveState, type ZoneConfig } from "@/lib/api";
import { fmt, hourOf, inWindow, pct, ZONE_COLOR } from "@/lib/format";
import { useLive, usePolling } from "@/lib/live";

function tankStatus(pct: number): Status {
  if (pct < 10) return "critical";
  if (pct < 20) return "warning";
  return "good";
}

const IRRIGATION_LABEL: Record<string, string> = {
  idle: "Idle",
  watering: "Watering",
  soak: "Soaking",
  fallback: "Timed (sensor fail-safe)",
};

function ZoneCard({ zone, live, config, forecast }: {
  zone: ZoneConfig;
  live: LiveState;
  config: AppConfig;
  forecast?: IrrigationForecast;
}) {
  const z = live.zones[zone.id];
  if (!z) return null;
  const day = inWindow(hourOf(live.time), config.control.day_window);
  const t = zone.targets;
  const tempRange = day ? t.temp_day_c : t.temp_night_c;
  const vwcRange: [number, number] = [pct(t.vwc[0]), pct(t.vwc[1])];
  const acts = zone.actuators.map((id) => [id, live.actuators[id]] as const).filter(([, a]) => a);
  const zoneAlerts = live.alerts.filter((a) => a.zone_id === zone.id).length;

  return (
    <section className="card p-4" aria-labelledby={`zone-${zone.id}`}>
      <header className="mb-3 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span aria-hidden className="h-3 w-3 rounded-sm" style={{ background: ZONE_COLOR[zone.id] }} />
          <div>
            <h2 id={`zone-${zone.id}`} className="font-semibold">
              {zone.name} · {zone.crop_name}
            </h2>
            <div className="text-xs text-muted">
              {zone.stage} · {zone.area_m2} m²
            </div>
          </div>
        </div>
        <Link href={`/zones/${zone.id}`} className="btn">
          Details
        </Link>
      </header>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Stat label="Temperature" value={fmt(z.measured.temp)} unit="°C"
              status={rangeStatus(z.measured.temp, tempRange)}
              sub={`target ${tempRange[0]} to ${tempRange[1]} (${day ? "day" : "night"})`} />
        <Stat label="Humidity" value={fmt(z.measured.rh, 0)} unit="%"
              status={rangeStatus(z.measured.rh, t.rh_pct)} sub={`target ${t.rh_pct[0]} to ${t.rh_pct[1]}`} />
        <Stat label="Soil moisture" value={fmt(z.measured.vwc_pct)} unit="%"
              status={rangeStatus(z.measured.vwc_pct, vwcRange)} sub={`target ${vwcRange[0]} to ${vwcRange[1]}`} />
        <Stat label="Light (PAR)" value={fmt(z.true.par_umol, 0)} unit="µmol/m²/s"
              sub={`DLI ${fmt(z.dli_estimate)} of ${t.dli_mol_m2d[0]} mol`} />
        <Stat label="CO₂" value={fmt(z.true.co2_ppm, 0)} unit="ppm" sub={`VPD ${fmt(z.true.vpd_kpa, 2)} kPa`} />
        <Stat label="Irrigation" value={IRRIGATION_LABEL[z.irrigation ?? "idle"] ?? z.irrigation ?? ""}
              sub={z.irrigation_lpm > 0 ? `${fmt(z.irrigation_lpm, 1)} L/min`
                : forecast?.hours_model != null
                  ? forecast.hours_model >= 48 ? "next: > 48 h (forecast)" : `next: ~${fmt(forecast.hours_model, 0)} h (forecast)`
                  : "no flow"} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {acts.map(([id, a]) => (
          <ActuatorChip key={id} id={id} a={a} />
        ))}
      </div>
      {zoneAlerts > 0 && (
        <div className="mt-3">
          <StatusBadge status="warning" label={`${zoneAlerts} active alert${zoneAlerts > 1 ? "s" : ""}`} />
        </div>
      )}
    </section>
  );
}

export default function Overview() {
  const { live, config } = useLive();
  const forecast = usePolling(() => get<IrrigationForecast[]>("/api/intelligence/forecast"), 15000, []);
  if (!live || !config) return <Empty>Connecting to the greenhouse…</Empty>;
  const w = live.weather;
  const pump = live.actuators[Object.keys(config.actuators).find((a) => config.actuators[a].kind === "pump") ?? ""];
  const critical = live.alerts.filter((a) => a.severity === "critical").length;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Outside weather">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Temperature" value={fmt(w.temp_c)} unit="°C" />
            <Stat label="Humidity" value={fmt(w.rh_pct, 0)} unit="%" />
            <Stat label="Sun" value={fmt(w.solar_w_m2, 0)} unit="W/m²" />
            <Stat label="Cloud" value={fmt(w.cloud * 100, 0)} unit="%" />
            <Stat label="Wind" value={fmt(w.wind_ms)} unit="m/s" />
            <Stat label="Rain" value={fmt(w.rain_mm_h)} unit="mm/h" />
          </div>
        </Card>
        <Card title="Water supply">
          <Stat label="Tank level" value={fmt(live.tank.level_pct, 0)} unit="%" status={tankStatus(live.tank.level_pct)}
                sub={`${fmt(live.tank.volume_l, 0)} of ${config.greenhouse.tank_capacity_l} L`} />
          <div className="mt-2">
            <Meter pct={live.tank.level_pct} status={tankStatus(live.tank.level_pct)} />
          </div>
          {pump && (
            <div className="mt-3 text-xs text-ink-2">
              Pump <span className="font-semibold text-ink">{pump.level > 0 ? "running" : "off"}</span>
              {pump.rule && <span> · {pump.rule}</span>}
            </div>
          )}
        </Card>
        <Card title="System">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Active alerts" value={String(live.alerts.length)}
                  status={critical ? "critical" : live.alerts.length ? "warning" : "good"}
                  sub={critical ? `${critical} critical` : undefined} />
            <Stat label="Scenarios running" value={String(live.scenarios.length)}
                  sub={live.scenarios.map((s) => s.name).join(", ") || "none"} />
          </div>
          <div className="mt-3 text-xs text-ink-2">
            Controller {live.control ? "in AUTO" : "disabled"} · run #{live.run_id} · speed {live.speed}×
          </div>
          {live.storage && (
            <div className="mt-1 flex items-center gap-1.5 text-xs text-ink-2">
              <StatusIcon status={live.storage.write_errors ? "warning" : "good"} />
              History in {live.storage.remote ? "PostgreSQL" : "SQLite"}
              {live.storage.last_write.at && ` · last write ${live.storage.last_write.rows} rows in ${live.storage.last_write.seconds} s`}
              {live.storage.write_errors > 0 && ` · ${live.storage.write_errors} write errors (retrying)`}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {config.zones.map((z) => (
          <ZoneCard key={z.id} zone={z} live={live} config={config} forecast={forecast?.find((f) => f.zone_id === z.id)} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Active alerts (${live.alerts.length})`}>
          <AlertList alerts={live.alerts} />
        </Card>
        <Card title="Latest controller decisions" action={<Link href="/events" className="text-xs text-ink-2 underline">All events</Link>}>
          <DecisionFeed decisions={live.decisions.slice(0, 12)} />
        </Card>
      </div>
    </div>
  );
}
