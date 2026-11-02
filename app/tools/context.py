"""What every tool call is given by the orchestrator.

`requester` comes from the X-Employee-Id header and the database. It is NEVER taken
from the message or from arguments the LLM chose, so a tool cannot be tricked into
acting as someone else.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.data.models import Employee


@dataclass
class ToolContext:
    conn: sqlite3.Connection
    requester: Employee
    today: date
