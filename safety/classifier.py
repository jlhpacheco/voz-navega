"""Pre-turn safety classifier for Voz Navega.

PORTED from Podrá Navega's proven classifier
(nebius-hackathon/repo/safety/classifier.py) — rule lists below are
verbatim unless marked VOZ EXTENSION. Credit: the taxonomy, the intent
rules, and the precedence order were built and battery-proven on Podrá
(31/31, crisis+medical zero-tolerance 16/16) and are carried over, not
reinvented. See taxonomy.md in this directory.

DETERMINISTIC, rule/keyword based. No LLM call. This MUST run on EVERY
patient turn — not just the first message — BEFORE any reply (demo
brain or live model) is composed:

  - crisis         -> NO draft, NO composed reply. Red banner (call
                      911 / care team now), session ESCALATED, case
                      jumps the navigator queue. escalate=True
  - medical_advice -> NO draft, NO composed answer. escalate=True.
                      A human navigator answers, from approved sources
                      only — the system never diagnoses, never advises
                      on treatment, medication, dose, or prognosis,
                      and never interprets a personal result.
  - sensitive      -> NO AI draft. Routed to a human. escalate=True
  - routine        -> The conversation may proceed. Medical
                      explanations inside routine conversation still
                      come ONLY from approved templates (brain_demo),
                      never free-generated text.

Design rules that matter (see taxonomy.md for the full taxonomy):

  1. A medication NAME alone never escalates. Medical-advice detection
     requires advice-seeking intent (should/can I take it, stop it,
     dose, side effects, interactions, personal result interpretation,
     prognosis, procedure-prep instructions).
  2. General education is routine: "¿qué es una biopsia?" (what is a
     biopsy) is exactly the plain-language explanation the product is
     allowed to give — from the approved template. Asking what MY
     result means is medical_advice.
  3. Precedence: crisis > medical_advice > sensitive > routine.
     A turn is classified by its most dangerous matching category.

Matching is done on normalized text (lowercase, accents stripped), so
"quimioterapia"/"quimio", "inglés"/"ingles" etc. match the same rules.

VOZ EXTENSIONS (marked inline; each closes a gap the ported rules
provably miss, and each is covered by a battery case):
  E1. fever_numeric_en — the ported numeric-fever rule is Spanish-only
      ("temperatura de 39"); the English "temperature of 39" slipped
      through as routine. Crisis is zero-tolerance, so the English
      form is a crisis rule here.
  E2. cure_prognosis — "Will the chemo cure me?" / "¿me va a curar?"
      is a prognosis question. Podrá's fallback keyword list caught
      it; the main classifier did not. A human answers prognosis.
  E3. grief_extended_kin — the ported grief rule covers spouse/parents/
      children in "mi X murió" order only. Siblings ("mi hermana") and
      the "murió mi X" order are the same grief disclosure.

Return shape: {"category", "escalate", "reason", "rule"} — Podrá's
three keys plus "rule" (the matched rule name, or None), which the
turn gate and the navigator panel use to show WHAT fired.
"""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# CRISIS — symptoms / emergencies / self-harm / immediate danger.
# Any match: no draft, red banner, queue jump.
# (Ported verbatim from Podrá, plus VOZ EXTENSION E1.)
# ---------------------------------------------------------------------------
CRISIS_RULES: list[tuple[str, str]] = [
    # (rule name, regex on normalized text)
    ("fever_during_treatment",
     r"\bfiebre\b|\bfever\b|\btemperatura de (38|39|40)\b"),
    ("bleeding",
     r"\bsangrando\b|\bsangrado\b|\bbleeding\b|\bsangre (en|por)\b|"
     r"\bvomit\w* sangre\b|\bblood in\b"),
    ("chest_pain_or_breathing",
     r"\bdolor (en|del|de) (el )?pecho\b|\bchest pain\b|"
     r"\bme duele (mucho |fuerte |el |mucho el )?pecho\b|"
     r"\bno puedo respirar\b|\bcan'?t breathe\b|\bcannot breathe\b|"
     r"\bme cuesta respirar\b|\bdificultad para respirar\b|"
     r"\btrouble breathing\b|\bshort(ness)? of breath\b"),
    ("self_harm",
     r"\bno quiero vivir\b|\bquiero morir\b|\bquitarme la vida\b|"
     r"\bsuicid\w*\b|\bkill myself\b|\bend my life\b|"
     r"\bno vale la pena vivir\b|\bhacerme dano\b"),
    ("emergency_state",
     r"\bemergencia\b|\bemergency\b|\bme (estoy )?desmay\w*\b|"
     r"\bfaint\w*\b|\bconvulsion\w*\b|\bseizure\b|\binconsciente\b|"
     r"\bunconscious\b|\bllamen al 911\b|\bcall 911\b"),
    ("uncontrolled_symptoms",
     r"\bdolor (insoportable|que no aguanto|intenso que)\b|"
     r"\bvomitos? que no paran?\b|\bcan'?t stop vomiting\b|"
     r"\bvomitando sin parar\b|\bunbearable pain\b"),
    ("immediate_danger",
     r"\bme esta (golpeando|pegando) ahora\b|"
     r"\btengo miedo de que me mate\b|\bhe is going to kill me\b"),
    # VOZ EXTENSION E1: English numeric fever (ported rule was ES-only).
    ("fever_numeric_en",
     r"\btemperature of (38|39|40)\b|\btemp of (38|39|40)\b"),
]

