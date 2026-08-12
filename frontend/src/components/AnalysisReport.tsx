"use client";

import type { Claim, Evidence, Explanation } from "@/lib/api";

type Props = {
  explanation: Explanation;
  selectedEvidenceId: string | null;
  onSelectClaim: (claim: Claim) => void;
  onSelectEvidence: (evidence: Evidence) => void;
};

export function AnalysisReport({
  explanation,
  selectedEvidenceId,
  onSelectClaim,
  onSelectEvidence,
}: Props) {
  return (
    <div className="space-y-4 rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Summary</h3>
        <p className="mt-2 text-base leading-relaxed text-zinc-900 dark:text-zinc-100">
          {explanation.summary}
        </p>
      </div>

      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Claims</h3>
        <ul className="mt-2 space-y-2">
          {explanation.claims.map((claim) => (
            <li key={claim.id}>
              <button
                type="button"
                onClick={() => onSelectClaim(claim)}
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-left text-sm hover:border-indigo-400 hover:bg-indigo-50 dark:border-zinc-700 dark:hover:bg-indigo-950/40"
              >
                <span className="mr-2 font-mono text-xs text-indigo-600">[{claim.id}]</span>
                {claim.text}
                <span className="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] uppercase text-zinc-500 dark:bg-zinc-800">
                  {claim.confidence}
                </span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {claim.evidence_ids.map((eid) => (
                    <span
                      key={eid}
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        const ev = explanation.evidence.find((x) => x.id === eid);
                        if (ev) onSelectEvidence(ev);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          const ev = explanation.evidence.find((x) => x.id === eid);
                          if (ev) onSelectEvidence(ev);
                        }
                      }}
                      className={`cursor-pointer rounded px-1.5 py-0.5 font-mono text-[10px] ${
                        selectedEvidenceId === eid
                          ? "bg-indigo-600 text-white"
                          : "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200"
                      }`}
                    >
                      {eid}
                    </span>
                  ))}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {explanation.limitations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Limitations</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-600 dark:text-zinc-400">
            {explanation.limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
