"""Voz Navega — FastAPI backend.

A simulated Alexa+ voice-companion experience in a web app: a
fictional patient talks (browser speech), and the companion answers
out loud and in the transcript. This module is the HTTP surface and
the server-side gate enforcement (ARCHITECTURE.md §2.2, §3.3);
content and turn decisions live in app/brain_demo.py, storage in
app/store.py, and the turn flow itself in app/flow.py — the ONE
door into the engine, shared with the MCP front door mounted at
/mcp (app/mcp_server.py, MCP spec 2025-11-25 over Streamable HTTP).

THE FLOW, on every patient turn, in this order:
  1. safety.gate.evaluate_turn classifies the raw turn
     (crisis > medical_advice > sensitive > routine). An escalated
     turn composes NOTHING — the response is the gate's fixed line,
     the red banner for crisis, draft=None, and the session is
     ESCALATED for good.
  2. Only a routine turn reaches the demo brain, which advances the
     conversation state machine (GREETING → … → HANDOFF).

THE GATE, enforced here and never only in the UI (Podrá's 409
pattern): the handoff summary is a draft until a human navigator
approves it. Approve is 409 when the session is ESCALATED, 409 when
it is not PENDING_APPROVAL, and 409 while any offered resource is
unverified. Resource verification is a navigator attestation click
in this demo directory, and is labeled as such on the record.

Run from the repo root:  uvicorn app.main:app
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# The safety package lives at the repo root (sibling of app/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from . import brain_demo as brain  # noqa: E402
from . import flow  # noqa: E402
from .flow import run_patient_turn as _run_patient_turn  # noqa: E402
from .flow import store  # noqa: E402
from .mcp_server import build_mcp_http_app, mcp  # noqa: E402

DEFAULT_NAVIGATOR = "Human navigator (demo)"

# The MCP front door's ASGI app (Streamable HTTP). Built before the
# FastAPI app because the app's lifespan must run its session
# manager (below).
_mcp_http_app = build_mcp_http_app()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # A mounted sub-app's own lifespan is not run by the parent, so
    # the parent runs the MCP session manager for the whole process:
    # without this, /mcp raises "Task group is not initialized".
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Voz Navega",
    description="Voice-first companion that helps a fictional patient "
                "prepare for a doctor visit. Simulated Alexa+ experience "
                "in a web app. Demo only — not a medical service.",
    version="0.3.0",
    lifespan=_lifespan,
)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_view(session: dict) -> dict:
    """The navigator-facing session record: everything except the
    brain's private scratch keys (``_first_patient_turn``)."""
    view = {k: v for k, v in session.items() if not k.startswith("_")}
    view["escalated"] = session.get("state") == "ESCALATED"
    return view


def _queue_entry(session: dict) -> dict:
    return {
        "id": session["id"],
        "state": session["state"],
        "language": session.get("language"),
        "approval_status": session.get("approval_status"),
        "barriers_found": [dict(b) for b in
                           session.get("barriers_found", [])],
        "barrier_checklist": dict(session.get("barrier_checklist") or {}),
        "escalated": session.get("state") == "ESCALATED",
        "escalated_category": session.get("escalated_category"),
        "turns_count": len(session.get("turns", [])),
        "fictional": True,
    }


# ---------------------------------------------------------------------------
# Seed: ONE pre-computed golden session (Golden A, ARCHITECTURE.md §1.3),
# replayed through the same gate + brain flow as a live conversation, so
# the demo and the navigator panel hold a case at HANDOFF from first boot.
# ---------------------------------------------------------------------------

_GOLDEN_A_LINES = [
    "They told me I need a biopsy on Tuesday and I'm scared. "
    "I don't really know what it is.",
    "Getting there. My daughter works, and I don't drive. And I watch "
    "my grandkids in the mornings — who watches them?",
    "Keep going. Will it hurt?",
    "That's good. Nothing to add.",
]


