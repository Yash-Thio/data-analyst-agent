"""Checks a report's claims against the evidence it cites.

Structured output guarantees a claim *names* an evidence id. It does not
guarantee the number in the sentence came from that evidence - and a plausible
wrong number is the most damaging thing this system can produce.

So every number in a claim is matched against the values its evidence actually
returned. Unmatched numbers do not silently pass: the claim is downgraded or
dropped, and the report says why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.models.explanation import Claim, ClaimCheck, Evidence

# Tolerance covers honest rounding ("18.2%" from 18.23), not different numbers.
RELATIVE_TOLERANCE = 0.02
ABSOLUTE_TOLERANCE = 0.51
# Rescaled forms ("1.21 million" from 1,207,500) get a much tighter band: at
# thousands scale a 2% window is wide enough to swallow unrelated figures -
# 42.7 would otherwise "match" 43,125.
SCALED_RELATIVE_TOLERANCE = 0.005

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# Years, ordinals and quarters are labels, not measurements.
_SKIP_CONTEXT = re.compile(
    r"(?:^|\s)(?:Q[1-4]|H[12]|FY)\s*$|(?:19|20)\d{2}", re.IGNORECASE
)


@dataclass
class VerificationReport:
    checks: list[ClaimCheck] = field(default_factory=list)
    kept: list[Claim] = field(default_factory=list)
    dropped: list[Claim] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        return all(c.status == "verified" for c in self.checks)


def extract_numbers(text: str) -> list[float]:
    """Numbers a claim asserts, excluding things that are obviously labels."""
    found: list[float] = []
    for match in _NUMBER.finditer(text):
        raw = match.group(0)
        cleaned = raw.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        # A bare four-digit year is a period label, not a measurement.
        if "." not in cleaned and 1900 <= abs(value) <= 2100 and len(cleaned.lstrip("-")) == 4:
            continue
        found.append(value)
    return found


def evidence_numbers(evidence: Evidence) -> tuple[set[float], set[float]]:
    """Numbers the evidence contains, split into direct and rescaled forms."""
    direct: set[float] = set()

    for value in evidence.metrics.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            direct.add(float(value))

    for row in evidence.result_preview:
        for value in row.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                direct.add(float(value))

    # Claims routinely quote the magnitude rather than the signed figure.
    direct |= {abs(value) for value in direct}
    # ... and often express large numbers in thousands or millions.
    scaled = {value / 1000 for value in direct} | {value / 1_000_000 for value in direct}
    return direct, scaled


def matches(target: float, direct: set[float], scaled: set[float]) -> bool:
    return _close(target, direct, RELATIVE_TOLERANCE, ABSOLUTE_TOLERANCE) or _close(
        target, scaled, SCALED_RELATIVE_TOLERANCE, 0.0
    )


def _close(target: float, candidates: set[float], relative: float, absolute: float) -> bool:
    for candidate in candidates:
        if absolute and abs(target - candidate) <= absolute:
            return True
        scale = max(abs(target), abs(candidate))
        if scale and abs(target - candidate) / scale <= relative:
            return True
    return False


def verify_claims(claims: list[Claim], evidence: list[Evidence]) -> VerificationReport:
    by_id = {e.id: e for e in evidence}
    report = VerificationReport()

    for claim in claims:
        cited = [by_id[eid] for eid in claim.evidence_ids if eid in by_id]

        if not cited:
            report.checks.append(
                ClaimCheck(
                    claim_id=claim.id,
                    status="rejected",
                    detail="Cites no evidence that exists.",
                )
            )
            report.dropped.append(claim)
            continue

        if all(not e.result_preview and not e.metrics for e in cited):
            report.checks.append(
                ClaimCheck(
                    claim_id=claim.id,
                    status="rejected",
                    detail="Every cited query returned no rows.",
                )
            )
            report.dropped.append(claim)
            continue

        direct: set[float] = set()
        scaled: set[float] = set()
        for item in cited:
            item_direct, item_scaled = evidence_numbers(item)
            direct |= item_direct
            scaled |= item_scaled

        asserted = extract_numbers(claim.text)
        unmatched = [n for n in asserted if not matches(n, direct, scaled)]

        if not asserted:
            report.checks.append(
                ClaimCheck(
                    claim_id=claim.id,
                    status="verified",
                    detail="Qualitative claim; no figures to check.",
                )
            )
            report.kept.append(claim)
        elif unmatched:
            report.checks.append(
                ClaimCheck(
                    claim_id=claim.id,
                    status="unverified",
                    detail=(
                        "These figures do not appear in the cited evidence: "
                        + ", ".join(_format(n) for n in unmatched)
                    ),
                    unmatched_numbers=unmatched,
                )
            )
            # Kept but demoted: the reader sees the caveat rather than losing
            # a claim that may still be directionally right.
            report.kept.append(claim.model_copy(update={"confidence": "low"}))
            report.notes.append(
                f"Claim {claim.id} quotes figures that could not be traced to its "
                f"evidence ({', '.join(_format(n) for n in unmatched)}); treat with caution."
            )
        else:
            report.checks.append(
                ClaimCheck(
                    claim_id=claim.id,
                    status="verified",
                    detail=f"All {len(asserted)} figure(s) match the cited evidence.",
                )
            )
            report.kept.append(claim)

    for claim in report.dropped:
        report.notes.append(
            f"A claim was removed because it was not supported by any evidence: "
            f'"{_shorten(claim.text)}"'
        )
    return report


def _format(value: float) -> str:
    return f"{value:g}"


def _shorten(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
