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

export function ChartPanel({ charts }: Props) {
  if (charts.length === 0) return null;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">Charts</h3>
      {charts.map((chart) => (
        <div key={chart.id} className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
          <p className="mb-2 text-sm font-medium">{chart.title}</p>
          <p className="mb-3 text-xs text-zinc-500">Supports finding {chart.finding_id}</p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              {chart.type === "line" ? (
                <LineChart data={chart.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey={chart.x_key} tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey={chart.y_key} stroke="#4f46e5" strokeWidth={2} />
                </LineChart>
              ) : chart.type === "area" ? (
                <AreaChart data={chart.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey={chart.x_key} tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Area type="monotone" dataKey={chart.y_key} fill="#c7d2fe" stroke="#4f46e5" />
                </AreaChart>
              ) : (
                <BarChart data={chart.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey={chart.x_key} tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey={chart.y_key} fill="#4f46e5" />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}
