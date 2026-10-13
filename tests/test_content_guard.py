"""Content-free turn guard (brain_demo._has_meaningful_content).

A turn with no real words — an empty string, whitespace, emoji or
punctuation alone, keyboard salad — is not a stated concern. The
companion gently re-asks what is on the patient's mind and the
machine does NOT move: no state advance, no barrier/topic recorded,
no probe spent, nothing appended verbatim to the question list.
Before this guard, such a turn was accepted as a concern and walked
GREETING → INTAKE with the canned intake question (cold-verification
wart, Oct 13). These tests pin the corrected behavior at the brain
level and through the HTTP API.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import brain_demo as brain
from app.main import app

client = TestClient(app)

GOLDEN_A_LINES = [
    "They told me I need a biopsy on Tuesday and I'm scared. "
    "I don't really know what it is.",
    "Getting there. My daughter works, and I don't drive. And I watch "
    "my grandkids in the mornings — who watches them?",
    "Keep going. Will it hurt?",
    "That's good. Nothing to add.",
]

CONTENT_FREE = [
    "", "   ", "😀😀", "???", "...", "asdf", "qwerty", "12345",
    "hmm", "aaaa", "bcdf", "aeiou", "jkl;", "zxcvbn",
]

REAL_TURNS = [
    "No", "Yes", "ok", "I", "Tuesday", "I'm sad", "Biopsy",
    "Keep going", "No, así está bien.", "¿Y si no puedo pagar?",
]


def new_talked_session(ui_language: str = "en") -> dict:
    session = brain.new_session()
    brain.greeting_turn(session, ui_language)
    return session


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", CONTENT_FREE)
def test_content_free_detection(text):
    assert not brain._has_meaningful_content(text)


@pytest.mark.parametrize("text", REAL_TURNS)
def test_real_turns_carry_content(text):
    assert brain._has_meaningful_content(text)


def test_short_real_words_survive_the_keyboard_salad_rule():
    # 'sad' and 'try' are contiguous keyboard-row runs of 3 letters;
    # the salad rule only applies at 4+ letters so they stay words.
    assert brain._is_word("sad")
    assert brain._is_word("try")


# ---------------------------------------------------------------------------
# First turn: the session stays at GREETING, with a re-ask
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", CONTENT_FREE)
def test_content_free_first_turn_stays_at_greeting(text):
    s = new_talked_session()
    r = brain.handle_turn(s, text)
    assert r["state"] == "GREETING"
    assert s["state"] == "GREETING"
    assert s["state_history"] == ["GREETING"]
    assert "catch that" in r["text"]  # the gentle re-ask
    # Nothing was recorded from the turn.
    assert s["_first_patient_turn"] is None
    assert s["slots"]["topic"] is None
    assert s["barriers_found"] == []
    assert s["language"] is None


def test_reask_after_content_free_first_turn_uses_ui_language():
    s = new_talked_session("es")
    r = brain.handle_turn(s, "😀")
    assert r["state"] == "GREETING"
    assert "escucho" in r["text"]          # Spanish re-ask
    assert "catch that" in r["gloss"]      # gloss stays English
    assert r["gloss"] != r["text"]


def test_conversation_recovers_after_a_content_free_first_turn():
    s = new_talked_session()
    brain.handle_turn(s, "asdf")
    r = brain.handle_turn(s, GOLDEN_A_LINES[0])
    assert r["state"] == "DISCOVERY"
    assert s["state_history"] == ["GREETING", "INTAKE", "DISCOVERY"]
    assert s["_first_patient_turn"].startswith("They told me")
    assert s["slots"]["topic"] == "biopsy"


# ---------------------------------------------------------------------------
# Mid-conversation: no advance, no probe spent, no list pollution
# ---------------------------------------------------------------------------


def test_content_free_turn_in_discovery_spends_no_probe():
    s = new_talked_session()
    brain.handle_turn(s, GOLDEN_A_LINES[0])
    assert s["state"] == "DISCOVERY"
    assert s["probes_asked"] == 1
    r = brain.handle_turn(s, "😀")
    assert r["state"] == "DISCOVERY"
    assert s["probes_asked"] == 1
    assert len(s["probes_used"]) == 1
    assert s["slots"]["topic"] == "biopsy"
    assert len(s["barriers_found"]) == 2  # fear + health_literacy only


def test_content_free_turn_in_explain_builds_no_question():
    s = new_talked_session()
    brain.handle_turn(s, GOLDEN_A_LINES[0])
    brain.handle_turn(s, GOLDEN_A_LINES[1])
    assert s["state"] == "EXPLAIN"
    # Before the guard, "???" was folded in as a verbatim question.
    r = brain.handle_turn(s, "???")
    assert r["state"] == "EXPLAIN"
    assert s["question_list"] is None
    assert s["question_list_en"] is None


def test_content_free_turn_in_questions_pollutes_nothing():
    s = new_talked_session()
    for line in GOLDEN_A_LINES[:3]:
        brain.handle_turn(s, line)
    assert s["state"] == "QUESTIONS"
    before = list(s["question_list"])
    r = brain.handle_turn(s, "???")
    assert r["state"] == "QUESTIONS"
    assert s["question_list"] == before
    assert "???" not in s["question_list"]
    # A real closing turn still completes the conversation.
    r = brain.handle_turn(s, GOLDEN_A_LINES[3])
    assert r["state"] == "HANDOFF"
    assert r["approval_status"] == "PENDING_APPROVAL"


# ---------------------------------------------------------------------------
# Through the HTTP API (the flow the frontend actually drives)
# ---------------------------------------------------------------------------


def _create(ui_language: str = "en") -> str:
    r = client.post("/api/sessions", json={"ui_language": ui_language})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _turn(session_id: str, text: str) -> dict:
    r = client.post(f"/api/sessions/{session_id}/turns",
                    json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_api_content_free_first_turn_stays_at_greeting():
    sid = _create()
    for junk in ("", "   ", "😀", "asdf"):
        body = _turn(sid, junk)
        assert body["state"] == "GREETING", junk
        assert "catch that" in body["reply"]
        assert body["barriers_found"] == []
    body = _turn(sid, GOLDEN_A_LINES[0])
    assert body["state"] == "DISCOVERY"
    assert body["slots"]["topic"] == "biopsy"
