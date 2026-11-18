export const ZONE_COLOR: Record<string, string> = { A: "var(--s1)", B: "var(--s2)", C: "var(--s3)" };

export const KIND_LABEL: Record<string, string> = {
  pump: "Pump",
  valve: "Valve",
  fan: "Fans",
  grow_light: "Grow lights",
  mister: "Mister",
  heater: "Heater",
};

export function fmt(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return `${v.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

/** Backend messages use ASCII units; show proper symbols. */
export function pretty(s: string): string {
  return s.replace(/degC/g, "°C").replace(/umol/g, "µmol");
}

/** Fractions to percent without floating-point noise (0.28 * 100 = 28.000000000000004). */
export const pct = (x: number) => Math.round(x * 1000) / 10;

export function levelLabel(level: number): string {
  if (level <= 0) return "OFF";
  if (level >= 1) return "ON";
  return `${Math.round(level * 100)} %`;
}

export function simClock(iso: string | undefined): string {
  if (!iso) return "--:--";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function hhmm(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function dayHhmm(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${hhmm(iso)}`;
}

export function hourOf(iso: string): number {
  const d = new Date(iso);
  return d.getHours() + d.getMinutes() / 60;
}

export function inWindow(hour: number, window: [string, string]): boolean {
  const toH = (s: string) => {
    const [h, m] = s.split(":").map(Number);
    return h + m / 60;
  };
  return hour >= toH(window[0]) && hour < toH(window[1]);
}

export function speedLabel(speed: number): string {
  if (speed < 60) return `${speed}×`;
  if (speed < 3600) return `${speed}× (1 h ≈ ${Math.round(3600 / speed)} s)`;
  return `${speed}× (1 h/s)`;
}