# ---------------------------------------------------------------------------
# MEDICAL ADVICE — diagnosis / treatment / medication / prognosis /
# personal-result interpretation / procedure-prep instructions.
# Requires advice-seeking INTENT; a drug name mentioned in passing
# (e.g. in a transport question) does NOT match any rule here.
# (Ported verbatim from Podrá, plus VOZ EXTENSION E2.)
# ---------------------------------------------------------------------------
MEDICAL_RULES: list[tuple[str, str]] = [
    ("personal_result_interpretation",
     r"\bque significa (este|mi|el) resultado\b|"
     r"\bque significa\w* (mi )?(analisis|estudio|resultado)\b|"
     r"\b(resultado|analisis|estudio|informe)\b[^.]{0,80}\bque significa\b|"
     r"\bque significa (esto|eso|este valor|este numero)\b|"
     r"\bwhat does (this|my) (result|scan|test|report) mean\b|"
     r"\binterpret\w* (mi|este|my|this) (resultado|result|analisis)\b|"
     r"\bes cancer\?|\bis (it|this) cancer\b|"
     r"\b(es|es un) (tumor )?(maligno|benigno)\b|"
     r"\bsalio (alto|positivo|anormal)\w* (en|mi) (analisis|resultado|estudio)\b|"
     r"\bmi (analisis|resultado) (salio|dice|marca)\b"),
    ("prognosis",
     r"\bcuanto tiempo me queda\b|\bhow long do i have\b|"
     r"\bme voy a morir\b|\bvoy a sobrevivir\b|"
     r"\bprobabilidades de (curarme|sobrevivir|vivir)\b|"
     r"\bchances of (surviving|being cured)\b|\besperanza de vida\b|"
     r"\blife expectancy\b"),
    ("medication_advice_intent",
     r"\b(debo|puedo|podria|quiero) (tomar|dejar|suspender|seguir tomando|cambiar|tomarme)\b|"
     r"\bshould i (take|stop|keep taking|change|continue)\b|"
     r"\bcan i take\b|\bdo i (take|stop)\b|"
     r"\bdejar de tomar\b|\bstop taking\b|\bstopping (my|the) medication\b|"
     r"\bsuspender (mi|el|la) (medicamento|tratamiento|pastilla)\b|"
     r"\binteract\w* (con|with) (mi|my|el) (tratamiento|medication)\b|"
     r"\b(es|sera) (seguro|peligroso) tomar\b|\bsafe to take\b"),
    ("dosage",
     r"\b(dosis|dosage|dose) de\b|\bcuantos? (mg|miligramos|pastillas) (debo|puedo|tomo)\b|"
     r"\bhow (much|many milligrams)\b|\b\d+\s?mg (debo|puedo|should)\b"),
    ("side_effect_management",
     r"\b(como (manejo|controlo|alivio)|que hago con) (los |las |mis )?(efectos secundarios|nauseas|vomitos|malestares)\b|"
     r"\bhow do i (manage|handle|relieve) (the )?(side effects|nausea)\b|"
     r"\bes normal (tener|sentir|que me|que tenga)\b|"
     r"\bis it normal to (feel|have|be)\b"),
    ("treatment_decision",
     r"\bdebo (hacerme|hacer|aceptar|seguir con) (la |el )?(quimioterapia|cirugia|tratamiento|radiacion)\b|"
     r"\bshould i (do|get|have|accept) (chemo|chemotherapy|surgery|radiation|the treatment)\b|"
     r"\bque tratamiento es mejor\b|\bwhich treatment is (best|better)\b|"
     r"\bnecesito (cirugia|operarme|quimioterapia)\?\b|"
     r"\bdo i need (surgery|chemo|chemotherapy|radiation)\b|"
     r"\balternativas? de tratamiento\b|\btreatment options for me\b"),
    ("procedure_prep_instruction",
     r"\bnecesito ayunar\b|\bayunar antes de\b|\bayuno antes de\b|"
     r"\bdo i need to fast\b|\bfasting before\b|"
     r"\bpuedo comer antes de (la|el|mi)\b|\bcan i eat before\b|"
          r"\bque (debo|tengo que) hacer antes de (la|el|mi) (biopsia|cirugia|estudio|operacion)\b|"
     r"\bwhat should i do before (the|my) (biopsy|surgery|scan|procedure)\b|"
     r"\b(prepararme|preparacion) para (la|el|mi) (biopsia|cirugia|operacion)\b.*\?$"),
    # VOZ EXTENSION E2: cure questions are prognosis questions.
    ("cure_prognosis",
     r"\bwill (it|this|the treatment|the chemo|chemotherapy) cure\b|"
     r"\bis (it|this) curable\b|\bme va a curar\b|"
     r"\bse puede curar\b|\btiene cura\b"),
]

