"""Frontend-serving proof — the patient screen must actually load.

Regression guard for the bug that shipped to Render on Oct 13: the
MCP sub-app is mounted at the root and matches every path, so the
StaticFiles mount at / became unreachable and GET / (plus the
screen's style.css and app.js) returned 404 on the public host
while /api/* stayed green. The frontend's three files are served
by explicit routes registered before the mounts (app/main.py);
these tests pin those paths — and that the API and the MCP mount
were not disturbed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BANNER = ("Simulated Alexa+ experience — demo. Fictional patient. "
          "Not a medical service.")


def test_root_serves_the_patient_screen():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert BANNER in r.text
    assert 'href="style.css"' in r.text
    assert 'src="app.js"' in r.text


def test_index_html_serves_the_patient_screen():
    r = client.get("/index.html")
    assert r.status_code == 200
    assert BANNER in r.text


def test_style_css_loads():
    r = client.get("/style.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert len(r.text) > 100


def test_app_js_loads():
    r = client.get("/app.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert len(r.text) > 100


def test_api_still_wins_over_the_frontend_routes():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r = client.get("/api/sessions")
    assert r.status_code == 200
    seeded = {s["id"]: s for s in r.json()["sessions"]}
    assert seeded["VOZ-0001"]["state"] == "HANDOFF"
