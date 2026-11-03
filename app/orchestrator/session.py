"""Conversation sessions: who owns a session, recent turns, and the one pending proposal."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Pending:
    name: str                 # "apply_leave" | "cancel_leave"
    args: Dict[str, Any]
    summary: str


@dataclass
class SessionState:
    employee_id: str
    history: List[Tuple[str, str]] = field(default_factory=list)
    pending: Optional[Pending] = None   # at most one proposal waits at a time


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def claim(self, session_id: str, employee_id: str) -> Optional[SessionState]:
        """Return the session, creating it for `employee_id` if new.
        Returns None if the session already belongs to a different employee."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = self._sessions[session_id] = SessionState(employee_id)
            return state if state.employee_id == employee_id else None
