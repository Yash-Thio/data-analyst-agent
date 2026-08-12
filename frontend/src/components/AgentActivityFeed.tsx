"use client";

import type { AgentEvent } from "@/lib/api";

type Props = {
  events: AgentEvent[];
};

export function AgentActivityFeed({ events }: Props) {
  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800">
        Agent activity will appear here as analysis runs…
      </div>
    );
  }

  return (
    <div className="max-h-80 space-y-2 overflow-y-auto rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-200">Agent activity</h3>
      {events.map((ev, i) => (
        <div key={i} className="flex gap-2 text-sm">
          <span className="mt-0.5 shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            {ev.type}
          </span>
          <span className="text-zinc-700 dark:text-zinc-300">
            {ev.message || ev.summary || ev.text || (ev.tool ? `Tool: ${ev.tool}` : ev.content?.slice(0, 120))}
          </span>
        </div>
      ))}
    </div>
  );
}
