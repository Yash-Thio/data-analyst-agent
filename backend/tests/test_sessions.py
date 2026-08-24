"""Session lifecycle and event streaming."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_manager import SessionManager, _has_terminal_event


@pytest.fixture
def client(sales_csv):
    return TestClient(app)


@pytest.fixture
def dataset_id(client, sales_csv) -> str:
    with sales_csv.open("rb") as f:
        response = client.post("/datasets", files={"file": ("sales.csv", f, "text/csv")})
    return response.json()["dataset_id"]


def test_session_requires_a_real_dataset(client) -> None:
    assert client.post("/sessions", json={"dataset_id": "nope"}).status_code == 404


def test_streaming_unknown_session_is_not_found(client) -> None:
    assert client.get("/sessions/nope/stream").status_code == 404


def test_empty_question_is_rejected(client, dataset_id) -> None:
    session_id = client.post("/sessions", json={"dataset_id": dataset_id}).json()["session_id"]
    assert client.post(f"/sessions/{session_id}/ask", json={"question": "   "}).status_code == 422
    assert client.post(f"/sessions/{session_id}/ask", json={"question": ""}).status_code == 422


def test_cancelling_an_idle_session_is_harmless(client, dataset_id) -> None:
    session_id = client.post("/sessions", json={"dataset_id": dataset_id}).json()["session_id"]
    response = client.post(f"/sessions/{session_id}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelled"] is False


def test_old_sessions_are_evicted() -> None:
    """The store must not grow without bound."""
    manager = SessionManager(max_sessions=3)
    ids = [manager.create_session("d") for _ in range(5)]

    assert manager.get_session(ids[0]) is None
    assert manager.get_session(ids[-1]) is not None
    assert len(manager._sessions) == 3


def test_recently_used_sessions_survive_eviction() -> None:
    manager = SessionManager(max_sessions=3)
    ids = [manager.create_session("d") for _ in range(3)]

    manager.get_session(ids[0])
    manager.create_session("d")

    assert manager.get_session(ids[0]) is not None
    assert manager.get_session(ids[1]) is None


@pytest.mark.asyncio
async def test_a_missing_dataset_still_terminates_the_stream() -> None:
    """Whatever goes wrong, the browser must receive a terminal event."""
    manager = SessionManager()
    session_id = manager.create_session("does-not-exist")

    await manager.run_analysis(session_id, "anything?")

    queue = manager.get_queue(session_id)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[-1]["type"] == "error"
    assert manager.get_session(session_id)["status"] == "error"


@pytest.mark.asyncio
async def test_failures_are_reported_rather_than_swallowed(monkeypatch) -> None:
    manager = SessionManager()
    session_id = manager.create_session("d")

    async def boom(*_args, **_kwargs):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(manager, "run_analysis", boom)
    manager.start_analysis(session_id, "why?")
    await asyncio.sleep(0.6)

    queue = manager.get_queue(session_id)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[-1]["type"] == "error"
    assert "graph exploded" in events[-1]["message"]


@pytest.mark.asyncio
async def test_cancellation_stops_the_run_and_closes_the_stream() -> None:
    manager = SessionManager()
    session_id = manager.create_session("d")

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(30)

    manager.run_analysis = slow  # type: ignore[method-assign]
    manager.start_analysis(session_id, "why?")
    await asyncio.sleep(0.1)

    assert manager.cancel(session_id) is True
    await asyncio.sleep(0.1)

    queue = manager.get_queue(session_id)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[-1]["type"] == "error"
    assert manager.get_session(session_id)["status"] == "cancelled"


def test_recoverable_errors_do_not_look_terminal() -> None:
    """`step_error` keeps the stream open; `error` closes it."""
    assert not _has_terminal_event([{"type": "step_error"}, {"type": "warning"}])
    assert _has_terminal_event([{"type": "step_error"}, {"type": "done"}])
    assert _has_terminal_event([{"type": "error"}])


@pytest.mark.asyncio
async def test_a_full_queue_never_blocks_the_analysis() -> None:
    manager = SessionManager()
    session_id = manager.create_session("d")
    queue = manager.get_queue(session_id)
    for _ in range(queue.maxsize):
        queue.put_nowait({"type": "filler"})

    await asyncio.wait_for(manager._emit(session_id, {"type": "done"}), timeout=1)
