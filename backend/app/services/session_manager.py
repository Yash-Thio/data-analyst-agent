"""Runs analyses and fans agent events out to SSE subscribers.

Three things this has to get right:

* a stream always terminates - every run ends in exactly one `done` or `error`,
  so the browser never hangs waiting
* events are emitted once - nodes carry the full accumulated list in state, so
  only the newly appended tail is forwarded
* nothing grows without bound - sessions are evicted, and a run can be cancelled
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any

from app.agent.graph import agent_graph
from app.agent.state import AgentState
from app.storage.local import storage

logger = logging.getLogger(__name__)

MAX_SESSIONS = 200
QUEUE_MAXSIZE = 1000
RECURSION_LIMIT = 60
SUBSCRIBE_GRACE_SECONDS = 0.4


class SessionManager:
    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._sessions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._queues: dict[str, asyncio.Queue] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._max_sessions = max_sessions

    # -- lifecycle ---------------------------------------------------------

    def create_session(self, dataset_id: str) -> str:
        session_id = storage.new_id()
        self._sessions[session_id] = {
            "session_id": session_id,
            "dataset_id": dataset_id,
            "status": "idle",
            "question": None,
            "state": None,
            "error": None,
        }
        self._queues[session_id] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._evict_old_sessions()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions.move_to_end(session_id)
        return session

    def get_queue(self, session_id: str) -> asyncio.Queue | None:
        return self._queues.get(session_id)

    def start_analysis(self, session_id: str, question: str) -> None:
        self.cancel(session_id)
        self._queues.setdefault(session_id, asyncio.Queue(maxsize=QUEUE_MAXSIZE))
        self._tasks[session_id] = asyncio.create_task(self._run_guarded(session_id, question))

    def cancel(self, session_id: str) -> bool:
        task = self._tasks.pop(session_id, None)
        if task is None or task.done():
            return False
        task.cancel()
        if session := self._sessions.get(session_id):
            session["status"] = "cancelled"
        return True

    def _evict_old_sessions(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest, _ = self._sessions.popitem(last=False)
            self._queues.pop(oldest, None)
            task = self._tasks.pop(oldest, None)
            if task and not task.done():
                task.cancel()

    # -- execution ---------------------------------------------------------

    async def _run_guarded(self, session_id: str, question: str) -> None:
        """Guarantees the stream is closed however the run ends."""
        # A brief pause lets the browser's EventSource attach before the first
        # event is produced; without it early events are lost.
        try:
            await asyncio.sleep(SUBSCRIBE_GRACE_SECONDS)
            await self.run_analysis(session_id, question)
        except asyncio.CancelledError:
            await self._emit(session_id, {"type": "error", "message": "Analysis cancelled."})
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("session %s failed", session_id)
            self._fail(session_id, str(exc))
            await self._emit(
                session_id, {"type": "error", "message": f"Analysis failed: {exc}"}
            )

    async def run_analysis(self, session_id: str, question: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return

        csv_path = storage.dataset_csv_path(session["dataset_id"])
        profile = storage.load_profile(session["dataset_id"])
        if not profile or not csv_path.exists():
            self._fail(session_id, "Dataset not found")
            await self._emit(session_id, {"type": "error", "message": "Dataset not found"})
            return

        session.update({"question": question, "status": "running", "error": None})

        initial: AgentState = {
            "dataset_id": session["dataset_id"],
            "session_id": session_id,
            "question": question,
            "csv_path": str(csv_path),
            "schema_profile": profile,
            "findings": [],
            "charts": [],
            "reasoning_trace": [],
            "events": [],
            "node_errors": [],
            "current_step_index": 0,
            "replans": 0,
            "status": "running",
        }

        final: dict[str, Any] = dict(initial)
        emitted = 0

        async for update in agent_graph.astream(
            initial, {"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"
        ):
            for _node, node_state in update.items():
                if not isinstance(node_state, dict):
                    continue
                final.update(node_state)
                # Nodes return the whole accumulated list; forward only the tail.
                events = node_state.get("events")
                if events and len(events) > emitted:
                    for event in events[emitted:]:
                        await self._emit(session_id, event)
                    emitted = len(events)

        session["state"] = _serialize(final)
        session["status"] = final.get("status", "done")
        self._persist(session_id, final)

        if not _has_terminal_event(final.get("events") or []):
            await self._emit(session_id, {"type": "done", "session_id": session_id})

    # -- helpers -----------------------------------------------------------

    async def _emit(self, session_id: str, event: dict[str, Any]) -> None:
        queue = self._queues.get(session_id)
        if queue is None:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # A subscriber that cannot keep up must not stall the analysis.
            logger.warning("event queue full for session %s; dropping event", session_id)

    def _fail(self, session_id: str, message: str) -> None:
        if session := self._sessions.get(session_id):
            session["status"] = "error"
            session["error"] = message

    def _persist(self, session_id: str, final: dict[str, Any]) -> None:
        try:
            if explanation := final.get("explanation"):
                payload = (
                    explanation.model_dump()
                    if hasattr(explanation, "model_dump")
                    else explanation
                )
                storage.save_artifact(session_id, "explanation.json", payload)
                storage.save_artifact(session_id, "report.md", payload.get("markdown", ""))
            if charts := final.get("charts"):
                storage.save_artifact(
                    session_id,
                    "charts.json",
                    [c.model_dump() if hasattr(c, "model_dump") else c for c in charts],
                )
        except Exception:  # noqa: BLE001
            # Persistence is a convenience; the answer is already streamed.
            logger.exception("failed to persist artifacts for session %s", session_id)


def _has_terminal_event(events: list[dict[str, Any]]) -> bool:
    return any(e.get("type") in ("done", "error") for e in events)


def _serialize(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in state.items():
        if hasattr(value, "model_dump"):
            result[key] = value.model_dump()
        elif isinstance(value, list):
            result[key] = [
                item.model_dump() if hasattr(item, "model_dump") else item for item in value
            ]
        else:
            result[key] = value
    return result


session_manager = SessionManager()
