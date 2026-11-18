"use client";

import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { dayHhmm, hhmm } from "@/lib/format";

// Chart chrome: recessive hairline grid and axes, muted tick labels, system sans.
const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--muted)", fontSize: 11 }, tickLine: false };
const GRID = <CartesianGrid vertical={false} stroke="var(--grid)" />;
const NO_ANIM = { isAnimationActive: false } as const;
// Legend: series order (not alphabetical) and text in ink colour, never the series colour.
const LEGEND = {
  itemSorter: null,
  formatter: (value: string) => <span style={{ color: "var(--ink-2)" }}>{value}</span>,
} as const;

/** Evenly spaced axis ticks on clean steps (1, 1.5, 2, 2.5, 3, 5 x 10^n), 3 to 5 intervals. */
export function niceTicks(max: number): number[] {
  if (!(max > 0)) return [0, 1];
  const target = max * 1.12; // headroom for the value labels above the bars
  const raw = target / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 1.5, 2, 2.5, 3, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const n = Math.ceil(target / step);
  return Array.from({ length: n + 1 }, (_, i) => Number((i * step).toPrecision(6)));
}

type TipEntry = { name?: string; value?: unknown; color?: string; dataKey?: unknown };

function Tip({
  active,
  payload,
  label,
  unit,
  digits = 1,
  labelFormat = dayHhmm,
}: {
  active?: boolean;
  payload?: TipEntry[];
  label?: string | number;
  unit: string;
  digits?: number;
  labelFormat?: (v: string) => string;
}) {
  if (!active || !payload?.length) return null;
  const show = (v: unknown) => {
    if (Array.isArray(v)) return `${Number(v[0]).toFixed(digits)} to ${Number(v[1]).toFixed(digits)}`;
    if (v === null || v === undefined) return "n/a";
    return Number(v).toFixed(digits);
  };
  return (
    <div className="card px-3 py-2 text-xs shadow-sm" style={{ minWidth: 160 }}>
      <div className="mb-1 font-medium tabular">{labelFormat(String(label))}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-ink-2">
            <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-medium tabular">
            {show(p.value)} {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

export type Series = { key: string; name: string; color: string };

/** Time series of 1-2 lines on ONE axis with an optional stepped target band behind them. */
export function TimeSeries({
  data,
  series,
  unit,
  band,
  height = 220,
  digits = 1,
  domain,
}: {
  data: Record<string, unknown>[];
  series: Series[];
  unit: string;
  band?: string; // key holding [lo, hi]
  height?: number;
  digits?: number;
  domain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
        {GRID}
        <XAxis dataKey="ts" tickFormatter={hhmm} minTickGap={48} {...AXIS} />
        <YAxis width={44} domain={domain ?? ["auto", "auto"]} {...AXIS}
               tickFormatter={(v: number) => v.toFixed(digits > 1 ? 1 : 0)} />
        <Tooltip content={<Tip unit={unit} digits={digits} />} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
        <Legend verticalAlign="top" align="left" height={26} iconSize={12}
                wrapperStyle={{ fontSize: 12 }} {...LEGEND} />
        {band && (
          <Area dataKey={band} name="Target range" type="stepAfter" fill="var(--band)" stroke="none" color="var(--muted)"
                activeDot={false} legendType="square" {...NO_ANIM} />
        )}
        {series.map((s) => (
          <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} dot={false}
                activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} connectNulls={false}
                legendType="plainline" {...NO_ANIM} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Equipment on/off history: one small single-series strip per actuator (small multiples). */
export function EquipmentStrips({
  data,
  rows,
}: {
  data: Record<string, unknown>[];
  rows: { key: string; name: string }[];
}) {
  return (
    <div className="space-y-1">
      {rows.map((r, i) => (
        <div key={r.key} className="flex items-center gap-2">
          <div className="w-24 shrink-0 text-xs text-ink-2">{r.name}</div>
          <div className="min-w-0 flex-1">
            <ResponsiveContainer width="100%" height={i === rows.length - 1 ? 52 : 34}>
              <AreaChart data={data} margin={{ top: 2, right: 12, bottom: 0, left: 0 }}>
                <XAxis dataKey="ts" hide={i !== rows.length - 1} tickFormatter={hhmm} minTickGap={48} {...AXIS} />
                <YAxis hide domain={[0, 1]} />
                <Tooltip
                  content={<Tip unit="" digits={2} />}
                  cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
                />
                <Area dataKey={r.key} name={`${r.name} level (0 to 1)`} type="stepAfter" stroke="var(--s1)"
                      strokeWidth={1.5} fill="var(--s1)" fillOpacity={0.25} {...NO_ANIM} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}

/** Grouped bars by category, one colour per series (fixed order), legend + direct value labels. */
export function GroupedBars({
  data,
  category,
  series,
  unit,
  height = 240,
  digits = 0,
}: {
  data: Record<string, unknown>[];
  category: string;
  series: Series[];
  unit: string;
  height?: number;
  digits?: number;
}) {
  const max = Math.max(0, ...data.flatMap((d) => series.map((sr) => Number(d[sr.key]) || 0)));
  const ticks = niceTicks(max);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} barGap={2} barCategoryGap="28%">
        {GRID}
        <XAxis dataKey={category} {...AXIS} />
        <YAxis width={48} domain={[0, ticks[ticks.length - 1]]} ticks={ticks} {...AXIS} />
        <Tooltip content={<Tip unit={unit} digits={digits} labelFormat={(v) => v} />}
                 cursor={{ fill: "var(--surface-2)" }} />
        {series.length > 1 && (
          <Legend verticalAlign="top" align="left" height={26} iconSize={10} iconType="square"
                  wrapperStyle={{ fontSize: 12, top: -8 }} {...LEGEND} />
        )}
        {series.map((s) => (
          <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={36}
               {...NO_ANIM}>
            <LabelList dataKey={s.key} position="top" fill="var(--ink-2)" fontSize={11}
                       formatter={(v: unknown) => (typeof v === "number" ? v.toFixed(digits) : "")} />
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Accessible table view behind every chart (values never live only in a tooltip). */
export function TableView({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-xs text-ink-2">Show table</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs tabular">
          <thead className="text-ink-2">
            <tr>
              {head.map((h) => (
                <th key={h} className="border-b border-line py-1 pr-4 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} className="border-b border-line py-1 pr-4">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
