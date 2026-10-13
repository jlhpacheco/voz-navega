# Voz Navega — Voice Companion

A voice-first companion that helps a patient get ready for a doctor visit — she talks, it listens, asks back, and helps her build the questions she wants to ask.

Simulated Alexa+ experience built for the **Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track). The experience runs as a web app: tap the orb and speak (browser speech recognition + speech synthesis), or type. A demo with fictional data only — not a medical service.

## Run it locally

```bash
pip install -r requirements.txt
uvicorn app.main:app
```

Then open http://127.0.0.1:8000/ in a browser. Health check: http://127.0.0.1:8000/api/health

## Status

Wave 1 scaffold: page, orb, transcript, and a stub `/api/turn`. The real companion engine lands in wave 2.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Jose Luis Pacheco.
