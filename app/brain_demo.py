"""Voz Navega — deterministic demo brain ($0, no API key).

This is the content + turn engine behind DEMO MODE. It follows the
conversation state machine in ARCHITECTURE.md §1.2:

    GREETING → INTAKE → DISCOVERY → EXPLAIN → QUESTIONS → RESOURCES
             → HANDOFF → CLOSED        (ESCALATED is reachable from
                                        every state, via the safety
                                        layer, never via this brain)

Layering (ARCHITECTURE.md §2.1): the safety classifier
(app/safety/, sibling-owned) runs on every patient turn BEFORE this
brain composes a reply, and the approval gate is enforced server-side
in main.py. This module owns only deterministic content and turn
decisions: barrier detection (keyword layer + discovery probes),
approved explanation templates (EN/ES, spoken length), base question
lists, one derived question per confirmed barrier, probe scripts,
resource offers (via app/resources.py), and the handoff summary.

Patterns ported from Podrá Navega's app/barriers.py (taxonomy, keyword
detection, templates, sample directory) and extended for conversation:
probe scripts, ``confirmed_by`` evidence tagging ("stated" vs "probe"),
spoken-turn chunking, and bilingual reply composition — every Spanish
companion turn is built from the same segments as its English gloss, so
the navigator panel's English gloss always matches what was said.

All patient data is fictional. Medical content is information and
preparation only, drawn from the fixed approved templates below —
never free-generated, never diagnosis or treatment advice.
"""

from __future__ import annotations

import re

from app.resources import resources_for

# ---------------------------------------------------------------------------
# Taxonomy + keyword detection (ported from Podrá barriers.py, extended)
# ---------------------------------------------------------------------------

BARRIER_TAXONOMY = [
    "transport",
    "cost",
    "childcare",
    "work_schedule",
    "fear",
    "language",
    "health_literacy",
    "other",
]

_BARRIER_KEYWORDS: dict[str, list[str]] = {
    "transport": [
        "transporte", "transport", "no tengo transporte", "no tengo carro",
        "no car", "ride", "bus", "cómo llegar", "como llegar", "get there",
        "getting there", "conducir", "driver", "don't drive", "do not drive",
        "no manejo", "sin carro",
    ],
    "cost": [
        "dinero", "money", "cuesta", "cost", "pagar", "pay for", "seguro",
        "insurance", "caro", "expensive", "afford", "factura", "bill",
    ],
    "childcare": [
        "niños", "ninos", "hijos", "kids", "children", "grandkids",
        "grandchildren", "nietos", "cuidar a mis", "childcare", "bebé",
        "bebe", "baby", "watch my grandkids", "watch my kids",
    ],
    "work_schedule": [
        "trabajo", "work", "jefe", "boss", "turno", "shift", "falto al",
        "permiso en el trabajo", "time off", "my job",
    ],
    "fear": [
        "miedo", "temor", "afraid", "scared", "nervios", "nerviosa",
        "nervioso", "ansiedad", "anxious", "preocupada", "preocupado",
        "worried",
    ],
    "language": [
        "no hablo inglés", "no hablo ingles", "don't speak english",
        "intérprete", "interprete", "interpreter", "solo español",
        "solo espanol", "in english",
    ],
    "health_literacy": [
        "no entiendo", "don't understand", "no sé qué es", "no se que es",
        "qué significa", "que significa", "what does", "qué es una",
        "que es una", "qué es un", "no comprendo", "don't know what",
        "don't really know", "no sé qué", "not sure what",
    ],
    # Caregiving for an adult family member — the barrier the patient
    # rarely names as a "barrier" at all (ARCHITECTURE.md golden B).
    "other": [
        "cuidar a mi mamá", "cuidar a mi madre", "cuidar a mi papá",
        "cuidar a mi padre", "cuidar a mi abuela", "cuido a mi mamá",
        "cuido a mi madre", "care for my mother", "care for my mom",
        "take care of my mother", "take care of my mom",
    ],
}

_SPANISH_MARKERS = [
    " no ", " una ", " un ", " que ", " mi ", " me ", " tengo ", " necesito ",
    " entiendo ", " dijeron ", " señora ", " por favor", " gracias", " cita ",
    "¿", "á", "é", "í", "ó", "ú", "ñ",
]

