"""Offline validation of the natural-language question bank.

Keeps `tests/eval/questions.yaml` honest: every dataset must exist and every
column an expectation names must really be queryable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.data.profiler import profile_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_INTENTS = {
    "aggregate",
    "comparison",
    "trend",
    "ranking",
    "distribution",
    "correlation",
    "root_cause",
    "lookup",
    "summary",
}


def test_every_dataset_file_exists(question_bank: dict[str, Any]) -> None:
    for name, spec in question_bank["datasets"].items():
        assert (REPO_ROOT / spec["file"]).exists(), f"{name}: {spec['file']}"


def test_question_ids_are_unique(question_bank: dict[str, Any]) -> None:
    ids = [q["id"] for q in question_bank["questions"]]
    assert len(ids) == len(set(ids))


def test_questions_are_well_formed(question_bank: dict[str, Any]) -> None:
    datasets = set(question_bank["datasets"])
    for q in question_bank["questions"]:
        assert q["dataset"] in datasets, q["id"]
        assert q["question"].strip(), q["id"]
        expect = q["expect"]
        for intent in expect.get("intents", []):
            assert intent in VALID_INTENTS, f"{q['id']}: {intent}"


def test_bank_covers_every_dataset(question_bank: dict[str, Any]) -> None:
    used = {q["dataset"] for q in question_bank["questions"]}
    assert used == set(question_bank["datasets"])


def test_bank_includes_unanswerable_questions(question_bank: dict[str, Any]) -> None:
    unanswerable = [
        q for q in question_bank["questions"] if q["expect"].get("answerable") is False
    ]
    assert len(unanswerable) >= 2


@pytest.fixture(scope="session")
def dataset_columns(question_bank: dict[str, Any]) -> dict[str, set[str]]:
    """Every column name the agent could legitimately reference, per dataset."""
    result: dict[str, set[str]] = {}
    for name, spec in question_bank["datasets"].items():
        profile = profile_dataset(Path(REPO_ROOT / spec["file"]))
        names = {c["name"] for c in profile["columns"]}
        if profile.get("wide"):
            names |= {profile["wide"]["period_name"], profile["wide"]["value_name"]}
        result[name] = names
    return result


def test_referenced_columns_exist(
    question_bank: dict[str, Any], dataset_columns: dict[str, set[str]]
) -> None:
    for q in question_bank["questions"]:
        available = dataset_columns[q["dataset"]]
        for col in q["expect"].get("columns_any", []):
            assert col in available, f"{q['id']}: {col!r} not in {sorted(available)}"


def test_forbidden_measures_are_real_columns(
    question_bank: dict[str, Any], dataset_columns: dict[str, set[str]]
) -> None:
    for q in question_bank["questions"]:
        for col in q["expect"].get("forbids_measures", []):
            assert col in dataset_columns[q["dataset"]], f"{q['id']}: {col!r}"
