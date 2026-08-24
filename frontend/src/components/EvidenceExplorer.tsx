"use client";

import type { Evidence } from "@/lib/api";

type Props = {
  evidence: Evidence | null;
};

export function EvidenceExplorer({ evidence }: Props) {
  if (!evidence) {
    return (
      <div className="rounded-xl border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800">
        Click a claim or evidence ID to inspect SQL and result rows.
      </div>
    );
  }

  const columns =
    evidence.result_preview.length > 0 ? Object.keys(evidence.result_preview[0]) : [];

  return (
    <div className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-indigo-800 dark:text-indigo-200">
          Evidence {evidence.id}
        </h3>
        <span className="text-xs text-zinc-500">Finding {evidence.finding_id}</span>
      </div>

      {evidence.row_count === 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          This query returned no rows, so it cannot support a conclusion.
        </p>
      ) : (
        <p className="text-xs text-zinc-500">
          {evidence.row_count.toLocaleString()} rows
          {evidence.truncated && " · preview truncated to the first rows"}
        </p>
      )}

      <div>
        <p className="mb-1 text-xs font-medium uppercase text-zinc-500">SQL</p>
        <pre className="overflow-x-auto rounded-lg bg-zinc-900 p-3 text-xs text-emerald-300">
          {evidence.sql}
        </pre>
      </div>

      {Object.keys(evidence.metrics).length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase text-zinc-500">Metrics</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(evidence.metrics).map(([k, v]) => (
              <span
                key={k}
                className="rounded bg-white px-2 py-1 text-xs dark:bg-zinc-900"
              >
                <span className="text-zinc-500">{k}:</span> {String(v)}
              </span>
            ))}
          </div>
        </div>
      )}

      {columns.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase text-zinc-500">Result preview</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c} className="border-b border-zinc-200 px-2 py-1 font-medium dark:border-zinc-700">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {evidence.result_preview.map((row, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c} className="border-b border-zinc-100 px-2 py-1 dark:border-zinc-800">
                        {String(row[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
