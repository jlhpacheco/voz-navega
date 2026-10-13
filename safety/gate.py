"""Turn-level safety gate for Voz Navega.

The classifier (classifier.py) judges ONE message. This gate is what
the conversation engine calls on EVERY patient turn, BEFORE any reply
is composed — including mid-conversation turns, which is where a
one-shot intake check fails: a patient can be three turns into a calm
conversation and then report a fever. The gate:

  - classifies the turn (crisis > medical_advice > sensitive > routine)
  - on any escalation: flips the session to ESCALATED, records what
    fired, and returns an outcome with NO draft and NO composed reply —
    only the category's fixed spoken line and, for crisis, the red
    banner payload ("call 911 / your care team")
  - treats ESCALATED as terminal for the AI: once a session is
    escalated, every later turn returns the same escalation outcome
    without re-classifying. A human owns the case from that moment.

The engine composes a reply ONLY when the outcome's "allowed" is True.
"""

from __future__ import annotations

try:  # package import (app, tests, battery via repo root)
    from .classifier import classify_message, escalation_payload
except ImportError:  # top-level import (running inside safety/)
    from classifier import classify_message, escalation_payload  # noqa: F401

ESCALATED = "ESCALATED"


def _escalation_outcome(session: dict, category: str, rule,
                        safety: dict | None) -> dict:
    language = session.get("language", "en")
    payload = escalation_payload(category, language)
    return {
        "allowed": False,
        "category": category,
        "escalate": True,
        "rule": rule,
        "state": ESCALATED,
        # The whole point of the gate: there is never a draft and never
        # a composed reply on an escalated turn.
        "draft": None,
        "banner": payload["banner"],
        "companion_turn": payload["spoken"],
        "companion_turn_gloss": payload["spoken_gloss"],
        "handoff": {
            "to": "human_navigator",
            "queue": "front" if category == "crisis" else "standard",
            "reason": (safety or {}).get("reason", ""),
        },
        "safety": safety,
    }


def evaluate_turn(session: dict, text: str, *, at: str | None = None) -> dict:
    """Run the safety gate on one patient turn.

    `session` is the engine's plain session dict; the gate reads
    `session["state"]` / `session["language"]` and, on escalation,
    sets `session["state"] = "ESCALATED"`, records
    `escalated_category` / `escalated_rule`, and appends to
    `session["state_history"]` when that list exists.

    Returns the outcome dict described in the module docstring.
    """
    if session.get("state") == ESCALATED:
        # Terminal for the AI — a human owns this case. Do not
        # re-classify, do not compose, do not un-escalate.
        return _escalation_outcome(
            session,
            session.get("escalated_category") or "crisis",
            session.get("escalated_rule"),
            session.get("escalation_safety"),
        )

    result = classify_message(text)

    if not result["escalate"]:
        return {
            "allowed": True,
            "category": "routine",
            "escalate": False,
            "rule": result["rule"],
            "state": session.get("state"),
            "draft": None,  # the engine fills this when it composes
            "banner": None,
            "companion_turn": None,  # the engine composes the reply
            "companion_turn_gloss": None,
            "handoff": None,
            "safety": result,
        }

    session["state"] = ESCALATED
    session["escalated_category"] = result["category"]
    session["escalated_rule"] = result["rule"]
    session["escalation_safety"] = result
    history = session.get("state_history")
    if isinstance(history, list):
        entry = {
            "state": ESCALATED,
            "category": result["category"],
            "rule": result["rule"],
        }
        if at is not None:
            entry["at"] = at
        history.append(entry)

    return _escalation_outcome(session, result["category"],
                                result["rule"], result)
