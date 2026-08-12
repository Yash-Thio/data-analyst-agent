"use client";

import type { ReasoningStep } from "@/lib/api";

type Props = {
  steps: ReasoningStep[];
};

export function ReasoningTrace({ steps }: Props) {
  if (steps.length === 0) return null;

  return (
    <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-200">Reasoning trace</h3>
      <ol className="relative space-y-0 border-l border-zinc-200 pl-4 dark:border-zinc-700">
        {steps.map((step) => (
          <li key={step.order} className="relative pb-4">
            <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-indigo-500" />
            <p className="text-xs font-mono text-indigo-600">{step.node}</p>
            <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">{step.description}</p>
            <p className="text-xs text-zinc-500">{step.output_summary}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
