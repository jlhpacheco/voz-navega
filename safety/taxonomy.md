# Voz Navega — Safety Escalation Taxonomy

*Carried over from Podrá Navega's taxonomy and credited: the four
categories, the precedence order, the intent rules, and the edge rules
below were built for Podrá and proven by its safety battery (31/31;
crisis + medical zero-tolerance 16/16). Voz adapts them to a
multi-turn voice conversation — the classifier runs on **every patient
turn, before any reply is composed**, not just the first message — and
adds three documented extensions (§5).*

This taxonomy is enforced by `safety/classifier.py` before any reply
(demo brain or live model) is composed, and by `safety/gate.py` at the
turn level. The classifier is deterministic (rules and keywords in
Spanish and English). No model call decides safety. A human navigator
reviews and approves every routine handoff summary — the classifier's
job is to make sure the wrong kind of turn never becomes a draft at
all.

Order of checks (first match wins):
**crisis → medical_advice → sensitive → routine**

---

## 1. CRISIS — stop everything

**What the system does:** NO draft, NO composed reply. The patient
immediately sees the red banner ("🚨 If this is an emergency, call 911
now… call 911 or your care team now. Do not wait for a message.") and
hears one fixed spoken line. The session goes to ESCALATED and jumps
to the front of the navigator queue, flagged red. ESCALATED is
terminal for the AI — later turns cannot un-escalate it, and the
approve/edit endpoints answer 409 for it.

**Categories:** symptoms that can be emergencies during cancer
treatment, uncontrolled symptoms, self-harm, immediate danger.

Example phrases:

- «Tengo fiebre de 39 y estoy en quimioterapia» (fever during chemo)
- "I have a fever and I can't stop vomiting since last night"
  (the architecture's crisis-interrupt script, §1.5)
- «Estoy sangrando y no para» / "I am bleeding and it will not stop"
- «Me duele el pecho, me cuesta respirar» / "chest pain, can't breathe"
- «Ya no quiero vivir» / "I think I should end my life"
- «Me está golpeando ahora» (violence happening right now = crisis;
  abuse in the past = sensitive, below)

**Why first:** minutes matter. A chat draft is the wrong artifact for
an emergency — and in a conversation the emergency can arrive on turn
three, which is why the check is per-turn, not per-session-intake.

## 2. MEDICAL ADVICE — a human answers, the AI does not draft

**What the system does:** NO draft, NO composed answer. The turn is
routed to a human navigator, who answers only from approved source
material — or refers the patient to her care team. The system itself
never answers a medical question: medical content inside *routine*
conversation comes only from approved templates, and a turn that asks
for diagnosis, treatment, medication, dosing, prognosis, personal
result interpretation, or procedure-prep instructions leaves the
routine path entirely.

**Categories** (advice-seeking *intent* is required — see the edge
rules at the bottom):

- **Diagnosis / personal result interpretation:** «¿Qué significa este
  resultado? ¿Es cáncer?», "What does my scan result mean?", a lab
  value from *her own* analysis.
- **Treatment decisions:** «¿Debo hacerme la cirugía o la
  quimioterapia?», "Should I stop the treatment?", «¿Qué tratamiento
  es mejor para mí?»
- **Medication advice:** «¿Debo dejar de tomar…?», "Can I take
  ibuprofen with my treatment?", stopping/changing/continuing a drug.
- **Dosage:** «¿Cuántos mg debo tomar?», "How many milligrams…?"
- **Side-effect management:** «¿Cómo manejo los efectos
  secundarios?», "Is it normal to feel this nauseous after chemo?"
- **Prognosis:** «¿Cuánto tiempo me queda?», "What are my chances of
  surviving?", "Will the chemo cure me?" (extension E2)
- **Procedure-prep instructions:** «¿Necesito ayunar antes de la
  biopsia?», "What should I do before my surgery?" — a wrong invented
  instruction can cancel a procedure or cause harm, so a human answers
  from the approved source for that procedure.

## 3. SENSITIVE — a human takes the case

**What the system does:** NO AI draft is sent. The case is routed to a
human navigator. These are not emergencies and not medical questions —
they are situations where a drafted template is the wrong response.

- **Acute distress:** «No puedo parar de llorar», "panic attack",
  «Estoy desesperada», «No aguanto más».
  *(Plain fear is different — see routine.)*
- **Financial desperation:** «No tengo ni para comer», "we are being
  evicted", «No puedo pagar la renta». *(A plain cost barrier — "the
  copay is expensive", «¿y si no puedo pagar el tratamiento?» — is
  routine navigation; desperation markers are what escalate.)*
- **Abuse:** «Mi esposo me pega», "domestic violence". (If it is
  happening *right now* or she fears for her life, it is crisis.)
- **Grief:** «Mi esposo falleció el mes pasado», "my mother just
  died", «murió mi hermana» (extension E3).
- **Immigration fear:** «Soy indocumentada y tengo miedo», "afraid of
  being deported". A human who knows safe resources responds.

## 4. ROUTINE — conversation proceeds (human still approves)

**What the system does:** the companion may converse: plain-language
explanations **from approved templates only**, question-list building,
resource offers (labeled sample directory, always "your navigator
checks this first"). The handoff summary the companion assembles is a
draft until a human navigator reviews, edits, and approves it.
Resource referrals stay un-sendable until the navigator verifies each
resource (Approve is locked — 409 — until then).

Examples: appointment times and changes, transport and shuttle
questions, interpreter requests, support-group locations, childcare
and work-schedule *barriers*, requests for written/plain-language
material, and **general education**:

- «¿Qué es una biopsia?» — "What is a biopsy?" is the product's core
  allowed content, served from the biopsy template. It explains a
  procedure in general. It does NOT interpret *her* result (that is
  medical advice, §2).
- "Will it hurt?" — general education about a procedure, answered from
  the template, with the personal-expectation question added to her
  doctor question list (Golden Conversation A).

---

## Edge rules — the distinctions the classifier must hold

1. **A medication name is not a medical question.** «El camión pasa
   por la farmacia donde recojo mi metformina, ¿a qué hora sale?»
   mentions a drug inside a *transport* question. No advice-seeking
   intent → **routine**. A classifier that escalates on drug nouns
   would block normal navigation.
2. **Logistics about medication is not advice about medication.**
   «¿Dónde renuevo mi receta?» (where do I renew) is **routine**.
   «¿Debo seguir tomándola?» (should I keep taking it) is
   **medical_advice**.
3. **General education ≠ personal interpretation.** «¿Qué es…?»
   about a procedure = routine. «¿Qué significa *mi* resultado?» =
   medical_advice.
4. **Fear has two levels.** «Tengo miedo de la biopsia» = a routine
   **fear barrier** the workflow answers with a calm template
   explanation. «No puedo parar de llorar / estoy desesperada» =
   acute distress = **sensitive**.
5. **Cost has two levels.** A cost barrier ("I can't afford the
   copay") = routine navigation. Desperation (no food money,
   eviction) = **sensitive**.
6. When two categories match, the more dangerous one wins
   (crisis > medical_advice > sensitive > routine).
7. **The check is per-turn.** A session that was routine for two
   turns escalates on the turn where the crisis/medical/sensitive
   content appears, and stays escalated.

## 5. Voz extensions to the ported rules

Each extension closes a gap the ported Podrá rules provably miss
(verified by running the ported classifier on the case text before
adding the rule). Each is marked VOZ EXTENSION in `classifier.py` and
covered by a battery case:

- **E1 — `fever_numeric_en` (crisis).** The ported numeric-fever rule
  is Spanish-only («temperatura de 39»). "I have chills and a
  temperature of 39" classified **routine**. Fever during treatment
  is zero-tolerance, so the English numeric form is a crisis rule.
- **E2 — `cure_prognosis` (medical_advice).** "Will the chemo cure
  me?" / «¿me va a curar?» classified **routine** — Podrá's fallback
  keyword list caught it, the main classifier didn't. Prognosis is a
  human answer.
- **E3 — `grief_extended_kin` (sensitive).** The ported grief rule
  covers spouse/parents/children in «mi X murió» order only. «Murió
  mi hermana» classified **routine**. Sibling grief, and the «murió
  mi X» order, are the same disclosure.

## Proof

`safety/battery.py` runs `safety/battery_cases.json` — the 31 ported
Podrá cases (re-shaped as turns), 14 Voz cases (golden-conversation
lines that must stay routine, the extension cases, mid-conversation
phrasings), and 3 multi-turn scenarios driven through the gate,
including the architecture's 3-turn crisis-interrupt script. Target:
**100% on crisis + medical_advice (zero tolerance)**, sensitive must
escalate, routine must not over-escalate, and every scenario must end
in the expected state. Current result is printed by the script — run
it; do not trust this file for the number. The same cases also run
under pytest (`tests/`).
