"use client";

import type { ReasoningStep } from "@/lib/api";

type Props = {
  steps: ReasoningStep[];
};

export function ReasoningTrace({ steps }: Props) {
  if (steps.length === 0) return null;

  return (
    <ol className="relative space-y-0 border-l border-[var(--separator)] pl-4">
      {steps.map((step) => (
        <li key={step.order} className="relative pb-4 last:pb-0">
          <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-[var(--accent)]" />
          <p className="font-mono text-xs text-[var(--accent)]">{step.node}</p>
          <p className="text-sm font-medium tracking-tight">{step.description}</p>
          <p className="text-xs text-[var(--label-secondary)]">{step.output_summary}</p>
        </li>
      ))}
    </ol>
  );
}
