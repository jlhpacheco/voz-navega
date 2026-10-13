"""Voz Navega — FastAPI backend (scaffold, wave 1).

A simulated Alexa+ voice-companion experience in a web app: a fictional
patient talks, and the companion answers out loud (browser speech) and in
the transcript. This file is the scaffold only — /api/turn returns a stub
reply; the real conversation engine lands in wave 2.

Run from the repo root:  uvicorn app.main:app
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(
    title="Voz Navega",
    description="Voice-first companion that helps a fictional patient "
                "prepare for a doctor visit. Simulated Alexa+ experience "
                "in a web app. Demo only — not a medical service.",
    version="0.1.0",
)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class TurnIn(BaseModel):
    text: str = ""


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": "voz-navega", "demo_mode": True}


@app.post("/api/turn")
def turn(payload: TurnIn) -> dict:
    """Stub turn — wave 2 replaces this with the real companion engine."""
    heard = payload.text.strip()
    if heard:
        reply = (
            f'I heard you say: "{heard}". '
            "I am still a scaffold — my full companion brain arrives in "
            "wave 2. For now, this is where I would help you get ready "
            "for your doctor visit."
        )
    else:
        reply = (
            "Hello, I am Voz Navega, your voice companion. "
            "I am still a scaffold — my full companion brain arrives "
            "in wave 2."
        )
    return {"reply": reply, "state": "stub"}


# Serve the single-page frontend at / (mounted last so /api/* wins).
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
