"""Golden-conversation run-through for the Voz Navega demo brain.

Drives BOTH golden conversations from ARCHITECTURE.md (§1.3 Marisol EN,
§1.4 Rosa ES) through app/brain_demo.py turn by turn and asserts:
every expected barrier is caught with the right confirmed_by tag, the
states advance in the architecture's order, the question list gains the
patient's verbatim questions, resources attach unverified, and the
session parks at HANDOFF / PENDING_APPROVAL with a summary.

Run from the repo root:  python scripts/golden_run.py
Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import brain_demo as brain  # noqa: E402

EXPECTED_HISTORY = [
    "GREETING", "INTAKE", "DISCOVERY", "EXPLAIN",
    "QUESTIONS", "RESOURCES", "HANDOFF",
]


def show(session: dict, result: dict) -> None:
    print(f"  VOZ [{result['state']}]: {result['text']}")
    if result["gloss"] != result["text"]:
        print(f"       gloss: {result['gloss']}")


def patient(session: dict, text: str) -> dict:
    print(f"  PATIENT: {text}")
    result = brain.handle_turn(session, text)
    show(session, result)
    # Spoken-turn rule (§1.1): the companion POSES at most one question
    # per turn. A quoted question being read back from her list («…» /
    # “…” in the read-back lead) is content, not a posed question.
    import re
    posed = re.sub(r"[“«][^”»]*[”»]", "", result["text"])
    assert posed.count("?") <= 1, "companion posed >1 question in a turn"
    return result


def barriers_by_name(result: dict) -> dict:
    return {b["barrier"]: b for b in result["barriers_found"]}


def golden_a() -> None:
    print("\n=== Golden A — Marisol (EN, biopsy) ===")
    s = brain.new_session()
    g = brain.greeting_turn(s, "en")
    print(f"  VOZ [GREETING]: {g['text']}")
    assert s["state"] == "GREETING"

    r1 = patient(s, "They told me I need a biopsy on Tuesday and I'm "
                    "scared. I don't really know what it is.")
    assert r1["state"] == "DISCOVERY", r1["state"]
    assert s["slots"]["topic"] == "biopsy"
    assert s["slots"]["appointment_text"] == "Tuesday"
    found = barriers_by_name(r1)
    assert found["fear"]["confirmed_by"] == "stated"
    assert found["health_literacy"]["confirmed_by"] == "stated"

    r2 = patient(s, "Getting there. My daughter works, and I don't "
                    "drive. And I watch my grandkids in the mornings — "
                    "who watches them?")
    assert r2["state"] == "EXPLAIN", r2["state"]
    found = barriers_by_name(r2)
    assert found["transport"]["confirmed_by"] == "probe"
    assert found["childcare"]["confirmed_by"] == "probe"
    # The daughter's job is family logistics, NOT Marisol's barrier.
    assert "work_schedule" not in found
    assert any("Family logistics" in n for n in s["notes"])
    assert "small sample of tissue" in r2["text"]

    r3 = patient(s, "Keep going. Will it hurt?")
    assert r3["state"] == "QUESTIONS", r3["state"]
    assert "pressure more than pain" in r3["text"]
    assert "Will it hurt?" in r3["question_list"]
    # 5 base + 4 barrier-derived + 1 verbatim
    assert len(r3["question_list"]) == 10, r3["question_list"]

    r4 = patient(s, "That's good. Nothing to add.")
    assert r4["state"] == "HANDOFF", r4["state"]
    assert r4["approval_status"] == "PENDING_APPROVAL"
    assert s["state_history"] == EXPECTED_HISTORY, s["state_history"]
    types = {r["type"] for r in r4["resources"]}
    assert types == {"transport", "support_group"}, types
    assert all(r["verified"] is False for r in r4["resources"])
    assert r4["summary"] is not None
    assert "childcare" in r4["summary"]["text"]
    print("  Golden A: PASS")


def golden_b() -> None:
    print("\n=== Golden B — Rosa (ES, chemotherapy) ===")
    s = brain.new_session()
    g = brain.greeting_turn(s, "es")
    print(f"  VOZ [GREETING]: {g['text']}")
    print(f"       gloss: {g['gloss']}")

    r1 = patient(s, "Me dijeron que voy a empezar quimioterapia y no "
                    "entiendo bien qué es. También me preocupa cuánto va "
                    "a costar.")
    assert s["language"] == "es"
    assert r1["state"] == "DISCOVERY", r1["state"]
    assert s["slots"]["topic"] == "chemotherapy"
    found = barriers_by_name(r1)
    assert found["health_literacy"]["confirmed_by"] == "stated"
    assert found["cost"]["confirmed_by"] == "stated"
    assert "fear" not in found  # fear surfaces via the probe, not here
    assert "¿quién le acompaña" in r1["text"]
    assert "who is with you at home" in r1["gloss"]

    r2 = patient(s, "Mi hija, pero trabaja en las mañanas. Tengo miedo "
                    "de sentirme muy mal y no poder cuidar a mi mamá.")
    assert r2["state"] == "EXPLAIN", r2["state"]
    found = barriers_by_name(r2)
    assert found["fear"]["confirmed_by"] == "probe"
    assert found["other"]["confirmed_by"] == "probe"
    assert "work_schedule" not in found
    assert any("Family logistics" in n for n in s["notes"])
    assert "tratamiento con medicamentos" in r2["text"]
    assert r2["gloss"] != r2["text"]

    r3 = patient(s, "¿Y si no puedo pagar el tratamiento?")
    assert "¿Y si no puedo pagar el tratamiento?" in r3["question_list"]
    types = {r["type"] for r in r3["resources"]}
    assert types == {"financial", "support_group"}, types
    assert all(r["verified"] is False for r in r3["resources"])

    r4 = patient(s, "No, así está bien.")
    assert s["language"] == "es"  # short reply must not flip the session
    assert r4["state"] == "HANDOFF", r4["state"]
    assert r4["approval_status"] == "PENDING_APPROVAL"
    assert s["state_history"] == EXPECTED_HISTORY, s["state_history"]
    assert r4["summary"] is not None
    assert any("CancerCare" in name
               for name in r4["summary"]["resources_offered"])
    print("  Golden B: PASS")


if __name__ == "__main__":
    golden_a()
    golden_b()
    print("\nALL GOLDEN CONVERSATIONS PASS")