# A family member's work is family logistics, NOT the patient's own
# work_schedule barrier: "My daughter works, and I don't drive" evidences
# transport, and the daughter's job is noted in the summary — it must not
# be recorded as the patient's barrier (see the golden conversations).
_FAMILY_SUBJECT = re.compile(
    r"\b(my|mi)\s+(daughter|son|husband|wife|sister|brother|hija|hijo|"
    r"esposo|esposa|hermana|hermano|mamá|mama|madre|papá|papa|padre)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Podrá's rule: >= 2 Spanish markers -> 'es', else 'en'."""
    low = " " + text.lower() + " "
    hits = sum(1 for marker in _SPANISH_MARKERS if marker in low)
    return "es" if hits >= 2 else "en"


def _spanish_hits(text: str) -> int:
    low = " " + text.lower() + " "
    return sum(1 for marker in _SPANISH_MARKERS if marker in low)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_family_work_sentence(sentence: str) -> bool:
    low = sentence.lower()
    return bool(_FAMILY_SUBJECT.search(sentence)) and (
        "work" in low or "trabaj" in low
    )


def detect_barriers(text: str, confirmed_by: str = "stated") -> list[dict]:
    """Keyword-layer barrier detection. Returns
    [{barrier, evidence, confirmed_by}] with the exact patient sentence
    that evidences each barrier. ``confirmed_by`` is "stated" for the
    intake turn and "probe" for barriers surfacing as answers to a
    discovery probe (the engine passes it in)."""
    found: list[dict] = []
    sentences = _sentences(text) or [text.strip()]
    low_text = text.lower()
    for barrier in BARRIER_TAXONOMY:
        keywords = _BARRIER_KEYWORDS[barrier]
        for sentence in sentences:
            if barrier == "work_schedule" and _is_family_work_sentence(sentence):
                continue  # someone else's job is logistics, not her barrier
            if any(kw in sentence.lower() for kw in keywords):
                found.append({
                    "barrier": barrier,
                    "evidence": sentence,
                    "confirmed_by": confirmed_by,
                })
                break
        else:
            # keyword split across the message (no single sentence match)
            if barrier == "work_schedule":
                # the family-work guard applies here too: search only
                # the sentences that are about the patient herself
                haystack = " ".join(
                    s for s in sentences
                    if not _is_family_work_sentence(s)).lower()
            else:
                haystack = low_text
            if any(kw in haystack for kw in keywords):
                found.append({
                    "barrier": barrier,
                    "evidence": text.strip()[:160],
                    "confirmed_by": confirmed_by,
                })
    return found


def family_logistics_notes(text: str) -> list[str]:
    """Sentences where a family member's work shapes the patient's day.
    Not barriers — they are recorded in the handoff summary as family
    logistics (ARCHITECTURE.md golden B)."""
    return [s for s in _sentences(text) if _is_family_work_sentence(s)]


# ---------------------------------------------------------------------------
# Topic slots
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("biopsy", ["biopsia", "biopsy"]),
    ("chemotherapy", ["quimioterapia", "chemotherapy", "quimio"]),
    ("surgery", ["cirugía", "cirugia", "surgery", "operación", "operacion"]),
    ("results", ["resultados", "results", "resultado"]),
]

_TOPIC_NAMES = {
    "biopsy": {"en": "the biopsy", "es": "la biopsia"},
    "chemotherapy": {"en": "the chemotherapy", "es": "la quimioterapia"},
    "surgery": {"en": "the surgery", "es": "la cirugía"},
    "results": {"en": "your results", "es": "sus resultados"},
    "other": {"en": "your next step", "es": "su próximo paso"},
}

_WEEKDAYS = (
    "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    "lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo"
)
_APPOINTMENT_RE = re.compile(
    rf"\b(?:on\s+)?({_WEEKDAYS})\b", re.IGNORECASE
)


def detect_topic(text: str) -> str | None:
    low = text.lower()
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(kw in low for kw in keywords):
            return topic
    return None


def detect_appointment(text: str) -> str | None:
    match = _APPOINTMENT_RE.search(text)
    if match:
        return match.group(1).capitalize()
    return None


# ---------------------------------------------------------------------------
# Approved content templates (information / preparation only — §3.2)
# Every companion line exists as an EN/ES pair; the reply is composed from
# segments so the English gloss of a Spanish turn is the same content.
# ---------------------------------------------------------------------------

_GREETING = {
    "en": "Hi, I'm Voz, your navigation companion. I explain your next "
          "steps in plain words and help you get ready. I don't diagnose "
          "or treat — your care team does that. What's on your mind today?",
    "es": "Hola, soy Voz, su compañera de navegación. Le explico sus "
          "próximos pasos con palabras simples y le ayudo a prepararse. "
          "¿Qué le preocupa hoy?",
}
_GREETING_GLOSS_EN = (
    "Hello, I'm Voz, your navigation companion. I explain your next steps "
    "in simple words and help you prepare. What is worrying you today?"
)

_EXPLANATIONS = {
    "biopsy": {
        "en": "Now the biopsy, in plain words: the doctor takes a very "
              "small sample of tissue and a lab checks it. That is how "
              "your team finds out exactly what is happening, so they can "
              "plan your care.",
        "es": "Ahora, la biopsia con palabras simples: el doctor toma "
              "una muestra muy pequeña de tejido y un laboratorio la "
              "revisa. Así su equipo sabe exactamente qué está pasando y "
              "puede planear su cuidado.",
    },
    "chemotherapy": {
        "en": "Now, chemotherapy in plain words: it is a treatment with "
              "medicines that work to stop cancer cells from growing. "
              "Everyone receives it differently, and your medical team "
              "will explain your plan.",
        "es": "Ahora, la quimioterapia con palabras simples: es un "
              "tratamiento con medicamentos que busca detener el "
              "crecimiento de las células del cáncer. Cada persona la "
              "recibe de forma distinta, y su equipo médico le explicará "
              "su plan.",
    },
    "surgery": {
        "en": "Now, the surgery in plain words: it is an operation your "
              "doctor does as part of your care. Your team will explain "
              "why they recommend it and how to get ready, and your "
              "navigator will help you prepare your questions.",
        "es": "Ahora, la cirugía con palabras simples: es una operación "
              "que hace el doctor como parte de su cuidado. Su equipo le "
              "explicará por qué la recomienda y cómo prepararse.",
    },
    "results": {
        "en": "Now, waiting for results, in plain words: it is normal "
              "for this part to feel hard. When the results are ready, "
              "your care team will explain them to you, and your "
              "navigator can help you write down what to ask.",
        "es": "Esperar resultados puede causar mucha preocupación, y eso "
              "es normal. Cuando lleguen, su equipo médico se los "
              "explicará, y su navegadora puede ayudarle a anotar qué "
              "preguntar.",
    },
    "other": {
        "en": "Your next step, in plain words: your care team will guide "
              "you through it one part at a time, and your navigator "
              "will help you get ready and write down your questions.",
        "es": "Su próximo paso, con palabras simples: su equipo médico "
              "le guiará una parte a la vez, y su navegadora le ayudará "
              "a prepararse y a anotar sus preguntas.",
    },
}

