"""Voz Navega safety package.

classifier.py — deterministic pre-turn classification (ported from
                Podrá Navega's battery-proven classifier; see the
                header credit and taxonomy.md).
gate.py       — the turn-level gate the conversation engine calls
                before composing any reply; owns the ESCALATED
                outcome (no draft, crisis banner, human handoff).
battery.py    — adversarial battery runner (battery_cases.json).
"""

from .classifier import (  # noqa: F401
    CRISIS_BANNER,
    classify_message,
    escalation_payload,
)
from .gate import ESCALATED, evaluate_turn  # noqa: F401
