# Voz Navega — a voice companion cancer patients talk to

**She talks, it listens.** Voz Navega is a voice-first companion for cancer
patients, built for the community served by **Latinas Contra Cancer**. The
patient speaks — out loud, in English or Spanish — and the companion answers
aloud in her language. It explains her next step (a biopsy, a first
chemotherapy session) in plain words, catches the barriers she states *and*
the ones she only hints at, builds her list of questions for the doctor,
offers resources, and then it **stops**: a summary goes to a human navigator,
who must review and approve it before anything is sent anywhere. In a crisis,
everything stops at once and a human takes the case.

Built for the **Build, Ship, Shape: Amazon Developer Hackathon** — Alexa+ track.

> **What this is, and what it is not.** Every patient in the demo is
> **fictional** and labeled on screen. Voz Navega gives **information and
> preparation only — no diagnosis, no treatment advice.** The demo navigator,
> **Elena, is a synthetic demo navigator**, and she is labeled that way
> wherever she appears. There is no database by design: sessions live in
> memory and reset when the host sleeps, and no real patient data is ever
> used.

## Live demo

**https://voz-navega.onrender.com**

Open it and talk: tap the orb and speak (browser speech recognition +
speech synthesis), or type. The navigator panel sits beside the patient
screen, so you can watch the case build — barriers, question list, resources —
as the conversation runs. A golden case (**VOZ-0001**, Marisol) is seeded at
HANDOFF / PENDING_APPROVAL so the navigator approval gate can be exercised
immediately.

The on-screen banner reads, verbatim:

> *Simulated Alexa+ experience — demo. Fictional patient. Not a medical service.*