_BASE_QUESTIONS = {
    "biopsy": {
        "en": [
            "What exactly will happen during the biopsy?",
            "How long will the biopsy take?",
            "When and how will I get my results?",
            "What should I bring with me on the day?",
            "Who can I call if I have questions before my appointment?",
        ],
        "es": [
            "¿Qué va a pasar exactamente durante la biopsia?",
            "¿Cuánto tiempo dura la biopsia?",
            "¿Cuándo y cómo voy a recibir los resultados?",
            "¿Qué debo llevar el día de la cita?",
            "¿A quién puedo llamar si tengo preguntas antes de mi cita?",
        ],
    },
    "chemotherapy": {
        "en": [
            "How will I get the chemotherapy, and how long is each "
            "session?",
            "What side effects should I watch for, and when should I "
            "call?",
            "How many sessions will I have?",
            "Can someone come with me to my sessions?",
            "Who can I call if I have questions between sessions?",
        ],
        "es": [
            "¿Cómo voy a recibir la quimioterapia y cuánto dura cada "
            "sesión?",
            "¿Qué efectos secundarios debo vigilar y cuándo debo llamar?",
            "¿Cuántas sesiones voy a tener?",
            "¿Puede alguien acompañarme a mis sesiones?",
            "¿A quién puedo llamar si tengo preguntas entre sesiones?",
        ],
    },
    "surgery": {
        "en": [
            "Why do you recommend this surgery for me?",
            "How long will I be in the hospital?",
            "How long is the recovery?",
            "What do I need to arrange at home for after?",
            "Who can I call if I have questions before the surgery?",
        ],
        "es": [
            "¿Por qué me recomienda esta cirugía?",
            "¿Cuánto tiempo estaré en el hospital?",
            "¿Cuánto dura la recuperación?",
            "¿Qué necesito arreglar en mi casa para después?",
            "¿A quién puedo llamar si tengo preguntas antes de la "
            "cirugía?",
        ],
    },
    "results": {
        "en": [
            "When will my results be ready?",
            "How will I receive them — call, visit, or message?",
            "Who will explain what they mean?",
            "What happens after the results, either way?",
            "Who can I call while I wait?",
        ],
        "es": [
            "¿Cuándo estarán listos mis resultados?",
            "¿Cómo los voy a recibir: llamada, visita o mensaje?",
            "¿Quién me va a explicar lo que significan?",
            "¿Qué sigue después de los resultados, pase lo que pase?",
            "¿A quién puedo llamar mientras espero?",
        ],
    },
    "other": {
        "en": [
            "When is my appointment and where do I need to go?",
            "What will happen during the test or appointment?",
            "Do I need to do anything to prepare?",
            "When and how will I receive the results?",
            "Who can I call if I have questions or a problem?",
        ],
        "es": [
            "¿Cuándo es mi cita y dónde tengo que llegar?",
            "¿Qué va a pasar durante el examen o la cita?",
            "¿Necesito hacer algo para prepararme?",
            "¿Cuándo y cómo voy a recibir los resultados?",
            "¿A quién puedo llamar si tengo preguntas o un problema?",
        ],
    },
}

# One derived question per confirmed barrier (ARCHITECTURE.md §3.2.1).
_BARRIER_QUESTIONS = {
    "transport": {
        "en": "Can I get help with a ride to my appointment?",
        "es": "¿Pueden ayudarme con transporte para mi cita?",
    },
    "cost": {
        "en": "What help is there if I cannot pay for my treatment?",
        "es": "¿Qué ayuda hay si no puedo pagar mi tratamiento?",
    },
    "childcare": {
        "en": "What can I do about care for my children or grandchildren "
              "during my appointment?",
        "es": "¿Qué puedo hacer para el cuidado de mis niños durante mi "
              "cita?",
    },
    "work_schedule": {
        "en": "Can I get a note for my job for the day of my "
              "appointment?",
        "es": "¿Pueden darme una nota para mi trabajo para el día de mi "
              "cita?",
    },
    "fear": {
        "en": "What can help me feel calmer about this step?",
        "es": "¿Qué puede ayudarme a sentirme más tranquila con este "
              "paso?",
    },
    "language": {
        "en": "Can I have an interpreter at my appointment?",
        "es": "¿Puedo tener un intérprete en mi cita?",
    },
    "health_literacy": {
        "en": "Can you explain my next step one more time in simple "
              "words?",
        "es": "¿Pueden explicarme mi próximo paso otra vez con palabras "
              "simples?",
    },
    "other": {
        "en": "Who can help me with care duties at home during my "
              "treatment?",
        "es": "¿Quién puede ayudarme con los cuidados en mi casa "
              "durante mi tratamiento?",
    },
}

