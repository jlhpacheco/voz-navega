"""MCP front-door proof (app/mcp_server.py) — the REAL protocol.

Boots the actual FastAPI app under uvicorn on a local port and
drives it with the official MCP Python SDK client: an initialize
handshake (asserting the negotiated protocol revision is the
track's pinned 2025-11-25), tools/list, and tools/call driving
Marisol's golden conversation (ARCHITECTURE.md §1.3) through
patient_turn, the §1.5 crisis interrupt, and case_status.

Sandbox note: the box's proxy env vars break the SDK client's
default httpx construction (no_proxy holds bracketed IPv6 entries
httpx2 cannot parse), so the client is given an explicit
trust_env=False HTTP client — the same lesson the cold-verification
drivers learned. On a clean machine the default client works.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

GOLDEN_A_LINES = [
    "They told me I need a biopsy on Tuesday and I'm scared. "
    "I don't really know what it is.",
    "Getting there. My daughter works, and I don't drive. And I watch "
    "my grandkids in the mornings — who watches them?",
    "Keep going. Will it hurt?",
    "That's good. Nothing to add.",
]

CRISIS_LINE = ("I have a fever and I can't stop vomiting since "
               "last night.")
CRISIS_SPOKEN = ("This sounds like an emergency. Call 911 or your "
                 "care team now. I'm stopping here and sending this "
                 "straight to a human navigator.")

EXPECTED_TOOLS = {"start_conversation", "patient_turn", "case_status"}
EXPECTED_HISTORY = [
    "GREETING", "INTAKE", "DISCOVERY", "EXPLAIN",
    "QUESTIONS", "RESOURCES", "HANDOFF",
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def base_url() -> str:
    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                r = httpx.get(f"{url}/api/health", timeout=1,
                              trust_env=False)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.1)
        else:  # pragma: no cover — server failed to come up
            raise RuntimeError("uvicorn did not start in 30s")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _with_session(base_url: str, work):
    http_client = httpx2.AsyncClient(trust_env=False, timeout=30)
    async with streamable_http_client(
            f"{base_url}/mcp", http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            return await work(session, init)


def _structured(result) -> dict:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    return result.structured_content


def test_handshake_negotiates_2025_11_25_and_lists_tools(base_url):
    async def work(session, init):
        assert init.protocol_version == "2025-11-25"
        assert init.server_info.name == "Voz Navega"
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == EXPECTED_TOOLS
        for tool in tools.tools:
            assert tool.input_schema  # a real schema, not a stub
            assert tool.output_schema is not None
    asyncio.run(_with_session(base_url, work))


def test_golden_a_through_mcp_tools(base_url):
    async def work(session, init):
        started = _structured(
            await session.call_tool("start_conversation", {}))
        sid = started["session_id"]
        assert started["state"] == "GREETING"
        assert "Voz" in started["greeting"]

        body = {}
        states = []
        for line in GOLDEN_A_LINES:
            body = _structured(await session.call_tool(
                "patient_turn", {"session_id": sid, "text": line}))
            states.append(body["state"])
            assert body["spoken"]  # every turn has a spoken reply
            assert body["escalated"] is False
        # The same per-turn states the web API returns (the flow
        # is shared — app/flow.py), ending parked at the gate.
        assert states == ["DISCOVERY", "EXPLAIN", "QUESTIONS", "HANDOFF"]
        assert body["state"] == "HANDOFF"
        assert body["approval_status"] == "PENDING_APPROVAL"

        barriers = {b["barrier"]: b for b in body["barriers_found"]}
        assert barriers["transport"]["confirmed_by"] == "probe"
        assert barriers["childcare"]["confirmed_by"] == "probe"
        assert "Will it hurt?" in (body["question_list"] or [])
        assert body["summary"] is not None
        assert all(r["verified"] is False for r in body["resources"])

        status = _structured(await session.call_tool(
            "case_status", {"session_id": sid}))
        assert status["state"] == "HANDOFF"
        assert status["state_history"] == EXPECTED_HISTORY
        assert status["approval_status"] == "PENDING_APPROVAL"
        assert status["escalated"] is False
    asyncio.run(_with_session(base_url, work))


def test_crisis_turn_through_mcp_tools(base_url):
    async def work(session, init):
        started = _structured(
            await session.call_tool("start_conversation", {}))
        sid = started["session_id"]
        for line in GOLDEN_A_LINES[:2]:  # a calm conversation first
            _structured(await session.call_tool(
                "patient_turn", {"session_id": sid, "text": line}))

        body = _structured(await session.call_tool(
            "patient_turn", {"session_id": sid, "text": CRISIS_LINE}))
        assert body["state"] == "ESCALATED"
        assert body["escalated"] is True
        assert body["safety_category"] == "crisis"
        assert body["spoken"] == CRISIS_SPOKEN  # the fixed line, verbatim
        assert body["summary"] is None           # no draft on escalation
        assert body["approval_status"] is None
        assert body["banner"]["kind"] == "crisis"
        assert "911" in body["banner"]["headline"]

        # ESCALATED is terminal: a later calm turn changes nothing.
        body = _structured(await session.call_tool(
            "patient_turn",
            {"session_id": sid, "text": "That's good. Nothing to add."}))
        assert body["state"] == "ESCALATED"
        assert body["spoken"] == CRISIS_SPOKEN

        status = _structured(await session.call_tool(
            "case_status", {"session_id": sid}))
        assert status["escalated"] is True
        assert status["escalated_category"] == "crisis"
    asyncio.run(_with_session(base_url, work))


def test_unknown_session_is_a_tool_error(base_url):
    async def work(session, init):
        result = await session.call_tool(
            "patient_turn",
            {"session_id": "VOZ-9999", "text": "hello"})
        assert result.is_error is True
        result = await session.call_tool(
            "case_status", {"session_id": "VOZ-9999"})
        assert result.is_error is True
    asyncio.run(_with_session(base_url, work))


def test_mcp_and_web_share_one_store(base_url):
    """A case opened over MCP is the same case on the web door —
    one store, one flow (app/flow.py)."""
    async def work(session, init):
        started = _structured(
            await session.call_tool("start_conversation", {}))
        return started["session_id"]
    sid = asyncio.run(_with_session(base_url, work))
    r = httpx.get(f"{base_url}/api/sessions/{sid}", trust_env=False)
    assert r.status_code == 200
    assert r.json()["state"] == "GREETING"
