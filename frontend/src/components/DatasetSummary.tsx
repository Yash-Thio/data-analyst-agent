"use client";

import { useState } from "react";
import type { ColumnProfile, DatasetProfile } from "@/lib/api";

type Props = {
  filename: string;
  profile: DatasetProfile;
};

const ROLE_STYLES: Record<string, string> = {
  measure: "bg-[var(--success-fill)] text-[var(--success)]",
  dimension: "bg-[var(--accent-fill)] text-[var(--accent)]",
  temporal: "bg-[var(--warning-fill)] text-[var(--warning)]",
  identifier: "bg-[var(--separator)] text-[var(--label-secondary)]",
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
    <div className="space-y-3">
      <div>
        <p className="font-medium tracking-tight">{filename}</p>
        <p className="text-xs text-[var(--label-secondary)]">
          {profile.row_count.toLocaleString()} rows · {profile.column_count} columns ·{" "}
          {profile.measures.length} measures · {profile.dimensions.length} dimensions
        </p>
      </div>

      {dateColumn && (
        <p className="text-xs text-[var(--label-secondary)]">
          Dates in <code className="font-mono text-[var(--foreground)]">{dateColumn.name}</code>{" "}
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
        <p className="banner banner-info text-xs">
          This file stores {profile.wide.value_columns.length} periods as separate columns. An
          unpivoted view (<code className="font-mono">{profile.long_table_name}</code>) was built so
          trends and comparisons over time can be queried.
        </p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {visible.map((column) => (
          <span
            key={column.name}
            title={columnHint(column)}
            className={`rounded-full px-2.5 py-0.5 text-xs ${ROLE_STYLES[column.role] ?? ROLE_STYLES.dimension}`}
          >
            {column.name}
          </span>
        ))}
        {profile.columns.length > visible.length && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="btn rounded-full px-2.5 py-0.5 text-xs text-[var(--accent)]"
          >
            +{profile.columns.length - visible.length} more
          </button>
        )}
      </div>

      {problems.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-[var(--warning)]">
            {problems.length} data quality {problems.length === 1 ? "note" : "notes"}
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--label-secondary)]">
            {problems.map((warning, i) => (
              <li key={i}>{warning.message}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