# Short plain names used when the companion reads barriers back out loud
# ("the companion remembers out loud", ARCHITECTURE.md §1.1 rule 4).
_BARRIER_NAMES = {
    "transport": {"en": "the ride", "es": "el transporte"},
    "cost": {"en": "the cost", "es": "el costo"},
    "childcare": {"en": "childcare", "es": "el cuidado de los niños"},
    "work_schedule": {"en": "your work schedule",
                      "es": "su horario de trabajo"},
    "fear": {"en": "the fear", "es": "el miedo"},
    "language": {"en": "language", "es": "el idioma"},
    "health_literacy": {"en": "understanding it all",
                        "es": "entenderlo bien"},
    "other": {"en": "caring for your family", "es": "el cuidado de su "
                                                   "familia"},
}

# Discovery probes — exactly ONE per turn (ARCHITECTURE.md §1.2). Each
# probe covers one life area; the engine walks uncovered areas only.
_PROBES = {
    "open_worry": {
        "en": "Before I explain {topic}, one question: what worries you "
              "most{day}?",
        "es": "Antes de explicarle, una pregunta: ¿qué es lo que más le "
              "preocupa?",
    },
    "support_home": {
        "en": "One question: who is with you at home during your "
              "treatment?",
        "es": "Una pregunta: ¿quién le acompaña en su casa durante el "
              "tratamiento?",
    },
    "transport": {
        "en": "One question: how will you get to your appointment?",
        "es": "Una pregunta: ¿cómo va a llegar a su cita?",
    },
    "family_duties": {
        "en": "One question: who depends on you at home during the day?",
        "es": "Una pregunta: ¿quién depende de usted en casa durante "
              "el día?",
    },
    "work": {
        "en": "One question: will your work schedule make that day hard?",
        "es": "Una pregunta: ¿su horario de trabajo le complica ese día?",
    },
    "cost": {
        "en": "One question: is the cost of this step on your mind?",
        "es": "Una pregunta: ¿le preocupa el costo de este paso?",
    },
}

# Which confirmed barriers "cover" a probe area, so the engine never asks
# about a life area the patient has already surfaced.
_PROBE_COVERAGE = {
    "support_home": {"other", "childcare"},
    "transport": {"transport"},
    "family_duties": {"childcare", "other"},
    "work": {"work_schedule"},
    "cost": {"cost"},
}
_PROBE_ORDER = ["transport", "family_duties", "work", "support_home", "cost"]
_PROBE_BUDGET = 3

_PRACTICAL_BARRIERS = {"transport", "cost", "childcare", "work_schedule"}

_THANKS = {
    "en": "Thank you for telling me.",
    "es": "Gracias por decírmelo.",
}
_EMPATHY_FEAR = {
    "en": "That's a lot to take in, and feeling scared is normal.",
    "es": "Sé que es mucho para asimilar, y sentir miedo es normal.",
}
_COST_ACK = {
    "en": "The worry about cost is very common, and your navigator can "
          "look for help with that.",
    "es": "La preocupación por el costo es muy común, y su navegadora "
          "puede buscar ayuda para eso.",
}
_UNDERSTANDING_CHECK = {
    "en": "Want me to say that part again, or shall we build your "
          "questions for the doctor?",
    "es": "¿Quiere que le repita esa parte, o preparamos sus preguntas "
          "para el doctor?",
}

