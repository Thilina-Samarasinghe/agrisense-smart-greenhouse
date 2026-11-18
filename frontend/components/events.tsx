"use client";

import { useState } from "react";

import { post, type Alert, type Decision } from "@/lib/api";
import { dayHhmm, pretty } from "@/lib/format";

import { Empty, StatusBadge, type Status } from "./ui";

const sevStatus = (s: string): Status => (s === "critical" ? "critical" : s === "warning" ? "warning" : "info");

export function AlertList({ alerts, compact = false }: { alerts: Alert[]; compact?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!alerts.length) return <Empty>No active alerts</Empty>;

  const reset = async (a: Alert) => {
    setBusy(a.code);
    try {
      await post("/api/alerts/reset", { code: a.code, scope: a.subject ?? a.zone_id });
    } finally {
      setBusy(null);
    }
  };

  return (
    <ul className="divide-y divide-[var(--border)]">
      {alerts.map((a) => (
        <li key={`${a.id}-${a.code}`} className="flex items-start gap-3 py-2">
          <div className="w-24 shrink-0 pt-0.5">
            <StatusBadge status={sevStatus(a.severity)} label={a.severity} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm">
              <span className="font-mono text-xs font-semibold">{a.code}</span>
              {a.latched && a.active && <span className="ml-2 text-xs text-ink-2">latched</span>}
              {!a.active && <span className="ml-2 text-xs text-muted">cleared</span>}
            </div>
            {!compact && <div className="text-sm text-ink-2">{pretty(a.message)}</div>}
            <div className="text-xs text-muted tabular">{dayHhmm(a.raised_at)}</div>
          </div>
          {a.latched && a.active && a.code !== "EMERGENCY_STOP" && (
            <button className="btn" disabled={busy === a.code} onClick={() => reset(a)}>
              Reset
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export function DecisionFeed({ decisions, empty = "No decisions yet" }: { decisions: Decision[]; empty?: string }) {
  if (!decisions.length) return <Empty>{empty}</Empty>;
  return (
    <ol className="space-y-1.5">
      {decisions.map((d, i) => (
        <li key={`${d.ts}-${d.actuator_id}-${i}`} className="flex gap-3 text-sm">
          <span className="w-28 shrink-0 text-xs text-muted tabular pt-0.5">{dayHhmm(d.ts)}</span>
          <span className="min-w-0">
            <span className={d.to_level > 0 ? "font-medium" : "text-ink-2"}>{pretty(d.message)}</span>
            {d.source !== "auto" && <span className="ml-2 text-xs text-muted">({d.source})</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
