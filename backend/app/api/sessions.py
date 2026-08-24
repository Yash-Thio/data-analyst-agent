import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.session_manager import session_manager
from app.storage.local import storage

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Long enough not to interrupt a slow model, short enough to keep proxies from
# closing an idle connection.
HEARTBEAT_SECONDS = 15.0
TERMINAL_EVENTS = ("done", "error")


class CreateSessionRequest(BaseModel):
    dataset_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
    dataset_id: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
    if not storage.dataset_exists(body.dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    session_id = session_manager.create_session(body.dataset_id)
    return CreateSessionResponse(session_id=session_id, dataset_id=body.dataset_id)


@router.post("/{session_id}/ask")
async def ask_question(session_id: str, body: AskRequest) -> dict[str, str]:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] == "running":
        raise HTTPException(status_code=409, detail="Analysis already running")
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty")

    session_manager.start_analysis(session_id, body.question)
    return {"status": "started", "session_id": session_id}


@router.post("/{session_id}/cancel")
async def cancel_analysis(session_id: str) -> dict[str, Any]:
    if not session_manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"cancelled": session_manager.cancel(session_id), "session_id": session_id}


@router.get("/{session_id}/stream")
async def stream_events(session_id: str, request: Request) -> EventSourceResponse:
    if not session_manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    queue = session_manager.get_queue(session_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Event stream not found")

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # Keep the connection alive, but do not wait forever on a run
                # that has already finished or died.
                yield {"event": "ping", "data": "{}"}
                session = session_manager.get_session(session_id)
                if session and session.get("status") not in ("running", "idle"):
                    yield _terminal_event(session)
                    break
                continue

            yield {"event": event.get("type", "message"), "data": json.dumps(event, default=str)}
            if event.get("type") in TERMINAL_EVENTS:
                break

    return EventSourceResponse(event_generator())


def _terminal_event(session: dict[str, Any]) -> dict[str, str]:
    """Close the stream cleanly when the run ended without a final event."""
    if session.get("status") == "error":
        payload = {"type": "error", "message": session.get("error") or "Analysis failed"}
    else:
        payload = {"type": "done", "session_id": session["session_id"]}
    return {"event": payload["type"], "data": json.dumps(payload)}


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "dataset_id": session["dataset_id"],
        "status": session["status"],
        "question": session.get("question"),
        "state": session.get("state"),
        "explanation": storage.load_artifact(session_id, "explanation.json"),
        "charts": storage.load_artifact(session_id, "charts.json"),
        "error": session.get("error"),
    }
