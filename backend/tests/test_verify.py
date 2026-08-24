"""Claims are checked against the numbers their own evidence returned."""

from __future__ import annotations

from app.agent.models.explanation import Claim, Evidence
from app.agent.verify import extract_numbers, verify_claims


def evidence(
    eid: str = "ev-1",
    metrics: dict | None = None,
    rows: list[dict] | None = None,
) -> Evidence:
    return Evidence(
        id=eid,
        finding_id="f-1",
        sql="SELECT 1",
        result_preview=rows if rows is not None else [{"region": "APAC", "total": 43125.0}],
        metrics=metrics if metrics is not None else {"delta_pct": -18.2},
    )


def claim(text: str, ids: list[str] | None = None, cid: str = "c-1") -> Claim:
    return Claim(id=cid, text=text, evidence_ids=ids or ["ev-1"], confidence="high")


def test_years_are_not_treated_as_measurements() -> None:
    assert extract_numbers("Revenue fell in 2014") == []
    assert extract_numbers("Revenue fell 18.2% in 2014") == [18.2]


def test_thousands_separators_are_parsed() -> None:
    assert extract_numbers("Sales were 43,125 in total") == [43125.0]


def test_matching_figures_verify() -> None:
    report = verify_claims([claim("Revenue fell 18.2%")], [evidence()])
    assert report.checks[0].status == "verified"
    assert report.kept and not report.dropped


def test_rounding_is_tolerated() -> None:
    report = verify_claims(
        [claim("Revenue fell about 18%")],
        [evidence(metrics={"delta_pct": -18.23})],
    )
    assert report.checks[0].status == "verified"


def test_figures_can_come_from_result_rows() -> None:
    report = verify_claims(
        [claim("APAC contributed 43,125")],
        [evidence(metrics={}, rows=[{"region": "APAC", "total": 43125.0}])],
    )
    assert report.checks[0].status == "verified"


def test_invented_figures_are_flagged_and_demoted() -> None:
    """The failure mode that matters: a plausible number that is not in the data."""
    report = verify_claims([claim("Revenue fell 42.7%")], [evidence()])

    check = report.checks[0]
    assert check.status == "unverified"
    assert check.unmatched_numbers == [42.7]
    assert report.kept[0].confidence == "low"
    assert any("42.7" in note for note in report.notes)


def test_qualitative_claims_pass() -> None:
    report = verify_claims([claim("Revenue declined across every region")], [evidence()])
    assert report.checks[0].status == "verified"


def test_claims_citing_unknown_evidence_are_dropped() -> None:
    report = verify_claims([claim("Revenue fell", ids=["ev-99"])], [evidence()])
    assert report.checks[0].status == "rejected"
    assert report.dropped and not report.kept


def test_claims_backed_only_by_empty_results_are_dropped() -> None:
    empty = Evidence(id="ev-1", finding_id="f-1", sql="SELECT 1", result_preview=[], metrics={})
    report = verify_claims([claim("Revenue fell 18%")], [empty])

    assert report.checks[0].status == "rejected"
    assert not report.kept
    assert any("not supported" in note for note in report.notes)


def test_scaled_figures_are_recognised() -> None:
    """"$1.2 million" against a raw 1,207,500."""
    report = verify_claims(
        [claim("Gross sales reached 1.21 million")],
        [evidence(metrics={"gross": 1_207_500.0})],
    )
    assert report.checks[0].status == "verified"


def test_mixed_report_keeps_verified_and_demotes_the_rest() -> None:
    report = verify_claims(
        [claim("Revenue fell 18.2%", cid="c-1"), claim("Costs rose 99.9%", cid="c-2")],
        [evidence()],
    )
    statuses = {c.claim_id: c.status for c in report.checks}
    assert statuses == {"c-1": "verified", "c-2": "unverified"}
    assert len(report.kept) == 2