That banner labels the **web surface** for what it is: the test bench and the
navigator's screen. It is not a claim about the Alexa path — see
[The Alexa path](#the-alexa-path--honest-status) below for exactly where that
stands. One practical note: the live demo runs on Render's free tier, which
sleeps when idle — the first hit can take up to a minute to wake. Wake it
once and it stays responsive.

## How it works

### One door, safety first

There is exactly **one door** into the conversation engine — the shared turn
flow in `app/flow.py` — and the **safety gate runs first, on every turn**,
before any reply is composed:

1. A classifier screens each patient message. Crisis, medical-advice, and
   sensitive turns are never answered by the machine. The gate speaks a fixed
   line — for crisis: *"This sounds like an emergency. Call 911 or your care
   team now. I'm stopping here and sending this straight to a human
   navigator."* — and hands the case to a human. An escalated case is
   **terminal**: it cannot be talked around, and approving it is refused
   server-side.
2. Only a turn that clears the gate reaches the conversation engine.

### The conversation engine

The engine is an 8-state flow:

`GREETING → INTAKE → DISCOVERY → EXPLAIN → QUESTIONS → RESOURCES → HANDOFF → CLOSED`

with `ESCALATED` reachable from every state. In DISCOVERY the engine asks
**one more question** — a probe for the barrier the patient never names
(the ride she doesn't have, the grandkids she watches every morning). The
patient path is deterministic by design: no LLM calls, no API key, $0 per
conversation — so the same conversation plays identically in tests, on the
web, and through MCP. Barriers are recorded with their source:

- **stated** — the patient said it, in her words;
- **found by asking** — a probe surfaced it, with her own sentence as evidence.

Spanish input gets a Spanish reply; the navigator panel shows every Spanish
turn with an English gloss.

### The navigator gate

Nothing sends on the machine's word. Resources sit at "not checked yet"
until the navigator verifies each one. **Approve is locked server-side**
(HTTP 409) until the case reaches HANDOFF *and* every resource is verified
by the navigator's attestation; only then does approve succeed. Approval
lives on the navigator's screen only — no API tool and no MCP tool can
approve a case. In the demo, the approver is shown as **Elena — Synthetic
Demo Navigator**.

## The two surfaces

### Web app

The patient voice screen (orb, speech in, speech out, barrier chips that
distinguish *"You told me"* from *"We found it by asking"*) plus the
navigator panel. This is the surface at the live demo URL above.

### MCP server — the Alexa+ qualifying artifact

The same engine is also served as a **self-hosted MCP server**: the Model
Context Protocol spec revision **2025-11-25** over the **Streamable HTTP**
transport, built on the official MCP Python SDK and mounted in this app at
`POST /mcp` (`app/mcp_server.py`). It is a real runtime surface, not a
description: any MCP client can call its tools and drive the actual
conversation engine. The live server is public at
`https://voz-navega.onrender.com/mcp` — its `initialize` handshake
negotiates protocol **2025-11-25** (verified live, see
[Verified results](#verified-results)).

| Tool | What it does |
| --- | --- |
| `start_conversation` | Open a case; returns the VOZ session id and the companion's spoken greeting. |
| `patient_turn` | One patient utterance in → the safety gate, then the companion's spoken reply + state + structured case content out. |
| `case_status` | Read a case: state, barriers found (each tagged *stated* or *found by asking*), question list, approval status. |

Both doors call the one shared turn flow, so a case started through MCP
reads identically in the web panel, and the reverse — one store, one state.

## The Alexa path — honest status

The MCP server above is **live, public, and proven** — that part has
landed. The path from a physical Echo to that server is **built to and in
progress**:

- The route is the open-source
  [**alexa-skill-mcp-bridge**](https://github.com/KayLerch/alexa-skill-mcp-bridge)
  (Apache-2.0): a Strands agent on Amazon Bedrock AgentCore Runtime plus a
  thin Alexa Skill Lambda, with the skill's interaction model generated
  from our server's tools. We label it exactly what it is — **a bridge,
  not native Alexa+**. (Native Alexa+ add-on access is partner-gated, with
  no self-service path for an individual entrant in this window; the
  bridge is the honest way to put a real device in front of a real MCP
  server.)
- **Done:** the bridge is staged locally, its setup is fully mapped step
  by step, and our server meets its stated requirements (Streamable HTTP,
  protocol 2025-11-25, tools whose results are complete exchanges).
- **Still ahead:** the bridge's deploy into AWS and the physical-Echo
  pass. Until those land, nothing in this repo claims the Echo demo
  works — when it does, this section will say so, with the proof.

## The golden cases

Scripted end-to-end cases (run them with `python scripts/golden_run.py`):

- **Marisol (English, biopsy).** Scared, and doesn't know what a biopsy
  is. The probe catches what she only hints at: her daughter works and she
  doesn't drive (**transport**), and she watches her grandkids every
  morning (**childcare**). She leaves with a plain-words explanation, a
  question list, two offered resources, and a case parked at HANDOFF /
  PENDING_APPROVAL.
- **Rosa (Spanish, chemotherapy).** Worried about cost and about not
  understanding the treatment. The companion answers in Spanish; her own
  words — *"¿Y si no puedo pagar el tratamiento?"* — land on her question
  list verbatim.
- **Crisis interrupt.** Three turns in, a crisis line stops everything:
  the fixed escalation line speaks, the case jumps to the navigator as
  ESCALATED, and it stays escalated.

## Run it locally

Python 3.12. No environment variables, no API keys — the app reads none.

```bash
pip install -r requirements.txt
uvicorn app.main:app
```

Then open http://127.0.0.1:8000/ in a browser. Health check:
http://127.0.0.1:8000/api/health — and the MCP server answers at
http://127.0.0.1:8000/mcp.

## Run the tests

```bash
pytest                                # full suite: 131 passing
pytest tests/test_mcp_server.py       # the MCP proof: boots the real server and
                                      # drives the golden conversation + crisis
                                      # interrupt through the actual protocol
python3 safety/battery.py             # safety battery: 45/45, zero-tolerance 21/21
python scripts/golden_run.py          # golden conversations A + B, turn by turn
```

## Verified results

Independently cold-checked, Oct 13, 2026:

- **131 automated tests pass** (pytest), including a live MCP protocol suite.
- **Safety battery: 45/45 cases**; the crisis + medical **zero-tolerance
  set: 21/21**.
- **Golden conversations A (Marisol) and B (Rosa) pass end to end** —
  Marisol reaches HANDOFF / PENDING_APPROVAL with transport + childcare
  caught *by probe*; Rosa reaches handoff with her cost question verbatim.
- **Live public MCP probe with an official SDK client:** the handshake
  against `https://voz-navega.onrender.com/mcp` negotiates exactly
  **2025-11-25**; the three tools list and answer; a crisis turn returns
  the gate's fixed line byte-exact, and a calm turn after escalation
  stays ESCALATED.
- The navigator gate's refusals are tested, not asserted: approve returns
  **409** until handoff + every resource verified, then **200**, then
  **409** again.

## Repository layout

- `app/flow.py` — the one shared turn flow (the only door into the engine)
- `app/mcp_server.py` — the MCP server, mounted at `POST /mcp`
- `app/main.py` — the FastAPI app: web UI, API, navigator gate
- `app/brain_demo.py` — the deterministic conversation engine
- `safety/` — the classifier, the gate, and the battery
- `scripts/golden_run.py` — the golden conversations, runnable
- `tests/` — the pytest suite, incl. the MCP protocol proof

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Jose Luis Pacheco.

