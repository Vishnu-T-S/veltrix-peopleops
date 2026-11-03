"""A scripted stand-in for the LLM, so tests never call a real model.

It enforces the same 3,000-token corpus guard as the real client and records every
call, so tests can assert on exactly what would have been sent to the model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.llm.client import check_corpus_budget
from app.tokens import count_tokens

PASSAGE = re.compile(r"\[(?P<doc>[^|\]]+) \| (?P<loc>[^|]+) \| [^|\]]+ \| effective [^\]]*\]\n(?P<text>.*?)(?=\n\n\[|\Z)", re.S)
VOLUNTEER = re.compile(r"(?:receive|get) (\d+) (?:paid )?volunteer days", re.I)


@dataclass
class Call:
    purpose: str
    system: str
    user: str
    corpus_text: str
    corpus_tokens: int


def volunteer_claims(corpus_text: str) -> dict:
    """Reads 'N volunteer days' out of the passages, the way a real model would."""
    claims = []
    for m in PASSAGE.finditer(corpus_text):
        found = VOLUNTEER.search(m.group("text"))
        if found:
            claims.append({"rule": "volunteer_days", "value": f"{found.group(1)} days", "detail": "",
                           "doc_id": m.group("doc").strip(), "locator": m.group("loc").strip()})
    return {"claims": claims, "not_covered": []}


class FakeLLM:
    def __init__(self, plans: Optional[Dict[str, dict]] = None, claims_fn: Callable[[str], dict] = volunteer_claims,
                 writer_fn: Optional[Callable[[str, str], str]] = None):
        self.plans = plans or {}
        self.claims_fn = claims_fn
        self.writer_fn = writer_fn or (lambda user, corpus: "ANSWER " + corpus)
        self.calls: List[Call] = []

    def add_plan(self, message: str, **fields) -> None:
        self.plans[message] = fields

    def complete(self, purpose, system, user, *, corpus_text="", json_mode=False, max_tokens=700) -> str:
        tokens = check_corpus_budget(purpose, corpus_text)
        self.calls.append(Call(purpose, system, user, corpus_text, tokens))
        if purpose == "plan":
            message = re.search(r"<user_message>\n(.*?)\n</user_message>", user, re.S).group(1)
            plan = self.plans.get(message, {"intent": "smalltalk"})
            return json.dumps(plan)
        if purpose == "extract_claims":
            return json.dumps(self.claims_fn(corpus_text))
        return self.writer_fn(user, corpus_text)

    def purposes(self) -> List[str]:
        return [c.purpose for c in self.calls]
