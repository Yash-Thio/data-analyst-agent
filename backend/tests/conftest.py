from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "sample-data"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
BANK_PATH = Path(__file__).resolve().parent / "eval" / "questions.yaml"

SALES_CSV = SAMPLE_DIR / "sales.csv"
FINANCIAL_CSV = SAMPLE_DIR / "04-01-Financial Sample Data.csv"
UNEMPLOYMENT_CSV = (
    SAMPLE_DIR
    / "2025-01-01 to 2026-06-01 Unemployment Rate by Metropolitan Statistical Area (Percent).csv"
)
CURRENCY_CSV = FIXTURE_DIR / "currency_sales.csv"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: requires a real LLM API key; deselected by default"
    )


class FakeLLM:
    """Stands in for a provider, dispatching on the requested response model.

    Values may be a single object, a list consumed one call at a time, or a
    callable receiving the messages - enough to script retry sequences.
    """

    def __init__(self, **_: Any) -> None:
        self.responses: dict[Any, Any] = {}
        self.calls: list[tuple[Any, str]] = []

    def on(self, response_format: Any, value: Any) -> "FakeLLM":
        self.responses[response_format] = value
        return self

    async def complete(self, messages: list, *, response_format: Any = None) -> Any:
        prompt = "\n".join(getattr(m, "content", "") for m in messages)
        self.calls.append((response_format, prompt))

        handler = self.responses.get(response_format)
        if handler is None:
            return "ok"
        if callable(handler):
            return handler(prompt)
        if isinstance(handler, list):
            return handler.pop(0) if len(handler) > 1 else handler[0]
        return handler

    def prompts_for(self, response_format: Any) -> list[str]:
        return [p for fmt, p in self.calls if fmt is response_format]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


def load_question_bank() -> dict[str, Any]:
    return yaml.safe_load(BANK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def question_bank() -> dict[str, Any]:
    return load_question_bank()


@pytest.fixture
def sales_csv() -> Path:
    return SALES_CSV


@pytest.fixture
def financial_csv() -> Path:
    return FINANCIAL_CSV


@pytest.fixture
def unemployment_csv() -> Path:
    return UNEMPLOYMENT_CSV


@pytest.fixture
def currency_csv() -> Path:
    return CURRENCY_CSV


@pytest.fixture
def sales_profile(sales_csv: Path) -> dict[str, Any]:
    from app.data.profiler import profile_dataset

    return profile_dataset(sales_csv)


@pytest.fixture(scope="session")
def financial_profile() -> dict[str, Any]:
    from app.data.profiler import profile_dataset

    return profile_dataset(FINANCIAL_CSV)


@pytest.fixture(scope="session")
def unemployment_profile() -> dict[str, Any]:
    from app.data.profiler import profile_dataset

    return profile_dataset(UNEMPLOYMENT_CSV)
