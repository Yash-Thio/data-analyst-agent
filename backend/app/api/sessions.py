import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.services.session_manager import session_manager
from app.storage.local import storage

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    dataset_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
    dataset_id: str


class AskRequest(BaseModel):
    question: str


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

    session_manager.start_analysis(session_id, body.question)
    return {"status": "started", "session_id": session_id}


@router.get("/{session_id}/stream")
async def stream_events(session_id: str) -> EventSourceResponse:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    queue = session_manager.get_queue(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Event stream not found")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=120.0)
                yield {"event": event.get("type", "message"), "data": json.dumps(event, default=str)}
                if event.get("type") in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                sess = session_manager.get_session(session_id)
                if sess and sess.get("status") != "running":
                    break

    return EventSourceResponse(event_generator())


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    explanation = storage.load_artifact(session_id, "explanation.json")
    charts = storage.load_artifact(session_id, "charts.json")

    return {
        "session_id": session_id,
        "dataset_id": session["dataset_id"],
        "status": session["status"],
        "question": session.get("question"),
        "state": session.get("state"),
        "explanation": explanation,
        "charts": charts,
        "error": session.get("error"),
    }
