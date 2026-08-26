"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";

type Props = {
  charts: ChartSpec[];
};

/**
 * A spec is only renderable if both axes exist and at least one point has a
 * numeric y value. Recharts renders an empty box rather than failing, which
 * looks like a bug in the analysis rather than a chart that made no sense.
 */
function isRenderable(chart: ChartSpec): boolean {
  if (!chart?.x_key || !chart?.y_key || !Array.isArray(chart.data) || chart.data.length < 2) {
    return false;
  }
  return chart.data.some(
    (row) => typeof row?.[chart.y_key] === "number" && row?.[chart.x_key] != null
  );
}

const stroke = "var(--accent)";
const fill = "var(--accent-fill)";
const tick = { fontSize: 11, fill: "var(--label-secondary)" };

export function ChartPanel({ charts }: Props) {
  const renderable = (charts ?? []).filter(isRenderable);
  if (renderable.length === 0) return null;

  return (
    <div className="space-y-4">
      <h3 className="section-title">Charts</h3>
      {renderable.map((chart) => (
        <div key={chart.id} className="pt-2">
          <p className="mb-1 text-sm font-medium tracking-tight">{chart.title}</p>
          <p className="mb-3 text-xs text-[var(--label-secondary)]">
            Supports finding {chart.finding_id}
          </p>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              {chart.type === "line" ? (
                <LineChart data={chart.data}>
                  <CartesianGrid stroke="var(--separator)" vertical={false} />
                  <XAxis dataKey={chart.x_key} tick={tick} axisLine={false} tickLine={false} />
                  <YAxis tick={tick} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey={chart.y_key} stroke={stroke} strokeWidth={2} dot={false} />
                </LineChart>
              ) : chart.type === "area" ? (
                <AreaChart data={chart.data}>
                  <CartesianGrid stroke="var(--separator)" vertical={false} />
                  <XAxis dataKey={chart.x_key} tick={tick} axisLine={false} tickLine={false} />
                  <YAxis tick={tick} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Area type="monotone" dataKey={chart.y_key} fill={fill} stroke={stroke} />
                </AreaChart>
              ) : (
                <BarChart data={chart.data}>
                  <CartesianGrid stroke="var(--separator)" vertical={false} />
                  <XAxis dataKey={chart.x_key} tick={tick} axisLine={false} tickLine={false} />
                  <YAxis tick={tick} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Bar dataKey={chart.y_key} fill={stroke} radius={[6, 6, 0, 0]} />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}