def _seed_golden_session() -> None:
    try:
        session = brain.new_session(store.next_id())
        brain.greeting_turn(session, "en")
        store.create(session)
        for line in _GOLDEN_A_LINES:
            working = store.get(session["id"])
            _run_patient_turn(working, line)
            store.update(working)
    except Exception as exc:  # noqa: BLE001 — a seed failure must not break boot
        print(f"voz-navega: golden seed failed: {exc!r}", file=sys.stderr)


_seed_golden_session()


# ---------------------------------------------------------------------------
# HTTP surface (ARCHITECTURE.md §2.2)
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "voz-navega",
        "app": "voz-navega",
        "demo_mode": True,
        "live_mode": False,
        "time": _now(),
    }


class SessionIn(BaseModel):
    ui_language: str = "en"


class TurnIn(BaseModel):
    text: str = ""
    session_id: str | None = None


def _create_session(ui_language: str) -> dict:
    return flow.start_session(ui_language)


@app.post("/api/sessions", status_code=201)
@app.post("/api/session", status_code=201)
def create_session(payload: SessionIn | None = None) -> dict:
    session, result = _create_session(
        payload.ui_language if payload else "en")
    return {
        "session_id": session["id"],
        "reply": result["text"],
        "companion_turn": {
            "speaker": "voz",
            "text": result["text"],
            "gloss": result["gloss"],
            "spoken": result["spoken"],
        },
        "state": result["state"],
        "session": _session_view(session),
    }


@app.get("/api/sessions")
def list_sessions() -> dict:
    """Navigator queue — ESCALATED first, then creation order."""
    entries = [_queue_entry(s) for s in store.all()]
    entries.sort(key=lambda e: not e["escalated"])
    return {"sessions": entries}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"session {session_id} not found")
    return _session_view(session)


@app.post("/api/sessions/{session_id}/turns")
def post_turn(session_id: str, payload: TurnIn) -> dict:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"session {session_id} not found")
    response = _run_patient_turn(session, payload.text.strip())
    store.update(session)
    return response


@app.post("/api/turn")
def post_turn_legacy(payload: TurnIn) -> dict:
    """The scaffold's single endpoint, kept for the current frontend:
    with a session_id it is the same flow as
    POST /api/sessions/{id}/turns; without one it starts a session
    (the greeting is the client's to request via POST /api/sessions)
    and returns the new session_id so the conversation can continue.
    """
    if payload.session_id:
        return post_turn(payload.session_id, payload)
    session = brain.new_session(store.next_id())
    store.create(session)
    response = _run_patient_turn(session, payload.text.strip())
    store.update(session)
    return response


# ---------------------------------------------------------------------------
# The navigator gate (ARCHITECTURE.md §3.3) — server-side, always.
# ---------------------------------------------------------------------------


def _require_pending_approval(session: dict, action: str) -> None:
    """The two state-based 409s shared by approve and edit-summary."""
    if session.get("state") == "ESCALATED":
        raise HTTPException(
            status_code=409,
            detail="This case was escalated and is handled by a human "
                   "navigator directly; the system cannot "
                   f"{action} for it.")
    if session.get("approval_status") != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action}: session is in state "
                   f"{session.get('state')} with approval status "
                   f"{session.get('approval_status')}; this requires "
                   "PENDING_APPROVAL.")


class VerifyIn(BaseModel):
    name: str | None = None
    index: int | None = None
    type: str | None = None
    by: str = ""