# Approved template answer to a general-education question about a
# procedure ("Will it hurt?"). Personal prep instructions are NOT
# template content — they classify as medical_advice and escalate in the
# safety layer before this brain ever sees the turn.
_COMFORT_ANSWER = {
    "en": "Most people say they feel pressure more than pain. Your care "
          "team will tell you exactly what to expect{day} — and that is "
          "a good question to ask them. I am adding it to your list.",
    "es": "La mayoría de las personas dice que siente más presión que "
          "dolor. Su equipo médico le dirá exactamente qué esperar — y "
          "es una buena pregunta para ellos. La agrego a su lista.",
}
_VERBATIM_ADD = {
    "en": "I'm adding that question to your list, just as you said it.",
    "es": "Esa pregunta va a su lista, tal como la dijo.",
}
_ADDED = {
    "en": "Added. Anything else you want on the list?",
    "es": "Agregada. ¿Quiere agregar algo más?",
}
_READBACK_LEAD = {
    "en": "Here is your question list. I will read the first one — the "
          "rest are on your screen: “{first}” Want to add anything?",
    "es": "Su lista de preguntas está en la pantalla. Le leo la primera: "
          "«{first}» ¿Quiere agregar algo más?",
}
_OFFER_CHECK = {
    "en": "Your navigator checks each one before anything is booked — "
          "nothing is final yet.",
    "es": "Su navegadora verifica cada uno antes de que se use — nada "
          "es final todavía.",
}
_HANDOFF_LINE = {
    "en": "I've put it all together for your navigator — your concerns, "
          "your questions, and the help you need. She reviews it before "
          "anything is sent. You don't have to carry this alone.",
    "es": "Preparé todo para su navegadora: sus preocupaciones, sus "
          "preguntas y la ayuda que necesita. Ella lo revisa antes de "
          "que se envíe cualquier cosa. No está sola en esto.",
}
_PARKED_LINE = {
    "en": "Your navigator is reviewing everything now. She will take it "
          "from here — you don't have to carry this alone.",
    "es": "Su navegadora está revisando todo ahora. Ella se encarga "
          "desde aquí — no está sola en esto.",
}
_CLOSING = {
    "en": "Your navigator reviewed everything, and it is all set. Your "
          "questions and the help you asked for are on their way. Take "
          "care.",
    "es": "Su navegadora revisó todo y ya está listo. Sus preguntas y "
          "la ayuda que pidió van en camino. Cuídese.",
}
_INTAKE_ASK = {
    "en": "Thank you. What did your care team say your next step is — "
          "for example, a biopsy, chemotherapy, surgery, or results?",
    "es": "Gracias. ¿Qué le dijo su equipo médico que sigue — por "
          "ejemplo, una biopsia, quimioterapia, cirugía o resultados?",
}
_ESCALATED_LINE = {
    "en": "I'm stopping here and sending this straight to a human "
          "navigator.",
    "es": "Me detengo aquí y envío esto directamente a una navegadora "
          "humana.",
}


# ---------------------------------------------------------------------------
# Session engine — the §1.2 state machine over the templates above.
# A session is a plain dict (the store layer owns persistence/threading;
# there is none — in-memory by design). Safety classification happens
# BEFORE handle_turn is called; an ESCALATED session never drafts.
# ---------------------------------------------------------------------------

_session_counter = [0]

_CLOSURE_MARKERS = [
    "that's all", "that is all", "nothing", "nada más", "nada mas",
    "así está bien", "asi esta bien", "está bien", "esta bien",
    "that's good", "that is good", "i'm good", "im good",
    "no quiero agregar", "no, así", "no, asi",
]
_REPEAT_MARKERS = [
    "say that again", "say it again", "repeat", "otra vez", "repita",
    "repítelo", "repitelo",
]
_COMFORT_WORDS = ["hurt", "pain", "dolor", "duele", "duela"]
_COST_WORDS = ["pagar", "pay", "cuesta", "cost", "dinero", "money",
               "afford", "cobran"]
_ENGLISH_MARKERS = [" the ", " i ", " my ", " is ", " and ", " what ",
                    " how ", " you "]


def new_session(session_id: str | None = None) -> dict:
    if session_id is None:
        _session_counter[0] += 1
        session_id = f"VOZ-{_session_counter[0]:04d}"
    return {
        "id": session_id,
        "fictional": True,
        "demo_mode": True,
        "language": None,
        "state": "GREETING",
        "state_history": ["GREETING"],
        "turns": [],
        "slots": {"topic": None, "appointment_text": None},
        "barriers_found": [],
        "barrier_checklist": {name: False for name in BARRIER_TAXONOMY},
        "question_list": None,
        "question_list_en": None,
        "resources": [],
        "resources_offered": False,
        "summary": None,
        "approval_status": None,
        "approval_record": None,
        "probes_asked": 0,
        "probes_used": [],
        "explanation_delivered": False,
        "notes": [],
        "_first_patient_turn": None,
    }


def _record_state(session: dict, state: str) -> None:
    session["state"] = state
    if session["state_history"][-1] != state:
        session["state_history"].append(state)


def _join_names(names: list[str], lang: str) -> str:
    if len(names) == 1:
        return names[0]
    joiner = " y " if lang == "es" else " and "
    if len(names) == 2:
        return names[0] + joiner + names[1]
    comma = ", ".join(names[:-1])
    return f"{comma}{',' if lang == 'en' else ''}{joiner}{names[-1]}"


def _ack_segment(new_barriers: list[dict], lang: str) -> str:
    names = [_BARRIER_NAMES[b["barrier"]][lang] for b in new_barriers]
    joined = _join_names(names, lang)
    if lang == "es":
        return f"Lo anoto: {joined}."
    if len(names) == 1:
        return f"I'll write that down — {joined}."
    if len(names) == 2:
        return f"I'll write both of those down — {joined}."
    return f"I'll write those down — {joined}."


def _offer_segment(resources: list[dict], lang: str) -> str:
    if lang == "es":
        offers = "; ".join(r["offer_es"] for r in resources)
        return f"Y le ofrezco esto: {offers}. {_OFFER_CHECK['es']}"
    number_words = ["One", "Two", "Three", "Four"]
    lead = {1: "One offer.", 2: "Two offers.", 3: "Three offers."}.get(
        len(resources), "Some offers.")
    items = " ".join(
        f"{number_words[i]}: {r['offer_en']}."
        for i, r in enumerate(resources)
    )
    return f"{lead} {items} {_OFFER_CHECK['en']}"


