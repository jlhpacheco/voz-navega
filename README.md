# Voz Navega — Voice Companion

A voice-first companion that helps a patient get ready for a doctor visit — she talks, it listens, asks back, and helps her build the questions she wants to ask.

Simulated Alexa+ experience built for the **Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track). The experience runs as a web app: tap the orb and speak (browser speech recognition + speech synthesis), or type. A demo with fictional data only — not a medical service.

## The MCP front door (Alexa+ track)

The same engine is also served as a **self-hosted MCP server** — the
Model Context Protocol spec revision **2025-11-25** over the
**Streamable HTTP** transport, built on the official MCP Python SDK
and mounted in this app at `POST /mcp` (`app/mcp_server.py`). It is
a real runtime surface, not a description: any MCP client can call
its tools and drive the actual conversation engine.

| Tool | What it does |
| --- | --- |
| `start_conversation` | Open a case; returns the VOZ session id and the companion's spoken greeting. |
| `patient_turn` | One patient utterance in → the safety gate, then the companion's spoken reply + state + structured case content out. |
| `case_status` | Read a case: state, barriers found (each tagged *stated* or *found by asking*), question list, approval status. |

Every front door — web app, MCP server — calls the one shared turn
flow in `app/flow.py`: the safety gate runs **first** on every turn,
and nothing is ever sent without a human navigator's approval
(approval itself stays on the navigator's screen; no tool can
approve). Test it with any MCP client, or with the repo's proof:
`pytest tests/test_mcp_server.py` boots the real server and drives
Marisol's golden conversation and the crisis interrupt through the
actual protocol handshake (`initialize` → `tools/list` →
`tools/call`).

## Run it locally

```bash
pip install -r requirements.txt
uvicorn app.main:app
```

Then open http://127.0.0.1:8000/ in a browser. Health check: http://127.0.0.1:8000/api/health

## Status

Working end to end: conversation engine (8-state machine, barrier
discovery probes, bilingual EN/ES), safety package (battery 45/45,
crisis + medical zero-tolerance 21/21), navigator approval gate
(409 until every resource is verified), web UI, and the MCP front
door. Full suite: 126 tests passing.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Jose Luis Pacheco.