@app.post("/api/sessions/{session_id}/verify-resource")
def verify_resource(session_id: str, payload: VerifyIn) -> dict:
    """Mark ONE offered resource verified. In this demo directory,
    verification is a navigator attestation click — a human saying
    'I checked this' — and the record says exactly that."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"session {session_id} not found")
    if session.get("approval_status") == "APPROVED_SENT":
        raise HTTPException(
            status_code=409,
            detail="Session already approved and sent; its resources "
                   "can no longer be changed.")
    resources = session.get("resources", [])
    target = None
    if payload.index is not None and 0 <= payload.index < len(resources):
        target = resources[payload.index]
    elif payload.name:
        target = next((r for r in resources
                       if r.get("name") == payload.name), None)
    elif payload.type:
        target = next((r for r in resources
                       if r.get("type") == payload.type), None)
    if target is None:
        raise HTTPException(status_code=404,
                            detail="resource not offered in this session")
    target["verified"] = True
    target["verified_by"] = payload.by or DEFAULT_NAVIGATOR
    target["verified_at"] = _now()
    target["verification"] = "navigator attestation (demo directory)"
    store.update(session)
    return {
        "session_id": session_id,
        "resource": dict(target),
        "resources": [dict(r) for r in resources],
        "all_verified": all(r.get("verified") for r in resources),
    }


class EditSummaryIn(BaseModel):
    text: str
    by: str = ""


@app.post("/api/sessions/{session_id}/edit-summary")
def edit_summary(session_id: str, payload: EditSummaryIn) -> dict:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"session {session_id} not found")
    _require_pending_approval(session, "edit the summary")
    session["summary"]["text"] = payload.text
    session["summary"]["navigator_edited"] = True
    session["summary_edited"] = True
    store.update(session)
    return {
        "session_id": session_id,
        "summary": session["summary"],
        "approval_status": session["approval_status"],
    }


class ApproveIn(BaseModel):
    by: str = ""


@app.post("/api/sessions/{session_id}/approve")
def approve(session_id: str, payload: ApproveIn | None = None) -> dict:
    """The gate. 409 until the session is PENDING_APPROVAL AND every
    offered resource is verified; on success the session becomes
    APPROVED_SENT with the approver recorded."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"session {session_id} not found")
    _require_pending_approval(session, "approve and send")
    unverified = [r["name"] for r in session.get("resources", [])
                  if not r.get("verified")]
    if unverified:
        raise HTTPException(
            status_code=409,
            detail="Cannot approve: unverified resources remain — "
                   + "; ".join(unverified)
                   + ". A navigator must verify each offered resource "
                     "first.")
    summary = session.get("summary") or {}
    session["approval_status"] = "APPROVED_SENT"
    session["approval_record"] = {
        "by": (payload.by if payload else "") or DEFAULT_NAVIGATOR,
        "at": _now(),
        "navigator_edited": bool(session.get("summary_edited")
                                 or summary.get("navigator_edited")),
        "resources_verified": sum(
            1 for r in session.get("resources", []) if r.get("verified")),
    }
    session["state"] = "APPROVED_SENT"
    history = session.get("state_history")
    if isinstance(history, list) and (
            not history or history[-1] != "APPROVED_SENT"):
        history.append("APPROVED_SENT")
    store.update(session)
    return {
        "session_id": session_id,
        "state": session["state"],
        "approval_status": session["approval_status"],
        "approval_record": session["approval_record"],
        "session": _session_view(session),
    }


# ---------------------------------------------------------------------------
# The single-page frontend (app/static/). Its three files are served
# by the explicit routes below, registered BEFORE the mounts: the
# MCP sub-app is mounted at the root (next block) and a root mount
# matches every path, so the StaticFiles catch-all at the bottom is
# unreachable for any path the MCP app does not own — left to the
# mount alone, GET / 404s (the f48c0cc screen worked before the MCP
# wave precisely because the static mount was then the only
# catch-all). index.html references style.css and app.js relatively,
# so they must live at exactly /style.css and /app.js.
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def _index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/index.html", include_in_schema=False)
def _index_html() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/style.css", include_in_schema=False)
def _style_css() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "style.css"),
                        media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def _app_js() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "app.js"),
                        media_type="text/javascript")


# The MCP front door (MCP spec 2025-11-25, Streamable HTTP). The
# sub-app carries its own /mcp route and is mounted at the root,
# before the static catch-all so /mcp wins over / — see
# build_mcp_http_app for why it is not mounted AT /mcp.
app.mount("", _mcp_http_app, name="mcp")

# Static catch-all (mounted last so /api/* wins). Kept as the
# backstop for any future file dropped into app/static/ under a
# path the MCP app passes on; the frontend's own files are served
# by the explicit routes above.
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
