"use client";

import type { ReactNode } from "react";

/** Status = state, never identity: colour plus icon plus label, never colour alone. */
export type Status = "good" | "warning" | "critical" | "info" | "neutral";

const STATUS: Record<Status, { color: string; icon: string; label: string }> = {
  good: { color: "var(--good)", icon: "✓", label: "OK" },
  warning: { color: "var(--warning)", icon: "!", label: "Warning" },
  critical: { color: "var(--critical)", icon: "✕", label: "Critical" },
  info: { color: "var(--s1)", icon: "i", label: "Info" },
  neutral: { color: "var(--muted)", icon: "•", label: "n/a" },
};

export function StatusIcon({ status }: { status: Status }) {
  const s = STATUS[status];
  return (
    <span
      aria-hidden
      className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
      style={{ background: s.color, color: status === "warning" ? "#0b0b0b" : "#ffffff" }}
    >
      {s.icon}
    </span>
  );
}

export function StatusBadge({ status, label }: { status: Status; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
      <StatusIcon status={status} />
      {label ?? STATUS[status].label}
    </span>
  );
}

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  sub,
  status,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: ReactNode;
  status?: Status;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        {status && <StatusIcon status={status} />}
        {label}
      </div>
      <div className="mt-0.5 text-xl font-semibold">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-2">{unit}</span>}
      </div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Meter({ pct, status }: { pct: number; status: Status }) {
  const color = status === "good" ? "var(--s1)" : `var(--${status === "neutral" ? "muted" : status})`;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2" role="meter" aria-valuenow={pct}
         aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function rangeStatus(value: number | null | undefined, [lo, hi]: [number, number]): Status {
  if (value === null || value === undefined) return "neutral";
  return value >= lo && value <= hi ? "good" : "warning";
}
