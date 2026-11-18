"use client";

import { useState } from "react";

import { GroupedBars, TableView } from "@/components/charts";
import { Card, Empty, StatusBadge, type Status } from "@/components/ui";
import {
  get,
  post,
  type Advice,
  type Anomaly,
  type IntelStatus,
  type IrrigationForecast,
  type Phase4Report,
} from "@/lib/api";
import { dayHhmm, fmt, pretty } from "@/lib/format";
import { useLive, usePolling } from "@/lib/live";

const DETECTORS: { key: string; name: string; color: string; about: string }[] = [
  { key: "rules", name: "Rules (Phase 2)", color: "var(--s1)", about: "stale, out of range, spikes, stuck, probe disagreement" },
  { key: "isolation", name: "IsolationForest", color: "var(--s2)", about: "unsupervised outlier detection" },
  { key: "virtual", name: "Virtual sensor", color: "var(--s3)", about: "predicts each sensor from its peers; flags persistent residuals" },
  { key: "supervised", name: "Supervised", color: "var(--s4)", about: "classifier trained on labelled simulated faults" },
];

const UNITS: Record<string, string> = { air_temp: "°C", soil_vwc: "% VWC", co2_ppm: "ppm" };
const sev = (s: string): Status => (s === "critical" ? "critical" : s === "warning" ? "warning" : "info");
const pct = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${Math.round(x * 100)} %`);

function ModelStatus({ status }: { status: IntelStatus | null }) {
  const [busy, setBusy] = useState(false);
  if (!status) return null;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <StatusBadge status={status.models_loaded ? "good" : "warning"}
                       label={status.models_loaded ? "Models loaded" : "Models not trained yet"} />
          <span className="text-xs text-ink-2">
            {status.trained_at ? `trained ${dayHhmm(status.trained_at)} · ` : ""}
            {status.history_minutes} min of live history
          </span>
        </div>
        <button className="btn" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await post("/api/intelligence/reload"); } finally { setBusy(false); }
        }}>
          Reload models
        </button>
      </div>
      {!status.models_loaded && (
        <p className="mt-2 text-sm text-ink-2">
          Train them once with <code className="rounded bg-surface-2 px-1">{status.how_to_train}</code> (about
          15 minutes on 8 cores), then press Reload. Advice works without models.
        </p>
      )}
    </Card>
  );
}

function ForecastCards({ forecast }: { forecast: IrrigationForecast[] }) {
  const { config } = useLive();
  if (!forecast.length) return <Empty>Forecast available once models are trained and 30 minutes of history exist</Empty>;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {forecast.map((f) => {
        const zone = config?.zones.find((z) => z.id === f.zone_id);
        return (
          <div key={f.zone_id} className="rounded-lg border border-line p-3">
            <div className="text-sm font-medium">{zone ? `${zone.name} · ${zone.crop_name}` : f.zone_id}</div>
            {f.irrigating_now ? (
              <div className="mt-1 text-xl font-semibold">Irrigating now</div>
            ) : (
              <div className="mt-1 text-xl font-semibold">
                {f.hours_model === null ? "n/a" : f.hours_model >= 48 ? "> 48 h" : `in ~${fmt(f.hours_model, 1)} h`}
              </div>
            )}
            <div className="mt-1 text-xs text-ink-2">
              soil {fmt(f.vwc_pct)} %, irrigation starts at {f.start_pct} %
            </div>
            {!f.irrigating_now && (
              <div className="text-xs text-muted">
                straight-line estimate: {f.hours_straight_line === null ? "n/a"
                  : f.hours_straight_line >= 48 ? "> 48 h" : `${fmt(f.hours_straight_line, 1)} h`}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function AnomalyTable({ rows }: { rows: Anomaly[] }) {
  if (!rows.length) return <Empty>Anomaly scores appear once models are trained and history exists</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs tabular">
        <thead className="text-ink-2">
          <tr>
            {["Sensor", "Reading", "Deviation from expected", "Virtual-sensor score", "Classifier", "Rules", "Status"].map((h) => (
              <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.channel}>
              <td className="border-b border-line py-1.5 pr-3">{a.channel}</td>
              <td className="border-b border-line py-1.5 pr-3">{fmt(a.value, 1)} {UNITS[a.quantity]}</td>
              <td className="border-b border-line py-1.5 pr-3">
                {a.residual === null ? "n/a" : `${a.residual > 0 ? "+" : ""}${fmt(a.residual, 2)} ${UNITS[a.quantity]}`}
              </td>
              <td className="border-b border-line py-1.5 pr-3">{fmt(a.virtual_score, 2)} <span className="text-muted">(flag &gt; 1)</span></td>
              <td className="border-b border-line py-1.5 pr-3">{pct(a.supervised_probability)}</td>
              <td className="border-b border-line py-1.5 pr-3">{a.rule_flag ? "flagged" : "ok"}</td>
              <td className="border-b border-line py-1.5 pr-3">
                {a.warming_up ? <StatusBadge status="neutral" label="warming up" />
                  : <StatusBadge status={a.flagged ? "warning" : "good"} label={a.flagged ? "suspect" : "ok"} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Try it: start a Sensor failure scenario with an offset or drift on an air sensor. The rules cannot see
        it; the virtual sensor flags it within minutes. The 24 h baseline needs a few hours of history first.
      </p>
    </div>
  );
}

function OfflineResults({ report }: { report: Phase4Report | null }) {
  if (!report) return <Empty>No evaluation report yet: run agrisense ml all</Empty>;
  const a = report.anomaly;
  const f = report.forecast;
  const o = report.optimisation;
  const faults = ["stuck", "spike", "drift", "offset"];
  const byFault = a
    ? faults.map((ft) => ({
        fault: ft,
        ...Object.fromEntries(DETECTORS.map((d) => [d.key, Math.round((a.methods[d.key]?.by_fault[ft]?.recall ?? 0) * 100)])),
      }))
    : [];
  return (
    <div className="space-y-4">
      {a && (
        <Card title="Sensor fault detection on held-out simulations">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs tabular">
              <thead className="text-ink-2">
                <tr>
                  {["Detector", "How it works", "Precision", "Recall", "F1", "Faults caught", "False alarms / sensor-day"].map((h) => (
                    <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {DETECTORS.map((d) => {
                  const m = a.methods[d.key];
                  return (
                    <tr key={d.key}>
                      <td className="border-b border-line py-1.5 pr-3 font-medium">{d.name}</td>
                      <td className="border-b border-line py-1.5 pr-3 text-ink-2">{d.about}</td>
                      <td className="border-b border-line py-1.5 pr-3">{pct(m.precision)}</td>
                      <td className="border-b border-line py-1.5 pr-3">{pct(m.recall)}</td>
                      <td className="border-b border-line py-1.5 pr-3">{m.f1.toFixed(2)}</td>
                      <td className="border-b border-line py-1.5 pr-3">{pct(m.event_recall)}</td>
                      <td className="border-b border-line py-1.5 pr-3">{m.false_alarms_per_channel_day.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <h3 className="mb-1 mt-5 text-sm font-semibold">Share of fault events caught, by fault type (%)</h3>
          <GroupedBars data={byFault} category="fault" unit="%" series={DETECTORS.map((d) => ({ key: d.key, name: d.name, color: d.color }))} />
          <TableView
            head={["Fault", ...DETECTORS.map((d) => `${d.name} caught / median delay`)]}
            rows={faults.map((ft) => [ft, ...DETECTORS.map((d) => {
              const b = a.methods[d.key].by_fault[ft];
              return b.events ? `${b.detected}/${b.events}${b.median_delay_min !== null ? `, ${b.median_delay_min} min` : ""}` : "n/a";
            })])}
          />
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {f && (
          <Card title="Irrigation forecast accuracy (hours until next irrigation)">
            <table className="w-full text-left text-xs tabular">
              <thead className="text-ink-2">
                <tr>{["Horizon", "Model error", "Straight-line error"].map((h) => (
                  <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>))}</tr>
              </thead>
              <tbody>
                <tr>
                  <td className="border-b border-line py-1.5 pr-3 font-medium">All</td>
                  <td className="border-b border-line py-1.5 pr-3">{f.model_mae_h} h</td>
                  <td className="border-b border-line py-1.5 pr-3">{f.baseline_mae_h} h</td>
                </tr>
                {Object.entries(f.buckets).map(([k, b]) => (
                  <tr key={k}>
                    <td className="border-b border-line py-1.5 pr-3">{k} ahead</td>
                    <td className="border-b border-line py-1.5 pr-3">{b.model_mae_h} h</td>
                    <td className="border-b border-line py-1.5 pr-3">{b.baseline_mae_h} h</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">Mean absolute error on {f.test_minutes.toLocaleString()} test minutes.</p>
          </Card>
        )}
        {o && (
          <Card title="Setpoint optimisation (validated on unseen weather)">
            <table className="w-full text-left text-xs tabular">
              <thead className="text-ink-2">
                <tr>{["Metric", "Default", "Tuned", "Change"].map((h) => (
                  <th key={h} className="border-b border-line py-1 pr-3 font-medium">{h}</th>))}</tr>
              </thead>
              <tbody>
                {[["energy_kwh", "Energy (kWh)"], ["temp_violation_h", "Hours outside temperature target"],
                  ["rh_violation_h", "Hours outside humidity target"], ["water_l", "Water (L)"]].map(([k, label]) => (
                  <tr key={k}>
                    <td className="border-b border-line py-1.5 pr-3">{label}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(o.validation.default[k], 1)}</td>
                    <td className="border-b border-line py-1.5 pr-3">{fmt(o.validation.tuned[k], 1)}</td>
                    <td className="border-b border-line py-1.5 pr-3">{o.validation.change_pct[k] > 0 ? "+" : ""}{fmt(o.validation.change_pct[k], 1)} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">
              {o.candidates} settings tried in closed-loop simulation; validated on {o.validation.seeds.length} unseen
              weather seeds × {o.validation.days} days. Settings: ml/reports/optimized_control.yaml.
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function Insights() {
  const status = usePolling(() => get<IntelStatus>("/api/intelligence/status"), 10000, []);
  const advice = usePolling(() => get<Advice[]>("/api/intelligence/advice?hours=24"), 15000, []);
  const forecast = usePolling(() => get<IrrigationForecast[]>("/api/intelligence/forecast"), 10000, []);
  const anomalies = usePolling(() => get<Anomaly[]>("/api/intelligence/anomalies"), 10000, []);
  const report = usePolling(() => get<Phase4Report | null>("/api/intelligence/report"), 60000, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Insights</h1>
        <p className="text-sm text-ink-2">
          Crop advice, irrigation forecasts and sensor anomaly detection. Every model was evaluated on simulations
          it never saw during training.
        </p>
      </div>
      <ModelStatus status={status} />
      <Card title={`Recommendations (last 24 h)${advice ? ` · ${advice.length}` : ""}`}>
        {!advice?.length ? <Empty>No recommendations</Empty> : (
          <ul className="divide-y divide-[var(--border)]">
            {advice.map((a, i) => (
              <li key={i} className="flex gap-3 py-2.5">
                <div className="w-24 shrink-0 pt-0.5"><StatusBadge status={sev(a.severity)} label={a.severity} /></div>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{pretty(a.title)}</div>
                  <div className="text-sm text-ink-2">{pretty(a.detail)}</div>
                  <div className="text-xs text-muted">Evidence: {pretty(a.evidence)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Next irrigation (forecast)"><ForecastCards forecast={forecast ?? []} /></Card>
      <Card title="Sensor anomaly detection (live)"><AnomalyTable rows={anomalies ?? []} /></Card>
      <OfflineResults report={report ?? null} />
    </div>
  );
}
