"use client";

import { useState } from "react";

import { AlertList, DecisionFeed } from "@/components/events";
import { Card } from "@/components/ui";
import { get, type Alert, type Decision } from "@/lib/api";
import { useLive, usePolling } from "@/lib/live";

export default function Events() {
  const { config } = useLive();
  const [tab, setTab] = useState<"decisions" | "alerts">("decisions");
  const [zone, setZone] = useState("");
  const [actuator, setActuator] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);

  const q = new URLSearchParams({ limit: "300" });
  if (zone) q.set("zone", zone);
  if (actuator) q.set("actuator", actuator);
  const decisions = usePolling(() => get<Decision[]>(`/api/decisions?${q}`), 4000, [zone, actuator]);
  const alerts = usePolling(
    () => get<Alert[]>(`/api/alerts?limit=300${activeOnly ? "&active_only=true" : ""}`),
    4000,
    [activeOnly],
  );
  const actuators = Object.keys(config?.actuators ?? {}).filter((a) => !zone || a.startsWith(`${zone}.`));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Event log</h1>
          <p className="text-sm text-ink-2">Every controller decision with the rule and readings behind it, and every alert.</p>
        </div>
        <div className="flex gap-1" role="group" aria-label="View">
          <button className="btn" aria-pressed={tab === "decisions"} onClick={() => setTab("decisions")}>
            Decisions
          </button>
          <button className="btn" aria-pressed={tab === "alerts"} onClick={() => setTab("alerts")}>
            Alerts
          </button>
        </div>
      </div>

      {tab === "decisions" ? (
        <Card
          title={`Decisions (${decisions?.length ?? 0}, newest first)`}
          action={
            <div className="flex gap-2">
              <select className="input" aria-label="Zone" value={zone} onChange={(e) => { setZone(e.target.value); setActuator(""); }}>
                <option value="">All zones</option>
                {config?.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
              </select>
              <select className="input" aria-label="Actuator" value={actuator} onChange={(e) => setActuator(e.target.value)}>
                <option value="">All equipment</option>
                {actuators.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
          }
        >
          <DecisionFeed decisions={decisions ?? []} />
        </Card>
      ) : (
        <Card
          title={`Alerts (${alerts?.length ?? 0})`}
          action={
            <label className="flex items-center gap-2 text-xs text-ink-2">
              <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
              Active only
            </label>
          }
        >
          <AlertList alerts={alerts ?? []} />
        </Card>
      )}
    </div>
  );
}
