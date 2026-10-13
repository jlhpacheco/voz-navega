"""App-level proof that the safety gate runs before reply composition
in the live HTTP surface (/api/turn): escalated turns get the fixed
escalation payload; no companion reply is ever composed for them.
(Originally written against the wave-1 scaffold; the routine-turn
test now asserts the real engine flow that replaced the stub.)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_routine_turn_reaches_the_real_engine():
    r = client.post("/api/turn", json={
        "text": "What time does the shuttle to the clinic leave?"})
    assert r.status_code == 200
    body = r.json()
    # The gate passed the turn and the real brain answered: a fresh
    # session now sits in INTAKE, asked for the next care step.
    assert body["session_id"]
    assert body["state"] == "INTAKE"
    assert body["safety"]["category"] == "routine"
    assert "next step" in body["reply"]
    assert "scaffold" not in body["reply"]


def test_crisis_turn_escalates_before_any_reply():
    r = client.post("/api/turn", json={
        "text": "I have a fever and I can't stop vomiting since "
                "last night."})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ESCALATED"
    assert body["draft"] is None
    assert body["safety"]["category"] == "crisis"
    assert body["safety"]["source"] == "safety.gate"
    # The reply is the fixed §1.5 line, NOT the stub echo.
    assert "Call 911 or your care team now" in body["reply"]
    assert "I heard you say" not in body["reply"]
    assert "911" in body["banner"]["headline"]
    assert body["handoff"]["to"] == "human_navigator"


def test_medical_turn_escalates_before_any_reply():
    r = client.post("/api/turn", json={
        "text": "¿Debo dejar de tomar mi medicamento para la "
                "presión antes de la cirugía?"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ESCALATED"
    assert body["safety"]["category"] == "medical_advice"
    assert body["banner"] is None
    assert body["draft"] is None
    assert "I heard you say" not in body["reply"]
