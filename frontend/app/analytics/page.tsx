"use client";

import { useState } from "react";

import { GroupedBars, TableView } from "@/components/charts";
import { Card, Empty, Stat } from "@/components/ui";
import { get, type Summary } from "@/lib/api";
import { fmt, KIND_LABEL } from "@/lib/format";
import { usePolling } from "@/lib/live";

const WINDOWS = [
  { h: 6, label: "Last 6 h" },
  { h: 24, label: "Last 24 h" },
  { h: 72, label: "Last 3 days" },
  { h: 168, label: "Last 7 days" },
];

export default function Analytics() {
  const [hours, setHours] = useState(24);
  const s = usePolling(() => get<Summary>(`/api/analytics/summary?hours=${hours}`), 10000, [hours]);

  // Filter row first: one control scopes every chart on the page.
  const filters = (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="text-sm text-ink-2">Simulated time. Covers the current run only.</p>
      </div>
      <div className="flex gap-1" role="group" aria-label="Time range">
        {WINDOWS.map((w) => (
          <button key={w.h} className="btn" aria-pressed={hours === w.h} onClick={() => setHours(w.h)}>
            {w.label}
          </button>
        ))}
      </div>
    </div>
  );
  if (!s) return <div className="space-y-4">{filters}<Empty>Loading…</Empty></div>;

  const zones = Object.entries(s.zones);
  const water = zones.map(([id, z]) => ({
    zone: `${id} · ${z.crop}`,
    irrigation: z.water.irrigation_l,
    et: z.water.et_l,
  }));
  const violations = zones.map(([id, z]) => ({
    zone: `${id} · ${z.crop}`,
    temp: z.violation_minutes.temp / 60,
    rh: z.violation_minutes.rh / 60,
    vwc: z.violation_minutes.vwc / 60,
  }));
  const energy = Object.entries(s.energy_kwh_by_kind)
    .map(([kind, kwh]) => ({ kind: KIND_LABEL[kind] ?? kind, kwh }))
    .sort((a, b) => b.kwh - a.kwh);
  const totalIrrigation = zones.reduce((t, [, z]) => t + z.water.irrigation_l, 0);
  const alertCount = Object.values(s.alerts_by_code).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-4">
      {filters}
      <Card>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat label="Window covered" value={fmt(s.hours, 1)} unit="h" sub="of simulated time" />
          <Stat label="Water irrigated" value={fmt(totalIrrigation, 0)} unit="L" />
          <Stat label="Rain harvested" value={fmt(s.rain_harvested_l, 0)} unit="L" />
          <Stat label="Equipment energy" value={fmt(s.energy_kwh_total, 2)} unit="kWh" />
          <Stat label="Alerts raised" value={String(alertCount)} sub={`${s.decisions} controller decisions`} />
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Water per zone (litres)">
          <GroupedBars data={water} category="zone" unit="L" series={[
            { key: "irrigation", name: "Irrigation supplied", color: "var(--s1)" },
            { key: "et", name: "Crop water use (ET)", color: "var(--s2)" },
          ]} />
          <TableView head={["Zone", "Irrigation L", "ET L", "Irrigation minutes"]}
                     rows={zones.map(([id, z]) => [id, fmt(z.water.irrigation_l, 1), fmt(z.water.et_l, 1),
                                                   fmt(z.irrigation_minutes, 0)])} />
        </Card>
        <Card title="Energy by equipment (kWh)">
          <GroupedBars data={energy} category="kind" unit="kWh" digits={2}
                       series={[{ key: "kwh", name: "Energy", color: "var(--s1)" }]} />
          <TableView head={["Equipment", "kWh"]} rows={energy.map((e) => [e.kind, fmt(e.kwh, 3)])} />
        </Card>
      </div>

      <Card title="Time outside crop targets (hours)">
        <GroupedBars data={violations} category="zone" unit="h" digits={1} series={[
          { key: "temp", name: "Temperature", color: "var(--s1)" },
          { key: "rh", name: "Humidity", color: "var(--s2)" },
          { key: "vwc", name: "Soil moisture", color: "var(--s3)" },
        ]} />
        <TableView head={["Zone", "Temperature h", "Humidity h", "Soil moisture h"]}
                   rows={violations.map((v) => [v.zone, fmt(v.temp, 1), fmt(v.rh, 1), fmt(v.vwc, 1)])} />
        <p className="mt-2 text-xs text-muted">
          Based on the true simulated conditions against each crop&apos;s day/night targets. Lettuce is a
          cool-season crop, so in a lowland tropical climate it spends long periods above its temperature target.
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Zone climate summary">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs tabular">
              <thead className="text-ink-2">
                <tr>
                  {["Zone", "Temp min / mean / max °C", "RH mean %", "VWC mean %", "CO₂ mean ppm"].map((h) => (
                    <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {zones.map(([id, z]) => (
                  <tr key={id}>
                    <td className="border-b border-line py-1.5 pr-3">{id} · {z.crop}</td>
                    <td className="border-b border-line py-1.5 pr-3">
                      {z.temp_c ? `${fmt(z.temp_c.min)} / ${fmt(z.temp_c.mean)} / ${fmt(z.temp_c.max)}` : "n/a"}
                    </td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(z.rh_pct?.mean, 0)}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(z.vwc ? z.vwc.mean * 100 : null)}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(z.co2_ppm?.mean, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Equipment use">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs tabular">
              <thead className="text-ink-2">
                <tr>
                  {["Actuator", "Activations", "Runtime h", "Energy kWh"].map((h) => (
                    <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...zones.flatMap(([, z]) => Object.entries(z.equipment)),
                  ...(s.pump ? [["pump1", s.pump] as const] : [])].map(([aid, e]) => (
                  <tr key={aid}>
                    <td className="border-b border-line py-1.5 pr-3">{aid}</td>
                    <td className="border-b border-line py-1.5 pr-3">{e.activations}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(e.runtime_h, 2)}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(e.energy_kwh, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card title="Alerts raised in this window">
        {alertCount === 0 ? (
          <Empty>No alerts</Empty>
        ) : (
          <table className="w-full text-left text-xs tabular">
            <tbody>
              {Object.entries(s.alerts_by_code).sort((a, b) => b[1] - a[1]).map(([code, n]) => (
                <tr key={code}>
                  <td className="border-b border-line py-1.5 font-mono">{code}</td>
                  <td className="border-b border-line py-1.5 text-right">{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