def _render(session: dict, segments: list[tuple[str, str]]) -> tuple[str, str]:
    """Compose a companion reply from (en, es) segment pairs. Returns
    (text in the session language, English gloss). Building the gloss
    from the same segments is what guarantees they match (§2.1)."""
    lang = session["language"] or "en"
    text = " ".join(en if lang == "en" else es for en, es in segments)
    gloss = " ".join(en for en, _ in segments)
    return text, gloss


def _pair(en_text: str, es_text: str) -> tuple[str, str]:
    return (en_text, es_text)


def _finish_turn(session: dict, segments: list[tuple[str, str]]) -> dict:
    text, gloss = _render(session, segments)
    session["turns"].append({
        "speaker": "voz",
        "text": text,
        "gloss": gloss,
        "state": session["state"],
    })
    return {
        "speaker": "voz",
        "text": text,
        "gloss": gloss,
        "spoken": text,
        "state": session["state"],
        "state_history": list(session["state_history"]),
        "slots": dict(session["slots"]),
        "barriers_found": [dict(b) for b in session["barriers_found"]],
        "question_list": (list(session["question_list"])
                          if session["question_list"] is not None else None),
        "resources": [dict(r) for r in session["resources"]],
        "summary": session["summary"],
        "approval_status": session["approval_status"],
        "banner": None,
    }


def greeting_turn(session: dict, ui_language: str = "en") -> dict:
    """Emit the GREETING turn. The greeting follows the UI language; the
    session language itself is set by the patient's first turn (§1.1)."""
    text = _GREETING[ui_language]
    gloss = _GREETING_GLOSS_EN if ui_language == "es" else text
    session["turns"].append({
        "speaker": "voz", "text": text, "gloss": gloss, "state": "GREETING",
    })
    return {
        "speaker": "voz",
        "text": text,
        "gloss": gloss,
        "spoken": text,
        "state": session["state"],
        "state_history": list(session["state_history"]),
        "slots": dict(session["slots"]),
        "barriers_found": [],
        "question_list": None,
        "resources": [],
        "summary": None,
        "approval_status": None,
        "banner": None,
    }


def _merge_barriers(session: dict, text: str) -> list[dict]:
    """Run detection on one patient turn and merge new barriers into the
    session. Barriers surfacing while answering a discovery probe are
    tagged confirmed_by='probe'; all others 'stated' (§1.2)."""
    confirmed_by = "probe" if session["state"] == "DISCOVERY" else "stated"
    known = {b["barrier"] for b in session["barriers_found"]}
    new: list[dict] = []
    for hit in detect_barriers(text, confirmed_by=confirmed_by):
        if hit["barrier"] not in known:
            session["barriers_found"].append(hit)
            session["barrier_checklist"][hit["barrier"]] = True
            known.add(hit["barrier"])
            new.append(hit)
    for note in family_logistics_notes(text):
        entry = f"Family logistics: {note}"
        if entry not in session["notes"]:
            session["notes"].append(entry)
    return new


def _update_language(session: dict, text: str) -> None:
    """Language follows the patient (§1.1 rule 6): set confidently from
    the first turn; switch mid-session only on a strong signal, so a
    short reply ('No, así está bien.') never flips the session."""
    es_hits = _spanish_hits(text)
    detected = "es" if es_hits >= 2 else "en"
    if session["language"] is None:
        session["language"] = detected
        return
    if detected == session["language"]:
        return
    low = " " + text.lower() + " "
    en_hits = sum(1 for m in _ENGLISH_MARKERS if m in low)
    if (detected == "es" and es_hits >= 3) or (
            detected == "en" and en_hits >= 3):
        session["language"] = detected


def _next_probe(session: dict) -> str | None:
    """Pick the first probe whose life area is not yet covered by a
    confirmed barrier and not already asked. One probe per turn."""
    confirmed = {b["barrier"] for b in session["barriers_found"]}
    for area in _PROBE_ORDER:
        if area in session["probes_used"]:
            continue
        if _PROBE_COVERAGE[area] & confirmed:
            continue
        return area
    return None


def _first_probe(session: dict) -> str:
    """First discovery probe: if the patient already named a practical
    barrier (cost, a ride, kids, work), ask who supports her at home;
    otherwise ask the open worry-ranking probe (golden conversations)."""
    confirmed = {b["barrier"] for b in session["barriers_found"]}
    if confirmed & _PRACTICAL_BARRIERS:
        return "support_home"
    return "open_worry"


def _probe_segment(session: dict, area: str) -> tuple[str, str]:
    lang_topic = _TOPIC_NAMES[session["slots"]["topic"] or "other"]
    appt = session["slots"]["appointment_text"]
    day = f" about {appt}" if appt else ""
    en = _PROBES[area]["en"].format(topic=lang_topic["en"], day=day)
    es = _PROBES[area]["es"].format(topic=lang_topic["es"], day="")
    session["probes_used"].append(area)
    session["probes_asked"] += 1
    return _pair(en, es)


