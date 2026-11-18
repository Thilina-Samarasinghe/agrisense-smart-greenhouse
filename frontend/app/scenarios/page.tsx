"use client";

import { useState } from "react";

import { Card, Empty, StatusIcon } from "@/components/ui";
import { del, get, post, type ScenarioInfo, type SensorRow } from "@/lib/api";
import { dayHhmm } from "@/lib/format";
import { useLive, usePolling } from "@/lib/live";

const FAULTS: Record<string, string[]> = {
  sensor_failure: ["stuck", "dropout", "spike", "drift", "offset"],
  actuator_fault: ["failed", "stuck_on", "stuck_off"],
  pump_failure: ["failed", "stuck_off"],
};

const GROUPS: { title: string; names: string[] }[] = [
  { title: "Weather", names: ["hot_day", "heatwave", "rainfall", "cloudy", "cold_night"] },
  { title: "Disturbances", names: ["humidity_spike", "dry_soil", "water_shortage", "refill_tank"] },
  { title: "Equipment and sensor faults", names: ["pump_failure", "actuator_fault", "sensor_failure"] },
];

const PARAM_LABEL: Record<string, string> = {
  temp_offset_c: "Temperature change (°C)",
  rain_mm_h: "Rain (mm/h)",
  cloud: "Cloud cover (0 to 1)",
  rh_pct: "Humidity (%)",
  vwc: "Soil moisture (0 to 1 VWC)",
  level_pct: "Tank level (%)",
  magnitude: "Magnitude (sensor units, or per hour for drift)",
};

const label = (s: string) =>
  PARAM_LABEL[s] ?? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function ScenarioCard({ sc, sensors }: { sc: ScenarioInfo; sensors: string[] }) {
  const { config } = useLive();
  const [params, setParams] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(sc.params).map(([k, v]) => [k, v === null ? "" : String(v)])),
  );
  const [duration, setDuration] = useState(String(sc.default_duration_h));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    setMsg(null);
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === "") continue;
      body[k] = ["zone", "sensor", "actuator", "fault"].includes(k) ? v : Number(v);
    }
    try {
      await post("/api/scenarios", {
        name: sc.name,
        duration_h: sc.default_duration_h > 0 ? Number(duration) : undefined,
        params: body,
      });
      setMsg({ ok: true, text: "Started" });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const field = (k: string) => {
    const set = (v: string) => setParams((p) => ({ ...p, [k]: v }));
    const common = { className: "input w-full", value: params[k] ?? "", onChange: (e: { target: { value: string } }) => set(e.target.value) };
    if (k === "zone")
      return (
        <select {...common} aria-label="zone">
          <option value="">All zones</option>
          {config?.zones.map((z) => (
            <option key={z.id} value={z.id}>{z.name} ({z.crop_name})</option>
          ))}
        </select>
      );
    if (k === "sensor")
      return (
        <select {...common} aria-label="sensor">
          <option value="">Choose a sensor</option>
          {sensors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      );
    if (k === "actuator")
      return (
        <select {...common} aria-label="actuator">
          <option value="">Choose an actuator</option>
          {Object.keys(config?.actuators ?? {}).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      );
    if (k === "fault")
      return (
        <select {...common} aria-label="fault">
          {(FAULTS[sc.name] ?? []).map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      );
    return <input {...common} type="number" step="any" aria-label={k} placeholder="default" />;
  };

  return (
    <div className="card flex flex-col gap-3 p-4">
      <div>
        <h3 className="font-semibold">{label(sc.name)}</h3>
        <p className="text-sm text-ink-2">{sc.description}</p>
      </div>
      {Object.keys(sc.params).length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {Object.keys(sc.params).map((k) => (
            <label key={k} className="text-xs text-ink-2">
              {label(k)}
              <div className="mt-0.5">{field(k)}</div>
            </label>
          ))}
        </div>
      )}
      <div className="mt-auto flex items-end justify-between gap-2">
        {sc.default_duration_h > 0 ? (
          <label className="text-xs text-ink-2">
            Duration (h)
            <input className="input mt-0.5 block w-24" type="number" min={0.1} step="any" value={duration}
                   onChange={(e) => setDuration(e.target.value)} />
          </label>
        ) : (
          <span className="text-xs text-muted">Instant change</span>
        )}
        <button className="btn" disabled={busy} onClick={start} style={{ fontWeight: 600 }}>
          Start
        </button>
      </div>
      {msg && (
        <div className="flex items-center gap-1.5 text-xs">
          <StatusIcon status={msg.ok ? "good" : "critical"} /> {msg.text}
        </div>
      )}
    </div>
  );
}

export default function Scenarios() {
  const { live, config } = useLive();
  const sensors = usePolling(() => get<SensorRow[]>("/api/sensors"), 30000, []);
  const sensorIds = [...new Set((sensors ?? []).map((s) => s.sensor_id))];
  const [resetting, setResetting] = useState(false);

  if (!config || !live) return <Empty>Connecting…</Empty>;
  const byName = Object.fromEntries(config.scenarios.map((s) => [s.name, s]));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Scenarios</h1>
          <p className="text-sm text-ink-2">
            Inject weather events, disturbances and faults, then watch the controller respond on the overview,
            zone pages and event log.
          </p>
        </div>
        <button
          className="btn"
          disabled={resetting}
          onClick={async () => {
            if (!confirm("Start a new simulation run? History of the current run is kept for comparison.")) return;
            setResetting(true);
            try {
              await post("/api/sim/reset", {});
            } finally {
              setResetting(false);
            }
          }}
        >
          New simulation run
        </button>
      </div>

      <Card title={`Active scenarios (${live.scenarios.length})`}>
        {live.scenarios.length === 0 ? (
          <Empty>No timed scenarios running</Empty>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {live.scenarios.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div>
                  <span className="font-medium">{label(s.name)}</span>
                  <span className="ml-2 text-xs text-ink-2">
                    {Object.entries(s.params).filter(([, v]) => v !== null).map(([k, v]) => `${k}=${v}`).join(", ")}
                  </span>
                  <div className="text-xs text-muted tabular">
                    {dayHhmm(s.started)} to {s.ends ? dayHhmm(s.ends) : "?"}
                  </div>
                </div>
                <button className="btn" onClick={() => del(`/api/scenarios/${s.id}`)}>Stop</button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {GROUPS.map((g) => (
        <section key={g.title}>
          <h2 className="mb-2 text-sm font-semibold text-ink-2">{g.title}</h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {g.names.filter((n) => byName[n]).map((n) => (
              <ScenarioCard key={n} sc={byName[n]} sensors={sensorIds} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
