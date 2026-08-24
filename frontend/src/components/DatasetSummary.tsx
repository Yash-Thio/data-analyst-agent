"use client";

import { useState } from "react";
import type { ColumnProfile, DatasetProfile } from "@/lib/api";

type Props = {
  filename: string;
  profile: DatasetProfile;
};

const ROLE_STYLES: Record<string, string> = {
  measure: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
  dimension: "bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-300",
  temporal: "bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-300",
  identifier: "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
};

function columnHint(column: ColumnProfile): string {
  const parts: string[] = [column.semantic_type];
  if (column.date_format) parts.push(`parsed as ${column.date_format}`);
  if (column.temporal_grain) parts.push(`${column.temporal_grain} grain`);
  if (column.null_pct >= 1) parts.push(`${column.null_pct.toFixed(0)}% missing`);
  if (column.role === "identifier") parts.push("not aggregated");
  return parts.join(" · ");
}

export function DatasetSummary({ filename, profile }: Props) {
  const [showAll, setShowAll] = useState(false);

  const dateColumn = profile.columns.find((c) => c.date_format);
  const problems = profile.quality.warnings.filter((w) => w.severity !== "info");
  const visible = showAll ? profile.columns : profile.columns.slice(0, 14);

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div>
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{filename}</p>
        <p className="text-xs text-zinc-500">
          {profile.row_count.toLocaleString()} rows · {profile.column_count} columns ·{" "}
          {profile.measures.length} measures · {profile.dimensions.length} dimensions
        </p>
      </div>

      {dateColumn && (
        <p className="text-xs text-zinc-500">
          Dates in <code className="font-mono text-zinc-700 dark:text-zinc-300">{dateColumn.name}</code>{" "}
          read as <code className="font-mono">{dateColumn.date_format}</code>
          {dateColumn.date_range?.min && (
            <>
              {" "}
              ({dateColumn.date_range.min} to {dateColumn.date_range.max})
            </>
          )}
        </p>
      )}

      {profile.layout === "wide" && profile.wide && (
        <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">
          This file stores {profile.wide.value_columns.length} periods as separate columns. An
          unpivoted view (<code className="font-mono">{profile.long_table_name}</code>) was built so
          trends and comparisons over time can be queried.
        </p>
      )}

      <div className="flex flex-wrap gap-1">
        {visible.map((column) => (
          <span
            key={column.name}
            title={columnHint(column)}
            className={`rounded px-2 py-0.5 text-xs ${ROLE_STYLES[column.role] ?? ROLE_STYLES.dimension}`}
          >
            {column.name}
          </span>
        ))}
        {profile.columns.length > visible.length && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="rounded px-2 py-0.5 text-xs text-indigo-600 hover:underline dark:text-indigo-400"
          >
            +{profile.columns.length - visible.length} more
          </button>
        )}
      </div>

      {problems.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-amber-700 dark:text-amber-400">
            {problems.length} data quality {problems.length === 1 ? "note" : "notes"}
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-600 dark:text-zinc-400">
            {problems.map((warning, i) => (
              <li key={i}>{warning.message}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
