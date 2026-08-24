"use client";

import type { AgentEvent } from "@/lib/api";

type Props = {
  events: AgentEvent[];
};

const STYLES: Record<string, { badge: string; text: string }> = {
  error: {
    badge: "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300",
    text: "text-red-700 dark:text-red-300",
  },
  step_error: {
    badge: "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300",
    text: "text-red-700 dark:text-red-300",
  },
  warning: {
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
    text: "text-amber-800 dark:text-amber-300",
  },
  step_retry: {
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
    text: "text-amber-800 dark:text-amber-300",
  },
  finding: {
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
    text: "text-zinc-700 dark:text-zinc-300",
  },
};

const DEFAULT_STYLE = {
  badge: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  text: "text-zinc-700 dark:text-zinc-300",
};

const LABELS: Record<string, string> = {
  step_retry: "retry",
  step_error: "failed",
  tool_call: "query",
  node_start: "step",
};

function describe(event: AgentEvent): string {
  if (event.message) return event.message;
  if (event.summary) return event.summary;
  if (event.text) return event.text;
  if (event.type === "tool_call") {
    return `Ran a query · ${event.row_count ?? 0} rows`;
  }
  return event.content?.slice(0, 160) ?? "";
}

export function AgentActivityFeed({ events }: Props) {
  const visible = events.filter((e) => e.type !== "ping" && e.type !== "report_chunk");

  if (visible.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800">
        Agent activity will appear here as analysis runs…
      </div>
    );
  }

  return (
    <div className="max-h-80 space-y-2 overflow-y-auto rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-200">Agent activity</h3>
      {visible.map((event, i) => {
        const style = STYLES[event.type] ?? DEFAULT_STYLE;
        return (
          <div key={i} className="flex gap-2 text-sm">
            <span
              className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${style.badge}`}
            >
              {LABELS[event.type] ?? event.type}
            </span>
            <div className="min-w-0">
              <span className={style.text}>{describe(event)}</span>
              {event.sql && (
                <pre className="mt-1 overflow-x-auto rounded bg-zinc-50 p-2 font-mono text-[10px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
                  {event.sql}
                </pre>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
