"""The LLM boundary.

Every call goes through `complete`, which takes the corpus text as its own argument.
That is how the 3,000-token limit is enforced structurally: the client counts the
corpus part itself, refuses to send more than the limit, and logs the count for
every call (Section 4.3 of the brief). Instructions and the user's message are not
corpus text and are passed separately.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Protocol

from app.tokens import count_tokens

logger = logging.getLogger("veltrix.llm")

CORPUS_TOKEN_LIMIT = 3000


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


class LLM(Protocol):
    def complete(
        self, purpose: str, system: str, user: str, *, corpus_text: str = "",
        json_mode: bool = False, max_tokens: int = 700,
    ) -> str: ...


def check_corpus_budget(purpose: str, corpus_text: str) -> int:
    tokens = count_tokens(corpus_text) if corpus_text else 0
    if tokens > CORPUS_TOKEN_LIMIT:
        raise LLMError(f"{purpose}: {tokens} corpus tokens exceeds the {CORPUS_TOKEN_LIMIT} limit")
    return tokens


def join_prompt(user: str, corpus_text: str) -> str:
    return f"{user}\n\n{corpus_text}" if corpus_text else user


def parse_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object from a model reply, tolerating code fences or stray text."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("the model did not return JSON")
        try:
            value = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise LLMError("the model returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("the model returned JSON that is not an object")
    return value


class OpenAIClient:
    """Chat Completions over HTTPS using only the standard library (no extra dependency)."""

    def __init__(self, api_key: Optional[str], model: Optional[str],
                 base_url: str = "https://api.openai.com/v1", timeout: float = 20.0):
        self._key, self._model, self._base, self._timeout = api_key, model, base_url.rstrip("/"), timeout
        self._ssl = ssl.create_default_context()

    @property
    def configured(self) -> bool:
        return bool(self._key and self._model)

    def complete(self, purpose, system, user, *, corpus_text="", json_mode=False, max_tokens=700) -> str:
        corpus_tokens = check_corpus_budget(purpose, corpus_text)
        if not self.configured:
            raise LLMError("OPENAI_API_KEY and OPENAI_MODEL must be set")
        prompt = join_prompt(user, corpus_text)
        body: Dict[str, Any] = {
            "model": self._model,
            "temperature": 0,
            "seed": 7,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        payload = json.dumps(body).encode()
        started = time.monotonic()
        last: Optional[Exception] = None
        for attempt in range(2):
            request = urllib.request.Request(
                f"{self._base}/chat/completions", data=payload, method="POST",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout, context=self._ssl) as response:
                    data = json.loads(response.read().decode())
                text = data["choices"][0]["message"]["content"] or ""
                logger.info(
                    "llm_call purpose=%s model=%s corpus_tokens=%d prompt_tokens=%d latency_ms=%d",
                    purpose, self._model, corpus_tokens, count_tokens(system) + count_tokens(prompt),
                    int((time.monotonic() - started) * 1000),
                )
                return text
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 1:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
                last = exc
                if attempt == 1:
                    break
            time.sleep(0.5)
        logger.error("llm_call purpose=%s failed corpus_tokens=%d error=%s", purpose, corpus_tokens, type(last).__name__)
        raise LLMError(f"{purpose}: model call failed ({type(last).__name__})")
