import asyncio
from typing import Any

from app.agent.graph import agent_graph
from app.agent.state import AgentState
from app.storage.local import storage


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._event_queues: dict[str, asyncio.Queue] = {}
        self._running: dict[str, asyncio.Task] = {}

    def create_session(self, dataset_id: str) -> str:
        session_id = storage.new_id()
        self._sessions[session_id] = {
            "session_id": session_id,
            "dataset_id": dataset_id,
            "status": "idle",
            "question": None,
            "state": None,
        }
        self._event_queues[session_id] = asyncio.Queue()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def get_queue(self, session_id: str) -> asyncio.Queue | None:
        return self._event_queues.get(session_id)

    async def run_analysis(self, session_id: str, question: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return

        queue = self._event_queues.setdefault(session_id, asyncio.Queue())

        dataset_id = session["dataset_id"]
        csv_path = storage.dataset_csv_path(dataset_id)
        profile = storage.load_profile(dataset_id)

        if not profile or not csv_path.exists():
            await queue.put({"type": "error", "message": "Dataset not found"})
            return

        initial_state: AgentState = {
            "dataset_id": dataset_id,
            "session_id": session_id,
            "question": question,
            "csv_path": str(csv_path),
            "schema_profile": profile,
            "findings": [],
            "charts": [],
            "reasoning_trace": [],
            "events": [],
            "current_step_index": 0,
            "status": "running",
        }

        session["question"] = question
        session["status"] = "running"
        emitted = 0

        try:
            final_state: dict[str, Any] = dict(initial_state)
            async for update in agent_graph.astream(initial_state, stream_mode="updates"):
                for _node, node_state in update.items():
                    if not isinstance(node_state, dict):
                        continue
                    final_state.update(node_state)
                    events = node_state.get("events")
                    if events:
                        for event in events[emitted:]:
                            await queue.put(event)
                        emitted = len(events)

            # Ensure terminal event
            last_events = final_state.get("events") or []
            if not any(e.get("type") in ("done", "error") for e in last_events):
                await queue.put({"type": "done", "session_id": session_id})

            session["state"] = _serialize_state(final_state)
            session["status"] = "done"

            if explanation := final_state.get("explanation"):
                payload = explanation.model_dump() if hasattr(explanation, "model_dump") else explanation
                storage.save_artifact(session_id, "explanation.json", payload)
                md = explanation.markdown if hasattr(explanation, "markdown") else payload.get("markdown", "")
                storage.save_artifact(session_id, "report.md", md)
            if charts := final_state.get("charts"):
                storage.save_artifact(
                    session_id,
                    "charts.json",
                    [c.model_dump() if hasattr(c, "model_dump") else c for c in charts],
                )
        except Exception as e:
            session["status"] = "error"
            session["error"] = str(e)
            await queue.put({"type": "error", "message": str(e)})

    def start_analysis(self, session_id: str, question: str) -> None:
        if session_id not in self._event_queues:
            self._event_queues[session_id] = asyncio.Queue()
        task = asyncio.create_task(self._delayed_run(session_id, question))
        self._running[session_id] = task

    async def _delayed_run(self, session_id: str, question: str) -> None:
        # Brief delay so EventSource can subscribe before events start
        await asyncio.sleep(0.4)
        await self.run_analysis(session_id, question)


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, val in state.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "model_dump"):
            result[key] = val.model_dump()
        elif isinstance(val, list):
            result[key] = [
                item.model_dump() if hasattr(item, "model_dump") else item for item in val
            ]
        else:
            result[key] = val
    return result


session_manager = SessionManager()