def _deliver_explain(session: dict, new_barriers: list[dict]) -> dict:
    """EXPLAIN: acknowledge what the probes surfaced, deliver the
    approved template for the topic slot, check understanding once."""
    segments: list[tuple[str, str]] = []
    if new_barriers:
        segments.append(_pair(
            _ack_segment(new_barriers, "en"),
            _ack_segment(new_barriers, "es"),
        ))
    topic = session["slots"]["topic"] or "other"
    segments.append(_pair(
        _EXPLANATIONS[topic]["en"], _EXPLANATIONS[topic]["es"]))
    segments.append(_pair(
        _UNDERSTANDING_CHECK["en"], _UNDERSTANDING_CHECK["es"]))
    session["explanation_delivered"] = True
    _record_state(session, "EXPLAIN")
    return _finish_turn(session, segments)


def _build_question_list(session: dict) -> None:
    topic = session["slots"]["topic"] or "other"
    lists: dict[str, list[str]] = {}
    for lang in ("en", "es"):
        questions = list(_BASE_QUESTIONS[topic][lang])
        for hit in session["barriers_found"]:
            derived = _BARRIER_QUESTIONS[hit["barrier"]][lang]
            if derived not in questions:
                questions.append(derived)
        lists[lang] = questions
    lang = session["language"] or "en"
    session["question_list"] = lists[lang]
    session["question_list_en"] = lists["en"]


def _append_verbatim_question(session: dict, question: str) -> None:
    if session["question_list"] is not None and \
            question not in session["question_list"]:
        session["question_list"].append(question)
    if session["question_list_en"] is not None and \
            question not in session["question_list_en"]:
        session["question_list_en"].append(question)


def _question_sentence(text: str) -> str | None:
    for sentence in _sentences(text):
        if "?" in sentence:
            return sentence
    return None


def _attach_resources(session: dict) -> None:
    if not session["resources_offered"]:
        session["resources"] = resources_for(session["barriers_found"])
        session["resources_offered"] = True
    _record_state(session, "RESOURCES")


def _enter_questions(session: dict, patient_text: str) -> dict:
    """EXPLAIN -> QUESTIONS: build the list, fold in the patient's own
    question from this turn (verbatim), answer a general-education
    question from its approved template when one applies, fast-path the
    resource offer when she asks about cost, then read the list back."""
    if session["question_list"] is None:
        _build_question_list(session)
    segments: list[tuple[str, str]] = []
    low = patient_text.lower()
    question = _question_sentence(patient_text)
    answered = False
    if question is not None:
        _append_verbatim_question(session, question)
        if any(w in low for w in _COMFORT_WORDS):
            appt = session["slots"]["appointment_text"]
            day = f" on {appt}" if appt else ""
            segments.append(_pair(
                _COMFORT_ANSWER["en"].format(day=day),
                _COMFORT_ANSWER["es"].format(day=""),
            ))
            answered = True
    _record_state(session, "QUESTIONS")
    cost_fastpath = (
        question is not None
        and any(w in low for w in _COST_WORDS)
        and session["barrier_checklist"].get("cost", False)
    )
    if cost_fastpath:
        _attach_resources(session)
        if not answered:
            segments.append(_pair(_VERBATIM_ADD["en"], _VERBATIM_ADD["es"]))
        segments.append(_pair(
            _offer_segment(session["resources"], "en"),
            _offer_segment(session["resources"], "es"),
        ))
    elif question is not None and not answered:
        segments.append(_pair(_VERBATIM_ADD["en"], _VERBATIM_ADD["es"]))
    first = session["question_list"][0] if session["question_list"] else ""
    segments.append(_pair(
        _READBACK_LEAD["en"].format(first=first),
        _READBACK_LEAD["es"].format(first=first),
    ))
    if session["state"] != "RESOURCES":
        _record_state(session, "QUESTIONS")
    return _finish_turn(session, segments)


def _is_closure(text: str) -> bool:
    low = text.lower()
    if "?" in text:
        return False
    if len(text.split()) > 8:
        return False
    if any(marker in low for marker in _CLOSURE_MARKERS):
        return True
    return low.strip() in ("no", "no.")


def _assemble_summary(session: dict) -> dict:
    topic = session["slots"]["topic"] or "other"
    lines = [
        "Voz Navega — navigator handoff summary (fictional demo patient)",
        f"Session: {session['id']} · Language: {session['language']}",
        f"Next step: {topic}"
        + (f" · Appointment mentioned: "
           f"{session['slots']['appointment_text']}"
           if session["slots"]["appointment_text"] else ""),
        f"Patient's concern (first turn): {session['_first_patient_turn']}",
        f"Explanation given: {_EXPLANATIONS[topic]['en']}",
        "Barriers found:",
    ]
    for hit in session["barriers_found"]:
        lines.append(
            f"  - {hit['barrier']} ({hit['confirmed_by']}) — "
            f"“{hit['evidence']}”")
    lines.append("Question list:")
    for i, q in enumerate(session["question_list_en"] or [], 1):
        lines.append(f"  {i}. {q}")
    lines.append(
        "Resources offered (sample directory, UNVERIFIED — verify "
        "before use):")
    for r in session["resources"]:
        lines.append(f"  - {r['name']}")
    for note in session["notes"]:
        lines.append(note)
    summary = {
        "text": "\n".join(lines),
        "topic": topic,
        "language": session["language"],
        "barriers": [dict(b) for b in session["barriers_found"]],
        "question_list_en": list(session["question_list_en"] or []),
        "resources_offered": [r["name"] for r in session["resources"]],
        "notes": list(session["notes"]),
        "fictional": True,
    }
    session["summary"] = summary
    return summary


