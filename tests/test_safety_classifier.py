"""Safety battery as pytest — single-turn classification.

The same battery_cases.json that safety/battery.py runs. The
zero-tolerance set (crisis + medical_advice) must pass 100%: any one
of those turns slipping through to reply composition is a product
failure, not a test statistic.
"""

from __future__ import annotations

import json
import os

import pytest

from safety.classifier import classify_message

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "..", "safety", "battery_cases.json"),
          encoding="utf-8") as f:
    _DATA = json.load(f)

CASES = _DATA["cases"]
ZERO_TOLERANCE = [c for c in CASES
                  if c["expected_category"] in ("crisis", "medical_advice")]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_battery_case(case):
    result = classify_message(case["text"])
    assert result["category"] == case["expected_category"], (
        f"{case['id']}: expected {case['expected_category']}, "
        f"got {result['category']} (rule={result['rule']})")
    assert result["escalate"] == case["expected_escalate"]


def test_zero_tolerance_set_is_complete_and_perfect():
    """Crisis + medical: every case escalates, zero exceptions."""
    assert len(ZERO_TOLERANCE) == 21  # 10 crisis + 11 medical
    for case in ZERO_TOLERANCE:
        result = classify_message(case["text"])
        assert result["category"] == case["expected_category"], case["id"]
        assert result["escalate"] is True, case["id"]


def test_routine_cases_never_escalate():
    routine = [c for c in CASES if c["expected_category"] == "routine"]
    assert len(routine) == 18
    for case in routine:
        result = classify_message(case["text"])
        assert result["escalate"] is False, case["id"]
        assert result["category"] == "routine", case["id"]


def test_precedence_crisis_beats_medical():
    # Fever (crisis) phrased as a question with medical-advice shape.
    result = classify_message(
        "Tengo fiebre de 39 y estoy en quimioterapia, ¿qué hago?")
    assert result["category"] == "crisis"
    assert result["rule"] == "fever_during_treatment"


def test_result_shape_has_rule_key():
    result = classify_message("What time does the shuttle leave?")
    assert set(result) >= {"category", "escalate", "reason", "rule"}
    assert result["rule"] is None  # routine match names no rule


def test_empty_turn_is_routine_and_safe():
    result = classify_message("   ")
    assert result["category"] == "routine"
    assert result["escalate"] is False
