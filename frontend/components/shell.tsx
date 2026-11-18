"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { post } from "@/lib/api";
import { simClock } from "@/lib/format";
import { useLive } from "@/lib/live";

import { StatusIcon } from "./ui";

const SPEEDS = [1, 60, 600, 3600];

function Nav() {
  const path = usePathname();
  const { config } = useLive();
  const links = [
    { href: "/", label: "Overview" },
    ...(config?.zones ?? []).map((z) => ({ href: `/zones/${z.id}`, label: `${z.id} · ${z.crop_name}` })),
    { href: "/scenarios", label: "Scenarios" },
    { href: "/analytics", label: "Analytics" },
    { href: "/insights", label: "Insights" },
    { href: "/events", label: "Events" },
  ];
  return (
    <nav className="flex gap-1 overflow-x-auto" aria-label="Main">
      {links.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            className="whitespace-nowrap rounded-md px-3 py-1.5 text-sm"
            style={{ background: active ? "var(--surface-2)" : "transparent", fontWeight: active ? 600 : 400 }}
            aria-current={active ? "page" : undefined}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>("system");
  useEffect(() => {
    try {
      setTheme(localStorage.getItem("theme") ?? "system");
    } catch {
      /* storage blocked */
    }
  }, []);
  const apply = (t: string) => {
    setTheme(t);
    try {
      if (t === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", t);
    } catch {
      /* ignore */
    }
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  };
  return (
    <select aria-label="Theme" className="input" value={theme} onChange={(e) => apply(e.target.value)}>
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}

function SimControls() {
  const { live } = useLive();
  const [busy, setBusy] = useState(false);
  const call = async (path: string, body: unknown = {}) => {
    setBusy(true);
    try {
      await post(path, body);
    } finally {
      setBusy(false);
    }
  };
  if (!live) return null;
  const estop = live.emergency_stop;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="mr-2 text-sm">
        <div className="font-semibold tabular">{simClock(live.time)}</div>
        <div className="text-xs text-muted">
          simulated time{live.paused ? " · paused" : ""}
          {live.lagging ? " · lagging" : ""}
        </div>
      </div>
      <div className="flex gap-1" role="group" aria-label="Simulation speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            className="btn"
            aria-pressed={live.speed === s}
            disabled={busy}
            onClick={() => call("/api/sim/speed", { speed: s })}
            title={s === 1 ? "real time" : `${s} simulated seconds per second`}
          >
            {s}×
          </button>
        ))}
      </div>
      <button className="btn" disabled={busy} onClick={() => call(live.paused ? "/api/sim/resume" : "/api/sim/pause")}>
        {live.paused ? "Resume" : "Pause"}
      </button>
      <button className="btn" disabled={busy} onClick={() => call("/api/sim/advance", { hours: 6 })} title="Fast-forward 6 simulated hours">
        +6 h
      </button>
      {estop ? (
        <button className="btn" disabled={busy} onClick={() => call("/api/emergency-stop/reset")}>
          <StatusIcon status="critical" /> Reset emergency stop
        </button>
      ) : (
        <button
          className="btn btn-danger"
          disabled={busy}
          onClick={() => {
            if (confirm("Emergency stop: switch every actuator off until reset?"))
              call("/api/emergency-stop", { reason: "dashboard" });
          }}
        >
          Emergency stop
        </button>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { connected, error, live, config } = useLive();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <div className="text-lg font-semibold">🌱 AgriSense</div>
            <div className="text-xs text-muted">{config?.greenhouse.name ?? "Smart greenhouse"}</div>
          </div>
          <SimControls />
        </div>
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 pb-2">
          <Nav />
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-ink-2">
              <StatusIcon status={connected ? "good" : "critical"} />
              {connected ? "Live" : "Offline"}
            </span>
            <ThemeToggle />
          </div>
        </div>
      </header>
      {live?.emergency_stop && (
        <div className="border-b border-line bg-surface-2">
          <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2 text-sm font-medium">
            <StatusIcon status="critical" /> Emergency stop active: every actuator is off until reset.
          </div>
        </div>
      )}
      <main className="mx-auto max-w-7xl px-4 py-5">
        {error && !connected && (
          <div className="card mb-4 flex items-center gap-2 p-3 text-sm">
            <StatusIcon status="critical" />
            {error}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
