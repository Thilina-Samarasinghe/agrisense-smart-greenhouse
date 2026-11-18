"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ActuatorControl } from "@/components/actuators";
import { EquipmentStrips, TableView, TimeSeries } from "@/components/charts";
import { DecisionFeed } from "@/components/events";
import { Card, Empty, rangeStatus, Stat, StatusBadge, type Status } from "@/components/ui";
import { get, type Decision, type SensorRow, type ZonePoint } from "@/lib/api";
import { dayHhmm, fmt, hourOf, inWindow, pct, pretty } from "@/lib/format";
import { useLive, usePolling } from "@/lib/live";

const WINDOWS = [6, 24, 72];

const healthStatus = (h: string | null): Status =>
  h === "ok" ? "good" : h === "saturated" || h === "warming_up" ? "info" : h ? "critical" : "neutral";

export default function ZonePage() {
  const { id } = useParams<{ id: string }>();
  const { live, config } = useLive();
  const [hours, setHours] = useState(24);

  const history = usePolling(
    () => get<{ points: ZonePoint[]; bucket_min: number }>(`/api/history/zones/${id}?hours=${hours}`),
    5000,
    [id, hours],
  );
  const sensors = usePolling(() => get<SensorRow[]>("/api/sensors"), 5000, []);
  const decisions = usePolling(() => get<Decision[]>(`/api/decisions?zone=${id}&limit=30`), 5000, [id]);

  const zone = config?.zones.find((z) => z.id === id);

  const data = useMemo(() => {
    if (!history || !zone || !config) return [];
    const t = zone.targets;
    return history.points.map((p) => {
      const day = inWindow(hourOf(p.ts), config.control.day_window);
      return {
        ...p,
        vwc_pct: p.vwc * 100,
        temp_band: day ? t.temp_day_c : t.temp_night_c,
        rh_band: t.rh_pct,
        vwc_band: [pct(t.vwc[0]), pct(t.vwc[1])],
      };
    });
  }, [history, zone, config]);

  if (!config || !live) return <Empty>Connecting…</Empty>;
  if (!zone) return <Empty>Unknown zone {id}</Empty>;
  const z = live.zones[zone.id];
  const t = zone.targets;
  const day = inWindow(hourOf(live.time), config.control.day_window);
  const zoneSensors = (sensors ?? []).filter((s) => s.zone_id === zone.id);
  const equipmentRows = [
    { key: "fan", name: "Fans" },
    { key: "valve", name: "Valve" },
    ...(zone.actuators.includes(`${zone.id}.light`) ? [{ key: "light", name: "Grow lights" }] : []),
    ...(zone.actuators.includes(`${zone.id}.mister`) ? [{ key: "mister", name: "Mister" }] : []),
  ];
  const truthVsSensor = (trueKey: string, sensorKey: string) => [
    { key: trueKey, name: "Actual (simulated truth)", color: "var(--s1)" },
    { key: sensorKey, name: "Sensor reading (what the controller sees)", color: "var(--s2)" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            {zone.name} · {zone.crop_name}
          </h1>
          <p className="text-sm text-ink-2">
            {zone.stage} stage · {zone.area_m2} m² · {zone.soil.type} soil (field capacity{" "}
            {pct(zone.soil.field_capacity)} %, wilting point {pct(zone.soil.wilting_point)} %)
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Time range">
          {WINDOWS.map((h) => (
            <button key={h} className="btn" aria-pressed={hours === h} onClick={() => setHours(h)}>
              Last {h} h
            </button>
          ))}
        </div>
      </div>

      {z && (
        <Card>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
            <Stat label="Temperature" value={fmt(z.measured.temp)} unit="°C"
                  status={rangeStatus(z.measured.temp, day ? t.temp_day_c : t.temp_night_c)}
                  sub={`truth ${fmt(z.true.temp_c)} °C`} />
            <Stat label="Humidity" value={fmt(z.measured.rh, 0)} unit="%" status={rangeStatus(z.measured.rh, t.rh_pct)}
                  sub={`VPD ${fmt(z.true.vpd_kpa, 2)} kPa`} />
            <Stat label="Soil moisture" value={fmt(z.measured.vwc_pct)} unit="%"
                  status={rangeStatus(z.measured.vwc_pct, [pct(t.vwc[0]), pct(t.vwc[1])])}
                  sub={`truth ${fmt(z.true.vwc_pct)} %`} />
            <Stat label="Soil temp" value={fmt(z.true.soil_temp_c)} unit="°C" />
            <Stat label="CO₂" value={fmt(z.true.co2_ppm, 0)} unit="ppm" />
            <Stat label="DLI today" value={fmt(z.dli_estimate)} unit="mol/m²"
                  status={rangeStatus(z.dli_estimate, t.dli_mol_m2d)} sub={`target ${t.dli_mol_m2d.join(" to ")}`} />
            <Stat label="Crop water use" value={fmt(z.true.et_mm_h, 2)} unit="mm/h"
                  sub={`water stress Ks ${fmt(z.true.water_stress_ks, 2)}`} />
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Air temperature (°C)">
          <TimeSeries data={data} series={truthVsSensor("temp_c", "measured_temp_c")} unit="°C" band="temp_band" />
        </Card>
        <Card title="Relative humidity (%)">
          <TimeSeries data={data} series={truthVsSensor("rh_pct", "measured_rh_pct")} unit="%" band="rh_band" digits={0} />
        </Card>
        <Card title="Soil moisture (% VWC)">
          <TimeSeries data={data} series={truthVsSensor("vwc_pct", "measured_vwc_pct")} unit="%" band="vwc_band" />
        </Card>
        <Card title="Light at canopy (PAR, µmol/m²/s)">
          <TimeSeries data={data} series={[{ key: "par_umol", name: "PAR", color: "var(--s1)" }]} unit="µmol/m²/s"
                      digits={0} domain={[0, "auto"]} />
        </Card>
      </div>
      <Card title="Equipment">
        <EquipmentStrips data={data} rows={equipmentRows} />
        <TableView
          head={["Time", "Temp °C", "Sensor °C", "RH %", "VWC %", "PAR", ...equipmentRows.map((r) => r.name)]}
          rows={data.slice(-48).reverse().map((p) => [
            dayHhmm(p.ts), fmt(p.temp_c), fmt(p.measured_temp_c), fmt(p.rh_pct, 0), fmt(p.vwc_pct),
            fmt(p.par_umol, 0), ...equipmentRows.map((r) => fmt(p[r.key as keyof ZonePoint] as number, 2)),
          ])}
        />
        {history && history.bucket_min > 1 && (
          <p className="mt-1 text-xs text-muted">Points are {history.bucket_min}-minute averages.</p>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Equipment control" className="lg:col-span-3">
          {zone.actuators.map((aid) =>
            live.actuators[aid] ? <ActuatorControl key={aid} id={aid} a={live.actuators[aid]} /> : null,
          )}
          <p className="mt-2 text-xs text-muted">
            Overrides return to automatic after 30 minutes. Safety interlocks (dry tank, pump failure, high
            temperature) still apply to manual commands.
          </p>
        </Card>
        <Card title="Sensor health" className="lg:col-span-2">
          <table className="w-full text-left text-xs tabular">
            <thead className="text-ink-2">
              <tr>
                <th className="py-1 font-medium">Sensor</th>
                <th className="py-1 font-medium">Value</th>
                <th className="py-1 font-medium">Raw</th>
                <th className="py-1 font-medium">Health</th>
              </tr>
            </thead>
            <tbody>
              {zoneSensors.map((s) => (
                <tr key={`${s.sensor_id}-${s.quantity}`} className="border-t border-line">
                  <td className="py-1.5">
                    {s.sensor_id} <span className="text-muted">{s.model}</span>
                    <div className="text-muted">{s.quantity}</div>
                  </td>
                  <td className="py-1.5">{s.value === null ? "n/a" : pretty(`${s.value} ${s.unit}`)}</td>
                  <td className="py-1.5 text-muted">{s.raw ?? "n/a"}</td>
                  <td className="py-1.5">
                    <StatusBadge status={healthStatus(s.health)} label={s.health ?? "n/a"} />
                    {s.fault && <div className="text-critical">injected: {s.fault}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Decisions for this zone">
        <DecisionFeed decisions={decisions ?? []} />
      </Card>
    </div>
  );
}