def _finish_to_handoff(session: dict) -> dict:
    """RESOURCES (if not already offered) -> HANDOFF: assemble the
    summary and park the session at PENDING_APPROVAL. The gate itself
    (verify-then-approve, 409s) is enforced in main.py, not here."""
    segments: list[tuple[str, str]] = []
    if not session["resources_offered"]:
        _attach_resources(session)
        segments.append(_pair(
            _offer_segment(session["resources"], "en"),
            _offer_segment(session["resources"], "es"),
        ))
    _assemble_summary(session)
    segments.append(_pair(_HANDOFF_LINE["en"], _HANDOFF_LINE["es"]))
    session["approval_status"] = "PENDING_APPROVAL"
    _record_state(session, "HANDOFF")
    return _finish_turn(session, segments)


def _handle_questions(session: dict, text: str) -> dict:
    if _is_closure(text):
        return _finish_to_handoff(session)
    low = text.lower()
    question = _question_sentence(text) or text.strip()
    segments: list[tuple[str, str]] = []
    cost_fastpath = (
        "?" in text
        and any(w in low for w in _COST_WORDS)
        and session["barrier_checklist"].get("cost", False)
        and not session["resources_offered"]
    )
    _append_verbatim_question(session, question)
    if cost_fastpath:
        _attach_resources(session)
        segments.append(_pair(_VERBATIM_ADD["en"], _VERBATIM_ADD["es"]))
        segments.append(_pair(
            _offer_segment(session["resources"], "en"),
            _offer_segment(session["resources"], "es"),
        ))
    else:
        segments.append(_pair(_ADDED["en"], _ADDED["es"]))
    return _finish_turn(session, segments)


def handle_turn(session: dict, text: str) -> dict:
    """Advance the conversation by one patient turn. The safety
    classifier has already run on ``text`` (sibling layer); if it
    escalated the session, this returns the fixed escalation line and
    drafts nothing."""
    text = (text or "").strip()
    session["turns"].append({
        "speaker": "patient", "text": text, "state": session["state"],
    })
    if session["_first_patient_turn"] is None and text:
        session["_first_patient_turn"] = text

    if session["state"] == "ESCALATED":
        return _finish_turn(session, [
            _pair(_ESCALATED_LINE["en"], _ESCALATED_LINE["es"])])

    if session["state"] in ("HANDOFF", "CLOSED"):
        return _finish_turn(session, [
            _pair(_PARKED_LINE["en"], _PARKED_LINE["es"])])

    _update_language(session, text)
    new_barriers = _merge_barriers(session, text)
    if session["slots"]["topic"] is None:
        session["slots"]["topic"] = detect_topic(text)
    if session["slots"]["appointment_text"] is None:
        session["slots"]["appointment_text"] = detect_appointment(text)

    state = session["state"]

    if state in ("GREETING", "INTAKE"):
        _record_state(session, "INTAKE")
        if session["slots"]["topic"] is None:
            return _finish_turn(session, [
                _pair(_INTAKE_ASK["en"], _INTAKE_ASK["es"])])
        segments: list[tuple[str, str]] = []
        confirmed = {b["barrier"] for b in session["barriers_found"]}
        if "fear" in confirmed:
            segments.append(_pair(_EMPATHY_FEAR["en"], _EMPATHY_FEAR["es"]))
        else:
            segments.append(_pair(_THANKS["en"], _THANKS["es"]))
        if "cost" in confirmed:
            segments.append(_pair(_COST_ACK["en"], _COST_ACK["es"]))
        segments.append(_probe_segment(session, _first_probe(session)))
        _record_state(session, "DISCOVERY")
        return _finish_turn(session, segments)

    if state == "DISCOVERY":
        said_all = _is_closure(text) or any(
            marker in text.lower()
            for marker in ("that's all", "nada más", "nada mas", "es todo"))
        if said_all or new_barriers or \
                session["probes_asked"] >= _PROBE_BUDGET:
            return _deliver_explain(session, new_barriers)
        area = _next_probe(session)
        if area is None:
            return _deliver_explain(session, new_barriers)
        return _finish_turn(session, [_probe_segment(session, area)])

    if state == "EXPLAIN":
        low = text.lower()
        if any(marker in low for marker in _REPEAT_MARKERS):
            topic = session["slots"]["topic"] or "other"
            return _finish_turn(session, [
                _pair(_EXPLANATIONS[topic]["en"],
                      _EXPLANATIONS[topic]["es"]),
                _pair(_UNDERSTANDING_CHECK["en"],
                      _UNDERSTANDING_CHECK["es"]),
            ])
        return _enter_questions(session, text)

    if state in ("QUESTIONS", "RESOURCES"):
        return _handle_questions(session, text)

    # Any other state: hold position with the thanks line (defensive;
    # the states above are exhaustive for the demo brain).
    return _finish_turn(session, [_pair(_THANKS["en"], _THANKS["es"])])


def closing_turn(session: dict) -> dict:
    """The companion's closing turn, delivered only after a navigator
    approves (the gate lives in main.py; this is just the words)."""
    _record_state(session, "CLOSED")
    return _finish_turn(session, [
        _pair(_CLOSING["en"], _CLOSING["es"])])
