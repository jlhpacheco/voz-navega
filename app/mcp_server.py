"""Voz Navega — the MCP front door (Alexa+ track qualifying artifact).

A self-hosted MCP server implementing the **Model Context Protocol
spec, revision 2025-11-25, over the Streamable HTTP transport**,
built on the official MCP Python SDK (``mcp`` 2.x, ``MCPServer``).
It is mounted into the same FastAPI app as the web UI at ``POST
/mcp`` (see app/main.py), so one process serves every front door.

The tools are thin translations over app/flow.py — the SAME shared
turn flow the web API calls. There is no second path into the
engine: every ``patient_turn`` passes the safety gate first, and an
escalated turn returns the gate's fixed line with no draft, exactly
as on the web. The tools:

  - ``start_conversation`` — open a case; returns the session id
    and the companion's spoken greeting.
  - ``patient_turn`` — one patient utterance in; the companion's
    spoken reply, the conversation state, and the structured case
    content (barriers, question list, resources, banner) out.
  - ``case_status`` — read a case: state, barriers found, and the
    navigator approval status. (Approval itself stays on the
    human navigator's screen — no tool here can approve.)

An MCP client session (the ``initialize`` handshake, protocol
negotiation) is the transport's own session; the VOZ session id
returned by ``start_conversation`` is the case key and rides in
every later tool call — the same mapping ALEXA-PLAN.md §2 designs
for the Alexa session id.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from . import flow

# The track pins MCP spec 2025-11-25 or later (FACTS.md); the SDK's
# initialize handshake negotiates exactly 2025-11-25 with a client
# that offers it (asserted in tests/test_mcp_server.py).
PROTOCOL_VERSION = "2025-11-25"

mcp = MCPServer(
    "Voz Navega",
    instructions=(
        "Voz Navega is a voice-first companion that helps a "
        "fictional cancer patient prepare for a doctor visit. Call "
        "start_conversation once, then patient_turn for each thing "
        "the patient says, speaking the returned 'spoken' text "
        "back verbatim. It does not diagnose or treat; if a turn "
        "comes back escalated, speak its line and stop — a human "
        "navigator owns the case from that moment. Nothing is ever "
        "sent without a human navigator's approval, and approval "
        "does not happen through these tools."
    ),
    version="0.3.0",
)


class StartConversationOut(BaseModel):
    session_id: str
    greeting: str          # spoken form — say this out loud
    reply: str             # display text (same words, punctuated)
    gloss: str | None      # English gloss when the reply is Spanish
    state: str


class PatientTurnOut(BaseModel):
    session_id: str
    spoken: str            # spoken form — say this out loud
    reply: str
    gloss: str | None
    state: str
    escalated: bool
    safety_category: str | None
    approval_status: str | None
    barriers_found: list[dict[str, Any]]
    question_list: list[str] | None
    resources: list[dict[str, Any]]
    summary: dict[str, Any] | None
    banner: dict[str, Any] | None


class CaseStatusOut(BaseModel):
    session_id: str
    state: str
    # Plain state names, in order — except the escalation entry,
    # which the gate records as a dict carrying the firing rule
    # and safety detail. Passed through as recorded, not flattened.
    state_history: list[Any]
    language: str | None
    escalated: bool
    escalated_category: str | None
    approval_status: str | None
    barriers_found: list[dict[str, Any]]
    barrier_checklist: dict[str, Any]
    question_list: list[str] | None
    resources: list[dict[str, Any]]
    summary: dict[str, Any] | None
    turns_count: int


def _get_session(session_id: str) -> dict:
    session = flow.store.get(session_id)
    if session is None:
        raise ValueError(
            f"session {session_id} not found — open a case with "
            "start_conversation first")
    return session


@mcp.tool()
def start_conversation(ui_language: str = "en") -> StartConversationOut:
    """Open a new Voz Navega case for a fictional patient.

    Returns the VOZ session id (pass it to patient_turn and
    case_status) and the companion's greeting — speak the greeting
    to the patient. ui_language: "en" or "es"."""
    session, result = flow.start_session(ui_language)
    return StartConversationOut(
        session_id=session["id"],
        greeting=result["spoken"],
        reply=result["text"],
        gloss=result["gloss"],
        state=result["state"],
    )


@mcp.tool()
def patient_turn(session_id: str, text: str) -> PatientTurnOut:
    """Send one patient utterance and get the companion's reply.

    The turn passes the safety gate before anything is composed:
    on a crisis or medical-advice turn the reply is the gate's
    fixed escalation line, the state is ESCALATED, and no draft
    exists. Otherwise the companion advances the conversation —
    explaining in plain language, catching barriers the patient
    only hints at, building her doctor question list — until the
    case reaches HANDOFF, where it waits for a human navigator's
    approval (which never happens through this tool)."""
    session = _get_session(session_id)
    response = flow.run_patient_turn(session, text.strip())
    flow.store.update(session)
    companion = response["companion_turn"]
    return PatientTurnOut(
        session_id=response["session_id"],
        spoken=companion["spoken"],
        reply=companion["text"],
        gloss=companion["gloss"],
        state=response["state"],
        escalated=response["state"] == "ESCALATED",
        safety_category=response["safety"]["category"],
        approval_status=response["approval_status"],
        barriers_found=response["barriers_found"],
        question_list=response["question_list"],
        resources=response["resources"],
        summary=response["summary"],
        banner=response["banner"],
    )


@mcp.tool()
def case_status(session_id: str) -> CaseStatusOut:
    """Read a case without advancing it: conversation state, the
    barriers found so far (each tagged with how it was caught —
    stated by the patient or found by asking), the question list,
    the resources offered, and the navigator approval status."""
    session = _get_session(session_id)
    return CaseStatusOut(
        session_id=session["id"],
        state=session["state"],
        state_history=list(session.get("state_history", [])),
        language=session.get("language"),
        escalated=session.get("state") == "ESCALATED",
        escalated_category=session.get("escalated_category"),
        approval_status=session.get("approval_status"),
        barriers_found=[dict(b) for b in session.get("barriers_found", [])],
        barrier_checklist=dict(session.get("barrier_checklist") or {}),
        question_list=session.get("question_list"),
        resources=[dict(r) for r in session.get("resources", [])],
        summary=session.get("summary"),
        turns_count=len(session.get("turns", [])),
    )


def build_mcp_http_app():
    """The Streamable HTTP ASGI app serving POST /mcp.

    The app carries its own "/mcp" route and is mounted at the
    root of the FastAPI app (app/main.py). It is NOT mounted at
    "/mcp" with an inner "/" route: that combination 405s a POST
    to exactly "/mcp" — the mount matches the prefix but the inner
    route doesn't match the empty remainder, so the request falls
    through to the static catch-all (proven live, Oct 13).

    DNS-rebinding protection is disabled explicitly: that
    protection guards servers bound to localhost, while this app
    is served publicly (Render) where the Host is the service
    domain — leaving the SDK's localhost default on would 421
    every deployed request. The demo endpoint is unauthenticated
    by design (fictional patients, no real data, no secrets)."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False),
    )
