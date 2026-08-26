"use client";

import type { Evidence } from "@/lib/api";

type Props = {
  evidence: Evidence;
};

export function EvidenceExplorer({ evidence }: Props) {
  const columns =
    evidence.result_preview.length > 0 ? Object.keys(evidence.result_preview[0]) : [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium tracking-tight">Evidence {evidence.id}</h3>
        <span className="text-xs text-[var(--label-secondary)]">Finding {evidence.finding_id}</span>
      </div>

      {evidence.row_count === 0 ? (
        <p className="text-xs text-[var(--warning)]">
          This query returned no rows, so it cannot support a conclusion.
        </p>
      ) : (
        <p className="text-xs text-[var(--label-secondary)]">
          {evidence.row_count.toLocaleString()} rows
          {evidence.truncated && " · preview truncated to the first rows"}
        </p>
      )}

      <div>
        <p className="section-title mb-1">SQL</p>
        <pre className="overflow-x-auto rounded-xl bg-[var(--code-bg)] p-3 text-xs text-[var(--success)]">
          {evidence.sql}
        </pre>
      </div>

      {Object.keys(evidence.metrics).length > 0 && (
        <div>
          <p className="section-title mb-1">Metrics</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(evidence.metrics).map(([k, v]) => (
              <span key={k} className="rounded-full bg-[var(--background)] px-2.5 py-1 text-xs">
                <span className="text-[var(--label-secondary)]">{k}:</span> {String(v)}
              </span>
            ))}
          </div>
        </div>
      )}

      {columns.length > 0 && (
        <div>
          <p className="section-title mb-1">Result preview</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c} className="border-b border-[var(--separator)] px-2 py-1 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {evidence.result_preview.map((row, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c} className="border-b border-[var(--separator)] px-2 py-1">
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