# ---------------------------------------------------------------------------
# SENSITIVE — routed to a human, no AI draft: acute distress, financial
# desperation, abuse, grief, immigration fear. Distinct from routine
# barrier mentions (e.g. "tengo miedo de la biopsia" is a ROUTINE fear
# barrier the navigator workflow handles with a draft).
# (Ported verbatim from Podrá, plus VOZ EXTENSION E3.)
# ---------------------------------------------------------------------------
SENSITIVE_RULES: list[tuple[str, str]] = [
    ("acute_distress",
     r"\bno puedo parar de llorar\b|\bcan'?t stop crying\b|"
     r"\bcrisis de ansiedad\b|\bataque de panico\b|\bpanic attack\b|"
     r"\bestoy desesperad[oa]\b|\bi am desperate\b|"
     r"\bno aguanto mas\b|\bi can'?t take (it|this) anymore\b|"
     r"\bme siento (sola y )?abandonad[oa]\b|\bi feel abandoned\b"),
    ("financial_desperation",
     r"\bno tengo ni para\b|\bno tengo (dinero )?para comer\b|"
     r"\bno puedo pagar (la renta|el alquiler|el rent)\b|"
     r"\bcan'?t afford (rent|food|to eat)\b|"
     r"\b(me van a|van a) desalojar\b|\bbeing evicted\b|\beviction\b|"
     r"\bsin hogar\b|\bhomeless\b|\bno tengo para (el|la|los|las|pagar)\b"),
    ("abuse",
     r"\bme pega\b|\bme golpea\b|\bme maltrata\b|\babuso (de|domestico)\b|"
     r"\bdomestic violence\b|\bhits me\b|\bbeats me\b|\babuse[sd]?\b"),
    ("grief",
     r"\b(mi )?(esposo|esposa|madre|padre|hijo|hija|marido) (fallecio|murio|acaba de morir)\b|"
     r"\bmy (husband|wife|mother|father|son|daughter) (died|just died|passed away)\b|"
     r"\bestoy de luto\b|\bi am grieving\b"),
    ("immigration_fear",
     r"\bmiedo de que me deporten\b|\bafraid of (being )?deport\w*\b|"
     r"\bsoy indocumentad[oa]\b|\bi am undocumented\b|"
     r"\bmiedo de (ir|acudir) (por|porque) (mis papeles|no tengo papeles)\b"),
    # VOZ EXTENSION E3: siblings + "murió mi X" word order.
    ("grief_extended_kin",
     r"\bmi (hermana|hermano) (fallecio|murio|acaba de morir)\b|"
     r"\b(murio|fallecio) mi (hermana|hermano|esposo|esposa|madre|padre|hijo|hija|marido)\b|"
     r"\bmy (sister|brother) (died|just died|passed away)\b"),
]


def _match_any(rules: list[tuple[str, str]], normalized: str):
    for name, pattern in rules:
        if re.search(pattern, normalized):
            return name
    return None


