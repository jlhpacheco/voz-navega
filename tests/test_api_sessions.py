"""API-level proof for the Voz Navega session engine + navigator gate.

Drives the golden conversations (ARCHITECTURE.md §1.3 / §1.4) THROUGH
the HTTP API (TestClient), the crisis interrupt through the API, and
every 409 path of the approval gate (§3.3) plus the successful
approve. The brain-level equivalent lives in scripts/golden_run.py;
this file proves the wiring: safety gate first on every turn, then
the brain, with the gate enforced server-side.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

EXPECTED_HISTORY = [
    "GREETING", "INTAKE", "DISCOVERY", "EXPLAIN",
    "QUESTIONS", "RESOURCES", "HANDOFF",
]

GOLDEN_A_LINES = [
    "They told me I need a biopsy on Tuesday and I'm scared. "
    "I don't really know what it is.",
    "Getting there. My daughter works, and I don't drive. And I watch "
    "my grandkids in the mornings — who watches them?",
    "Keep going. Will it hurt?",
    "That's good. Nothing to add.",
]

GOLDEN_B_LINES = [
    "Me dijeron que voy a empezar quimioterapia y no entiendo bien "
    "qué es. También me preocupa cuánto va a costar.",
    "Mi hija, pero trabaja en las mañanas. Tengo miedo de sentirme "
    "muy mal y no poder cuidar a mi mamá.",
    "¿Y si no puedo pagar el tratamiento?",
    "No, así está bien.",
]

CRISIS_LINE = ("I have a fever and I can't stop vomiting since "
               "last night.")


def create_session(ui_language: str = "en") -> str:
    r = client.post("/api/sessions", json={"ui_language": ui_language})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def turn(session_id: str, text: str) -> dict:
    r = client.post(f"/api/sessions/{session_id}/turns",
                    json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def drive(session_id: str, lines: list[str]) -> dict:
    body = {}
    for line in lines:
        body = turn(session_id, line)
    return body


def barriers_by_name(body: dict) -> dict:
    return {b["barrier"]: b for b in body["barriers_found"]}


# ---------------------------------------------------------------------------
# Sessions + golden conversations through the API
# ---------------------------------------------------------------------------


def test_create_session_returns_greeting():
    r = client.post("/api/sessions", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "GREETING"
    assert "Voz" in body["reply"]
    assert "I don't diagnose" in body["reply"]
    view = client.get(f"/api/sessions/{body['session_id']}").json()
    assert view["state"] == "GREETING"
    assert view["fictional"] is True
    assert view["turns"][0]["speaker"] == "voz"


def test_seeded_golden_session_sits_at_handoff():
    view = client.get("/api/sessions/VOZ-0001").json()
    assert view["state"] == "HANDOFF"
    assert view["approval_status"] == "PENDING_APPROVAL"
    assert view["summary"] is not None
    assert all(r["verified"] is False for r in view["resources"])


def test_golden_a_through_api():
    sid = create_session()
    states = [turn(sid, line)["state"] for line in GOLDEN_A_LINES[:2]]
    assert states == ["DISCOVERY", "EXPLAIN"]

    body = turn(sid, GOLDEN_A_LINES[2])
    assert body["state"] == "QUESTIONS"
    assert "Will it hurt?" in body["question_list"]
    found = barriers_by_name(body)
    assert found["fear"]["confirmed_by"] == "stated"
    assert found["transport"]["confirmed_by"] == "probe"
    assert found["childcare"]["confirmed_by"] == "probe"
    assert found["childcare"]["evidence"]

    body = turn(sid, GOLDEN_A_LINES[3])
    assert body["state"] == "HANDOFF"
    assert body["approval_status"] == "PENDING_APPROVAL"
    assert body["state_history"] == EXPECTED_HISTORY
    types = {r["type"] for r in body["resources"]}
    assert types == {"transport", "support_group"}
    assert all(r["verified"] is False for r in body["resources"])
    assert body["summary"] is not None
    assert body["draft"] == body["summary"]

    # GET exposes the full record the navigator panel needs.
    view = client.get(f"/api/sessions/{sid}").json()
    assert view["state"] == "HANDOFF"
    assert view["barrier_checklist"]["transport"] is True
    assert view["barrier_checklist"]["childcare"] is True
    assert "Will it hurt?" in view["question_list"]
    assert {r["type"] for r in view["resources"]} == types
    assert "childcare" in view["summary"]["text"]


def test_golden_b_through_api_spanish_with_gloss():
    sid = create_session("es")
    body = drive(sid, GOLDEN_B_LINES)
    assert body["state"] == "HANDOFF"
    assert body["approval_status"] == "PENDING_APPROVAL"
    assert body["state_history"] == EXPECTED_HISTORY

    view = client.get(f"/api/sessions/{sid}").json()
    assert view["language"] == "es"
    found = barriers_by_name(view)
    assert found["cost"]["confirmed_by"] == "stated"
    assert found["health_literacy"]["confirmed_by"] == "stated"
    assert found["fear"]["confirmed_by"] == "probe"
    assert found["other"]["confirmed_by"] == "probe"
    assert "¿Y si no puedo pagar el tratamiento?" in view["question_list"]
    types = {r["type"] for r in view["resources"]}
    assert types == {"financial", "support_group"}
    # Every Spanish companion turn carries its English gloss.
    voz_turns = [t for t in view["turns"] if t["speaker"] == "voz"]
    assert all(t.get("gloss") for t in voz_turns)
    assert any(t["gloss"] != t["text"] for t in voz_turns)


# ---------------------------------------------------------------------------
# Crisis through the API — at turn 1 and mid-conversation
# ---------------------------------------------------------------------------


def test_crisis_at_turn_one_through_api():
    sid = create_session()
    body = turn(sid, CRISIS_LINE)
    assert body["state"] == "ESCALATED"
    assert body["safety"]["category"] == "crisis"
    assert body["draft"] is None
    assert body["summary"] is None
    assert "911" in body["banner"]["headline"]
    assert "Call 911 or your care team now" in body["reply"]
    assert body["handoff"]["to"] == "human_navigator"
    assert body["handoff"]["queue"] == "front"
    # Terminal: a calm follow-up turn never un-escalates.
    body = turn(sid, "Actually I feel fine now, tell me about the biopsy.")
    assert body["state"] == "ESCALATED"
    assert body["draft"] is None


def test_crisis_mid_conversation_through_api():
    sid = create_session()
    body = drive(sid, GOLDEN_A_LINES[:2])
    assert body["state"] == "EXPLAIN"
    body = turn(sid, CRISIS_LINE)
    assert body["state"] == "ESCALATED"
    assert body["safety"]["category"] == "crisis"
    view = client.get(f"/api/sessions/{sid}").json()
    assert view["escalated"] is True
    assert view["escalated_category"] == "crisis"
    # The triggering sentence is in the transcript for the human.
    assert any(t["speaker"] == "patient" and "fever" in t["text"]
               for t in view["turns"])


# ---------------------------------------------------------------------------
# The four 409 paths (ARCHITECTURE.md §3.3)
# ---------------------------------------------------------------------------


def test_409_approve_escalated_session():
    sid = create_session()
    turn(sid, CRISIS_LINE)
    r = client.post(f"/api/sessions/{sid}/approve", json={"by": "Nav"})
    assert r.status_code == 409
    assert "human navigator" in r.json()["detail"]


def test_409_approve_wrong_state():
    sid = create_session()  # still GREETING — nothing to approve
    r = client.post(f"/api/sessions/{sid}/approve", json={})
    assert r.status_code == 409
    assert "GREETING" in r.json()["detail"]
    turn(sid, GOLDEN_A_LINES[0])  # mid-conversation: still not pending
    r = client.post(f"/api/sessions/{sid}/approve", json={})
    assert r.status_code == 409


def test_409_approve_with_unverified_resources():
    sid = create_session()
    drive(sid, GOLDEN_A_LINES)
    r = client.post(f"/api/sessions/{sid}/approve", json={})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "unverified" in detail.lower()
    assert "VTA Paratransit" in detail  # the unverified are named
    # Verifying only one of two is not enough.
    client.post(f"/api/sessions/{sid}/verify-resource",
                json={"type": "transport"})
    r = client.post(f"/api/sessions/{sid}/approve", json={})
    assert r.status_code == 409
    assert "Latinas Contra Cancer" in r.json()["detail"]


def test_409_edit_summary_blocked_states():
    sid = create_session()
    turn(sid, CRISIS_LINE)  # ESCALATED
    r = client.post(f"/api/sessions/{sid}/edit-summary",
                    json={"text": "edited"})
    assert r.status_code == 409
    sid = create_session()  # GREETING — no summary exists to edit
    r = client.post(f"/api/sessions/{sid}/edit-summary",
                    json={"text": "x"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Verify + edit + the successful approve
# ---------------------------------------------------------------------------


def test_verify_resource_marks_attestation():
    sid = create_session()
    drive(sid, GOLDEN_A_LINES)
    r = client.post(f"/api/sessions/{sid}/verify-resource",
                    json={"type": "transport", "by": "Elena — Navigator"})
    assert r.status_code == 200
    body = r.json()
    assert body["resource"]["verified"] is True
    assert body["resource"]["verified_by"] == "Elena — Navigator"
    assert "attestation" in body["resource"]["verification"]
    assert body["all_verified"] is False
    r = client.post(f"/api/sessions/{sid}/verify-resource",
                    json={"index": 1})
    assert r.json()["all_verified"] is True
    r = client.post(f"/api/sessions/{sid}/verify-resource",
                    json={"name": "No such resource"})
    assert r.status_code == 404


def test_approve_success_end_to_end():
    sid = create_session()
    drive(sid, GOLDEN_A_LINES)
    # The navigator edits the summary first — the edit is recorded.
    r = client.post(f"/api/sessions/{sid}/edit-summary",
                    json={"text": "Navigator-edited summary."})
    assert r.status_code == 200
    assert r.json()["summary"]["text"] == "Navigator-edited summary."
    for rtype in ("transport", "support_group"):
        client.post(f"/api/sessions/{sid}/verify-resource",
                    json={"type": rtype})
    r = client.post(f"/api/sessions/{sid}/approve",
                    json={"by": "Elena — Navigator"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "APPROVED_SENT"
    assert body["approval_status"] == "APPROVED_SENT"
    record = body["approval_record"]
    assert record["by"] == "Elena — Navigator"
    assert record["at"]
    assert record["resources_verified"] == 2
    assert record["navigator_edited"] is True
    # Double approval is a 409, not a second send.
    r = client.post(f"/api/sessions/{sid}/approve", json={})
    assert r.status_code == 409
    # Only now may the companion deliver its closing turn.
    body = turn(sid, "Thank you.")
    assert body["state"] == "CLOSED"
    assert "reviewed everything" in body["reply"]


# ---------------------------------------------------------------------------
# Queue + 404s + the legacy endpoint
# ---------------------------------------------------------------------------


def test_queue_lists_escalated_first():
    calm = create_session()
    hot = create_session()
    turn(hot, CRISIS_LINE)
    queue = client.get("/api/sessions").json()["sessions"]
    ids = [e["id"] for e in queue]
    assert hot in ids and calm in ids
    # Escalated cases form a block at the front of the queue (other
    # tests in this process escalated sessions of their own, so the
    # invariant is the partition, not position 0).
    flags = [e["escalated"] for e in queue]
    assert flags == sorted(flags, reverse=True)
    assert ids.index(hot) < ids.index(calm)


def test_unknown_session_404s():
    assert client.get("/api/sessions/VOZ-9999").status_code == 404
    assert client.post("/api/sessions/VOZ-9999/turns",
                       json={"text": "hi"}).status_code == 404
    assert client.post("/api/sessions/VOZ-9999/approve",
                       json={}).status_code == 404
    assert client.post("/api/sessions/VOZ-9999/verify-resource",
                       json={"index": 0}).status_code == 404
    assert client.post("/api/sessions/VOZ-9999/edit-summary",
                       json={"text": "x"}).status_code == 404


def test_legacy_turn_endpoint_runs_the_real_flow():
    r = client.post("/api/turn", json={
        "text": "What time does the shuttle to the clinic leave?"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]
    assert body["state"] == "INTAKE"
    assert body["safety"]["category"] == "routine"
    # …and a session_id continues that same conversation.
    r = client.post("/api/turn", json={
        "session_id": body["session_id"], "text": GOLDEN_A_LINES[0]})
    assert r.json()["state"] == "DISCOVERY"
