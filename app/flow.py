"""Voz Navega — the shared turn flow: ONE door into the engine.

Every front door — the web API (app/main.py), the MCP server
(app/mcp_server.py), and any future adapter (ALEXA-PLAN.md) — calls
:func:`run_patient_turn`, and nothing reaches the demo brain except
through it. The flow is, on every patient turn, in this order:

  1. safety.gate.evaluate_turn classifies the raw turn
     (crisis > medical_advice > sensitive > routine). An escalated
     turn composes NOTHING — the response is the gate's fixed line,
     the red banner for crisis, draft=None, and the session is
     ESCALATED for good.
  2. Only a routine turn reaches the demo brain, which advances the
     conversation state machine (GREETING → … → HANDOFF). A session
     a human already approved gets exactly one closing turn.

This module also owns the process-wide SessionStore: one store,
shared by every front door, so a case opened through one door is
the same case on all the others. Deliberately no database — see
app/store.py.
"""

from __future__ import annotations

import os
import sys

# The safety package lives at the repo root (sibling of app/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from safety.gate import evaluate_turn  # noqa: E402

from . import brain_demo as brain  # noqa: E402
from .store import SessionStore  # noqa: E402

# The one session store for the whole process (all front doors).
store = SessionStore()


def start_session(ui_language: str = "en") -> tuple[dict, dict]:
    """Create a session, run the greeting turn, store it.

    Returns ``(session, greeting_result)`` — the greeting result is
    the brain's turn dict (text / gloss / spoken / state)."""
    language = "es" if (ui_language or "en").lower().startswith("es") else "en"
    session = brain.new_session(store.next_id())
    result = brain.greeting_turn(session, language)
    store.create(session)
    return session, result


def safety_view(outcome: dict) -> dict:
    raw = outcome.get("safety") or {}
    return {
        "category": outcome.get("category") or raw.get("category"),
        "escalate": bool(outcome.get("escalate")),
        "reason": raw.get("reason", ""),
        "rule": outcome.get("rule", raw.get("rule")),
        "source": "safety.gate",
    }


def turn_response(session: dict, result: dict, safety: dict) -> dict:
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
        "state_history": result["state_history"],
        "slots": result["slots"],
        "barriers_found": result["barriers_found"],
        "question_list": result["question_list"],
        "resources": result["resources"],
        "summary": result["summary"],
        "draft": result["summary"],
        "approval_status": result["approval_status"],
        "banner": result["banner"],
        "handoff": None,
        "safety": safety,
    }


def run_patient_turn(session: dict, text: str) -> dict:
    """One patient turn through the real flow: the safety gate FIRST,
    then the brain. Mutates the passed session copy; the caller writes
    it back to the store."""
    state_before = session.get("state")
    outcome = evaluate_turn(session, text)
    safety = safety_view(outcome)

    if not outcome["allowed"]:
        # Escalated: the gate composed nothing. Record the patient's
        # words and the fixed line so the navigator sees the trigger,
        # and void any pending approval — an escalated case is never
        # offered for approval (§1.2, §3.3).
        session["turns"].append({
            "speaker": "patient", "text": text, "state": state_before})
        session["turns"].append({
            "speaker": "voz",
            "text": outcome["companion_turn"],
            "gloss": (outcome["companion_turn_gloss"]
                      or outcome["companion_turn"]),
            "state": "ESCALATED",
        })
        if session.get("approval_status") == "PENDING_APPROVAL":
            session["approval_status"] = None
        return {
            "session_id": session["id"],
            "reply": outcome["companion_turn"],
            "companion_turn": {
                "speaker": "voz",
                "text": outcome["companion_turn"],
                "gloss": outcome["companion_turn_gloss"],
                "spoken": outcome["companion_turn"],
            },
            "state": "ESCALATED",
            "state_history": list(session.get("state_history", [])),
            "slots": dict(session.get("slots") or {}),
            "barriers_found": [dict(b) for b in
                               session.get("barriers_found", [])],
            "question_list": session.get("question_list"),
            "resources": [dict(r) for r in session.get("resources", [])],
            "summary": None,
            "draft": None,
            "approval_status": session.get("approval_status"),
            "banner": outcome["banner"],
            "handoff": outcome["handoff"],
            "safety": safety,
        }

    if session.get("state") == "APPROVED_SENT":
        # A human approved; the companion may now deliver its closing
        # turn — exactly once, then the session is CLOSED (§1.2).
        session["turns"].append({
            "speaker": "patient", "text": text, "state": state_before})
        result = brain.closing_turn(session)
    else:
        result = brain.handle_turn(session, text)
    return turn_response(session, result, safety)
