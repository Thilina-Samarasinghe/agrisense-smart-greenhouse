"use client";

import { useState } from "react";

import { post, type ActuatorLive } from "@/lib/api";
import { hhmm, KIND_LABEL, levelLabel, pretty } from "@/lib/format";

/** Small read-only chip: equipment name, state and (as a tooltip) the rule behind it. */
export function ActuatorChip({ id, a }: { id: string; a: ActuatorLive }) {
  const on = a.level > 0;
  return (
    <span
      title={pretty(`${a.rule ?? ""}: ${a.reason ?? ""}`)}
      className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs"
      style={{ background: on ? "var(--surface-2)" : "transparent" }}
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full"
        style={{ background: on ? "var(--s1)" : "var(--axis)" }}
      />
      {KIND_LABEL[a.kind] ?? id}
      <span className={on ? "font-semibold" : "text-muted"}>{levelLabel(a.level)}</span>
      {a.mode && a.mode !== "auto" && <span className="text-ink-2">· {a.mode}</span>}
      {a.fault && <span className="text-critical">· {a.fault}</span>}
    </span>
  );
}

/** Full control row: state, explanation, mode and timed override. */
export function ActuatorControl({ id, a }: { id: string; a: ActuatorLive }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const act = async (path: string, body: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/actuators/${id}/${path}`, body);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const proportional = a.kind === "fan" || a.kind === "heater";

  return (
    <div className="border-b border-line py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-36 min-w-0">
          <div className="text-sm font-medium">{KIND_LABEL[a.kind] ?? a.kind}</div>
          <div className="text-xs text-muted">{id}</div>
        </div>
        <div className="w-16 text-sm">
          <span className={a.level > 0 ? "font-semibold" : "text-ink-2"}>{levelLabel(a.level)}</span>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <select
            aria-label={`${id} mode`}
            className="input"
            value={a.mode ?? "auto"}
            disabled={busy}
            onChange={(e) => act("mode", { mode: e.target.value, level: e.target.value === "manual" ? 1 : 0 })}
          >
            <option value="auto">Auto</option>
            <option value="manual">Manual ON</option>
            <option value="off">Off</option>
          </select>
          <button className="btn" disabled={busy} onClick={() => act("override", { level: 1, duration_min: 30 })}>
            ON 30 min
          </button>
          {proportional && (
            <button className="btn" disabled={busy} onClick={() => act("override", { level: 0.5, duration_min: 30 })}>
              50 % 30 min
            </button>
          )}
          <button className="btn" disabled={busy} onClick={() => act("override", { level: 0, duration_min: 30 })}>
            OFF 30 min
          </button>
        </div>
      </div>
      <div className="mt-1.5 text-xs text-ink-2">
        <span className="font-mono">{a.rule}</span>
        {a.reason && <span> · {pretty(a.reason)}</span>}
        {a.override_until && <span className="text-ink"> · override until {hhmm(a.override_until)}</span>}
        {a.fault && <span className="text-critical"> · fault: {a.fault}</span>}
        {err && <div className="text-critical">{err}</div>}
      </div>
    </div>
  );
}