def classify_message(text: str) -> dict:
    """Classify one patient turn BEFORE any reply is composed.

    Returns {"category": "crisis"|"medical_advice"|"sensitive"|"routine",
             "escalate": bool, "reason": str,
             "rule": str | None}  (the matched rule's name)
    """
    if not text or not text.strip():
        return {
            "category": "routine",
            "escalate": False,
            "rule": None,
            "reason": "Empty turn — nothing to compose; the conversation "
                      "workflow handles it as routine intake.",
        }

    normalized = _normalize(text)

    rule = _match_any(CRISIS_RULES, normalized)
    if rule:
        return {
            "category": "crisis",
            "escalate": True,
            "rule": rule,
            "reason": (
                f"Crisis rule '{rule}' matched. NO draft and NO composed "
                "reply. Show the red banner (call 911 / the care team "
                "now) and jump this case to the front of the navigator "
                "queue."
            ),
        }

    rule = _match_any(MEDICAL_RULES, normalized)
    if rule:
        return {
            "category": "medical_advice",
            "escalate": True,
            "rule": rule,
            "reason": (
                f"Medical-advice rule '{rule}' matched (advice-seeking "
                "intent about diagnosis, treatment, medication, "
                "prognosis, personal results, or procedure prep). NO "
                "draft and NO composed answer. A human navigator "
                "answers using approved sources only."
            ),
        }

    rule = _match_any(SENSITIVE_RULES, normalized)
    if rule:
        return {
            "category": "sensitive",
            "escalate": True,
            "rule": rule,
            "reason": (
                f"Sensitive rule '{rule}' matched (acute distress, "
                "financial desperation, abuse, grief, or immigration "
                "fear). Routed to a human navigator; no AI draft is "
                "sent."
            ),
        }

    return {
        "category": "routine",
        "escalate": False,
        "rule": None,
        "reason": (
            "No crisis, medical-advice, or sensitive rule matched. The "
            "conversation may proceed; medical explanations come only "
            "from approved templates, and a human navigator still "
            "reviews and approves the handoff summary before anything "
            "reaches the patient."
        ),
    }


# ---------------------------------------------------------------------------
# Escalation payloads — the ONLY things an escalated turn may produce.
# The banner text is Podrá's shipped banner (English-first UI, Spanish
# line included); the crisis spoken line is ARCHITECTURE.md §1.5
# verbatim. Medical/sensitive spoken lines follow the same pattern:
# fixed, human-routing, no clinical content.
# ---------------------------------------------------------------------------
CRISIS_BANNER: dict = {
    "kind": "crisis",
    "headline": "🚨 If this is an emergency, call 911 now.",
    "body": (
        "If you have fever, bleeding, or feel very ill, call 911 or "
        "your care team now. Do not wait for a message."
    ),
    "headline_es": "🚨 Si esto es una emergencia, llama al 911 ahora.",
    "body_es": (
        "Si tienes fiebre, sangrado o te sientes muy mal, llama al 911 "
        "o a tu equipo de cuidado ahora. No esperes un mensaje."
    ),
}

_ESCALATION_LINES: dict[str, dict[str, str]] = {
    "crisis": {
        "en": (
            "This sounds like an emergency. Call 911 or your care "
            "team now. I'm stopping here and sending this straight to "
            "a human navigator."
        ),
        "es": (
            "Esto suena como una emergencia. Llama al 911 o a tu "
            "equipo de cuidado ahora. Me detengo aquí y envío esto "
            "directamente a una navegadora humana."
        ),
    },
    "medical_advice": {
        "en": (
            "That question needs a person, not a guess — it is about "
            "your own care. I'm sending it straight to your navigator, "
            "who answers from approved information."
        ),
        "es": (
            "Esa pregunta necesita una persona, no una suposición — "
            "es sobre su propio cuidado. La envío directamente a su "
            "navegadora, que responde con información aprobada."
        ),
    },
    "sensitive": {
        "en": (
            "Thank you for telling me. This deserves a person, not a "
            "recording. I'm sending this straight to your navigator."
        ),
        "es": (
            "Gracias por contármelo. Esto merece una persona, no una "
            "grabación. Lo envío directamente a su navegadora."
        ),
    },
}


def escalation_payload(category: str, language: str = "en") -> dict:
    """The fixed payload an escalated turn produces.

    {"banner": CRISIS_BANNER copy for crisis, else None,
     "spoken": the one line the companion may say, in the session
               language,
     "spoken_gloss": the English line when the spoken line is Spanish
                     (the navigator panel always shows English), else
                     None}
    """
    lines = _ESCALATION_LINES[category]
    lang = "es" if (language or "en").lower().startswith("es") else "en"
    return {
        "banner": dict(CRISIS_BANNER) if category == "crisis" else None,
        "spoken": lines[lang],
        "spoken_gloss": lines["en"] if lang == "es" else None,
    }


if __name__ == "__main__":
    import sys

    msg = " ".join(sys.argv[1:]) or (
        "Me dijeron que necesito una biopsia y no entiendo, "
        "y no tengo transporte."
    )
    print(classify_message(msg))
