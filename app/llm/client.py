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

from app.logctx import deadline_var, request_id_var
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


class HttpLLM:
    """Shared plumbing for every provider: the corpus-token guard, one retry on temporary
    errors, and the per-call log line. A provider only says how to build its request and
    how to read its reply. Uses only the standard library (no extra dependency)."""

    key_hint = "API key and model"

    def __init__(self, api_key: Optional[str], model: Optional[str], base_url: Optional[str] = None,
                 timeout: float = 20.0):
        self._key, self._model, self._timeout = api_key, model, timeout
        self._base = (base_url or self.default_base).rstrip("/")
        self._ssl = ssl.create_default_context()

    default_base = ""

    @property
    def configured(self) -> bool:
        return bool(self._key and self._model)

    def _build(self, system: str, prompt: str, json_mode: bool, max_tokens: int):
        """Return (url, headers, body) for one request."""
        raise NotImplementedError

    def _text(self, data: Dict[str, Any]) -> str:
        """Return the reply text from the provider's JSON response."""
        raise NotImplementedError

    def complete(self, purpose, system, user, *, corpus_text="", json_mode=False, max_tokens=700) -> str:
        corpus_tokens = check_corpus_budget(purpose, corpus_text)
        if not self.configured:
            raise LLMError(f"{self.key_hint} must be set")
        prompt = join_prompt(user, corpus_text)
        url, headers, body = self._build(system, prompt, json_mode, max_tokens)
        payload = json.dumps(body).encode()
        started = time.monotonic()
        last: Optional[Exception] = None
        for attempt in range(2):
            request = urllib.request.Request(url, data=payload, method="POST",
                                             headers={**headers, "Content-Type": "application/json"})
            timeout = self._timeout
            if deadline_var.get():                      # the whole request must finish within its deadline
                timeout = min(timeout, deadline_var.get() - time.monotonic())
                if timeout < 1.0:
                    last = TimeoutError("request deadline reached")
                    break
            try:
                with urllib.request.urlopen(request, timeout=timeout, context=self._ssl) as response:
                    data = json.loads(response.read().decode())
                text = self._text(data) or ""
                logger.info(
                    "llm_call request_id=%s purpose=%s model=%s corpus_tokens=%d prompt_tokens=%d latency_ms=%d",
                    request_id_var.get(), purpose, self._model, corpus_tokens,
                    count_tokens(system) + count_tokens(prompt), int((time.monotonic() - started) * 1000),
                )
                return text
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (429, 500, 502, 503, 504, 529) or attempt == 1:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError) as exc:
                last = exc
                if attempt == 1:
                    break
            time.sleep(0.5)
        logger.error("llm_call request_id=%s purpose=%s failed corpus_tokens=%d error=%s",
                     request_id_var.get(), purpose, corpus_tokens, type(last).__name__)
        raise LLMError(f"{purpose}: model call failed ({type(last).__name__})")


class OpenAIClient(HttpLLM):
    key_hint = "OPENAI_API_KEY and OPENAI_MODEL"
    default_base = "https://api.openai.com/v1"

    def _build(self, system, prompt, json_mode, max_tokens):
        body: Dict[str, Any] = {
            "model": self._model, "temperature": 0, "seed": 7, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return f"{self._base}/chat/completions", {"Authorization": f"Bearer {self._key}"}, body

    def _text(self, data):
        return data["choices"][0]["message"]["content"]


class AnthropicClient(HttpLLM):
    key_hint = "ANTHROPIC_API_KEY and ANTHROPIC_MODEL"
    default_base = "https://api.anthropic.com/v1"

    def _build(self, system, prompt, json_mode, max_tokens):
        instruction = system + ("\n\nReply with a single JSON object and nothing else." if json_mode else "")
        body = {"model": self._model, "temperature": 0, "max_tokens": max_tokens, "system": instruction,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        return f"{self._base}/messages", headers, body

    def _text(self, data):
        return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")


class GeminiClient(HttpLLM):
    key_hint = "GEMINI_API_KEY (or GOOGLE_API_KEY) and GEMINI_MODEL"
    default_base = "https://generativelanguage.googleapis.com/v1beta"

    def _build(self, system, prompt, json_mode, max_tokens):
        config: Dict[str, Any] = {"temperature": 0, "maxOutputTokens": max(max_tokens, 1500)}
        if json_mode:
            config["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        return f"{self._base}/models/{self._model}:generateContent", {"x-goog-api-key": self._key}, body

    def _text(self, data):
        return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
