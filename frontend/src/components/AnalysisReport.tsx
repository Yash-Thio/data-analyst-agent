"use client";

import type { Claim, ClaimCheck, Evidence, Explanation } from "@/lib/api";

type Props = {
  explanation: Explanation;
  selectedEvidenceId: string | null;
  onSelectClaim: (claim: Claim) => void;
  onSelectEvidence: (evidence: Evidence) => void;
};

const CHECK_STYLES: Record<ClaimCheck["status"], string> = {
  verified: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
  unverified: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
  rejected: "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300",
};

const CHECK_LABELS: Record<ClaimCheck["status"], string> = {
  verified: "checked",
  unverified: "unverified figures",
  rejected: "unsupported",
};

export function AnalysisReport({
  explanation,
  selectedEvidenceId,
  onSelectClaim,
  onSelectEvidence,
}: Props) {
  const checks = new Map((explanation.checks ?? []).map((c) => [c.claim_id, c]));

  return (
    <div className="space-y-4 rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
      {explanation.degraded && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          Partial answer — some steps could not be completed. See the limitations below for what is
          missing.
        </p>
      )}

      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Summary</h3>
        <p className="mt-2 text-base leading-relaxed text-zinc-900 dark:text-zinc-100">
          {explanation.summary}
        </p>
      </div>

      {explanation.claims.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Claims</h3>
          <ul className="mt-2 space-y-2">
            {explanation.claims.map((claim) => {
              const check = checks.get(claim.id);
              return (
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
                    {check && (
                      <span
                        title={check.detail}
                        className={`ml-1 rounded px-1.5 py-0.5 text-[10px] uppercase ${CHECK_STYLES[check.status]}`}
                      >
                        {CHECK_LABELS[check.status]}
                      </span>
                    )}
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
              );
            })}
          </ul>
        </div>
      )}

      {explanation.limitations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Caveats and limitations
          </h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-600 dark:text-zinc-400">
            {explanation.limitations.map((limitation, i) => (
              <li key={i}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
