"use client";

import type { Claim, ClaimCheck, Evidence, Explanation } from "@/lib/api";

type Props = {
  explanation: Explanation;
  selectedEvidenceId: string | null;
  onSelectClaim: (claim: Claim) => void;
  onSelectEvidence: (evidence: Evidence) => void;
};

const CHECK_STYLES: Record<ClaimCheck["status"], string> = {
  verified: "bg-[var(--success-fill)] text-[var(--success)]",
  unverified: "bg-[var(--warning-fill)] text-[var(--warning)]",
  rejected: "bg-[var(--danger-fill)] text-[var(--danger)]",
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
    <div className="space-y-4">
      {explanation.degraded && (
        <p className="banner banner-warn">
          Partial answer — some steps could not be completed. See the limitations below for what is
          missing.
        </p>
      )}

      <div>
        <h3 className="section-title">Summary</h3>
        <p className="summary-copy mt-2">{explanation.summary}</p>
      </div>

      {explanation.claims.length > 0 && (
        <div>
          <h3 className="section-title">Claims</h3>
          <ul className="mt-2 divide-y divide-[var(--separator)]">
            {explanation.claims.map((claim) => {
              const check = checks.get(claim.id);
              return (
                <li key={claim.id}>
                  <button
                    type="button"
                    onClick={() => onSelectClaim(claim)}
                    className="w-full rounded-xl px-0 py-2.5 text-left text-sm transition-[transform] duration-100 active:scale-[0.99] hover:text-[var(--accent)]"
                  >
                    <span className="mr-2 font-mono text-xs text-[var(--accent)]">[{claim.id}]</span>
                    {claim.text}
                    <span className="ml-2 rounded-full bg-[var(--separator)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--label-secondary)]">
                      {claim.confidence}
                    </span>
                    {check && (
                      <span
                        title={check.detail}
                        className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] uppercase ${CHECK_STYLES[check.status]}`}
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
                          className={`cursor-pointer rounded-full px-1.5 py-0.5 font-mono text-[10px] ${
                            selectedEvidenceId === eid
                              ? "bg-[var(--accent)] text-white"
                              : "bg-[var(--accent-fill)] text-[var(--accent)]"
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
          <h3 className="section-title">Caveats and limitations</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--label-secondary)]">
            {explanation.limitations.map((limitation, i) => (
              <li key={i}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
