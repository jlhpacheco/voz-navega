"""In-memory session store for Voz Navega (ARCHITECTURE.md §2.1).

Deliberately NO database: sessions live in this process and reset
when the host sleeps — the same disclosed choice as Podrá Navega.
The store owns ids (``VOZ-0001``…), a thread lock, and copy-in /
copy-out semantics: callers always work on a deep copy and write the
session back with :meth:`SessionStore.update`, so no caller can
mutate stored state by holding a reference.
"""

from __future__ import annotations

import copy
import threading


class SessionStore:
    """Thread-locked dict of plain session dicts (brain_demo shape)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._counter = 0

    def next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"VOZ-{self._counter:04d}"

    def create(self, session: dict) -> dict:
        """Store a new session (assigning an id if it has none) and
        return a copy of what was stored."""
        with self._lock:
            if not session.get("id"):
                self._counter += 1
                session["id"] = f"VOZ-{self._counter:04d}"
            self._sessions[session["id"]] = copy.deepcopy(session)
            return copy.deepcopy(session)

    def get(self, session_id: str) -> dict | None:
        """A deep copy of the stored session, or None."""
        with self._lock:
            session = self._sessions.get(session_id)
            return copy.deepcopy(session) if session is not None else None

    def update(self, session: dict) -> dict:
        """Write back a (mutated) session copy; returns a copy."""
        with self._lock:
            self._sessions[session["id"]] = copy.deepcopy(session)
            return copy.deepcopy(session)

    def all(self) -> list[dict]:
        """Deep copies of every session, in creation order."""
        with self._lock:
            return [copy.deepcopy(s) for s in self._sessions.values()]
