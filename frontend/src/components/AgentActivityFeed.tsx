"use client";

import type { AgentEvent } from "@/lib/api";

type Props = {
  events: AgentEvent[];
};

const STYLES: Record<string, { badge: string; text: string }> = {
  error: {
    badge: "bg-[var(--danger-fill)] text-[var(--danger)]",
    text: "text-[var(--danger)]",
  },
  step_error: {
    badge: "bg-[var(--danger-fill)] text-[var(--danger)]",
    text: "text-[var(--danger)]",
  },
  warning: {
    badge: "bg-[var(--warning-fill)] text-[var(--warning)]",
    text: "text-[var(--warning)]",
  },
  step_retry: {
    badge: "bg-[var(--warning-fill)] text-[var(--warning)]",
    text: "text-[var(--warning)]",
  },
  finding: {
    badge: "bg-[var(--success-fill)] text-[var(--success)]",
    text: "text-[var(--foreground)]",
  },
};

const DEFAULT_STYLE = {
  badge: "bg-[var(--separator)] text-[var(--label-secondary)]",
  text: "text-[var(--foreground)]",
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
    return null;
  }

  return (
    <div className="surface-scroll max-h-64 space-y-2 overflow-y-auto pr-1">
      {visible.map((event, i) => {
        const style = STYLES[event.type] ?? DEFAULT_STYLE;
        return (
          <div key={i} className="flex gap-2 text-sm">
            <span
              className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase ${style.badge}`}
            >
              {LABELS[event.type] ?? event.type}
            </span>
            <div className="min-w-0">
              <span className={style.text}>{describe(event)}</span>
              {event.sql && (
                <pre className="mt-1 overflow-x-auto rounded-xl bg-[var(--code-bg)] p-2 font-mono text-[10px] text-[var(--success)]">
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
