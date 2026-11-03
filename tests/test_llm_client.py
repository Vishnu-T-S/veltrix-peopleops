import json
import logging
import urllib.error
import urllib.request

import pytest

from app.llm.client import CORPUS_TOKEN_LIMIT, LLMError, OpenAIClient, parse_json


class Response:
    def __init__(self, content='{"ok": true}'):
        self._body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def client():
    return OpenAIClient("sk-test", "gpt-test")


def test_request_uses_temperature_zero_json_mode_and_logs_corpus_tokens(monkeypatch, caplog):
    seen = {}

    def fake_urlopen(request, timeout, context):
        seen["body"] = json.loads(request.data)
        seen["auth"] = request.headers["Authorization"]
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    caplog.set_level(logging.INFO)
    from app.logctx import request_id_var
    request_id_var.set("req-123")
    text = client().complete("extract_claims", "SYSTEM", "Question?", corpus_text="Sick leave is 12 days.", json_mode=True)
    assert text == '{"ok": true}'
    assert seen["body"]["temperature"] == 0 and seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "gpt-test" and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert "Sick leave is 12 days." in seen["body"]["messages"][1]["content"]
    assert "request_id=req-123 purpose=extract_claims" in caplog.text and "corpus_tokens=" in caplog.text
    assert "sk-test" not in caplog.text


def test_more_than_3000_corpus_tokens_is_refused_before_any_request(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="exceeds"):
        client().complete("extract_claims", "s", "q", corpus_text="word " * (CORPUS_TOKEN_LIMIT + 100))


def test_exactly_at_the_limit_is_allowed(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
    from app.tokens import count_tokens
    text = "word " * 2990
    assert count_tokens(text) <= CORPUS_TOKEN_LIMIT
    client().complete("write_answer", "s", "q", corpus_text=text)


def test_unconfigured_client_fails_cleanly():
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAIClient(None, None).complete("plan", "s", "q")


def test_a_temporary_server_error_is_retried_once(monkeypatch):
    calls = []

    def flaky(request, timeout, context):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 503, "busy", {}, None)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert client().complete("plan", "s", "q") == '{"ok": true}' and len(calls) == 2


def test_an_authentication_error_is_not_retried(monkeypatch):
    calls = []

    def denied(request, timeout, context):
        calls.append(1)
        raise urllib.error.HTTPError("u", 401, "no", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", denied)
    with pytest.raises(LLMError):
        client().complete("plan", "s", "q")
    assert len(calls) == 1


@pytest.mark.parametrize("text", ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! {"a": 1} hope it helps'])
def test_parse_json_tolerates_fences_and_chatter(text):
    assert parse_json(text) == {"a": 1}


@pytest.mark.parametrize("text", ["not json", "[1, 2]", "{broken"])
def test_parse_json_rejects_other_things(text):
    with pytest.raises(LLMError):
        parse_json(text)


# ---- the other two providers ------------------------------------------------------------------

from app.config import load_settings
from app.llm.client import AnthropicClient, GeminiClient
from app.llm.factory import make_llm


def capture(monkeypatch, reply):
    seen = {}

    class Reply:
        def read(self):
            return json.dumps(reply).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout, context):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
        seen["body"] = json.loads(request.data)
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_anthropic_request_and_reply(monkeypatch):
    seen = capture(monkeypatch, {"content": [{"type": "text", "text": '{"a": 1}'}]})
    text = AnthropicClient("ak-test", "claude-test").complete("plan", "SYS", "Q", corpus_text="Passage.", json_mode=True)
    assert text == '{"a": 1}'
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "ak-test" and seen["headers"]["anthropic-version"]
    assert seen["body"]["temperature"] == 0 and seen["body"]["model"] == "claude-test"
    assert seen["body"]["system"].startswith("SYS") and "JSON" in seen["body"]["system"]
    assert "Passage." in seen["body"]["messages"][0]["content"]


def test_gemini_request_and_reply(monkeypatch):
    seen = capture(monkeypatch, {"candidates": [{"content": {"parts": [{"text": '{"b": 2}'}]}}]})
    text = GeminiClient("gk-test", "gemini-test").complete("plan", "SYS", "Q", corpus_text="Passage.", json_mode=True)
    assert text == '{"b": 2}'
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert seen["headers"]["x-goog-api-key"] == "gk-test"
    assert seen["body"]["generationConfig"]["temperature"] == 0
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert "Passage." in seen["body"]["contents"][0]["parts"][0]["text"]


@pytest.mark.parametrize("cls", [AnthropicClient, GeminiClient])
def test_every_provider_refuses_more_than_3000_corpus_tokens(monkeypatch, cls):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    with pytest.raises(LLMError, match="exceeds"):
        cls("k", "m").complete("extract_claims", "s", "q", corpus_text="word " * 3200)


@pytest.mark.parametrize("provider, key_env, expected", [
    ("openai", "OPENAI_API_KEY", OpenAIClient),
    ("anthropic", "ANTHROPIC_API_KEY", AnthropicClient),
    ("gemini", "GEMINI_API_KEY", GeminiClient),
    ("google", "GOOGLE_API_KEY", GeminiClient),
])
def test_provider_is_chosen_from_the_environment(provider, key_env, expected):
    llm = make_llm(load_settings({"LLM_PROVIDER": provider, key_env: "secret"}))
    assert type(llm) is expected and llm.configured


def test_unknown_provider_does_not_crash_start_up():
    llm = make_llm(load_settings({"LLM_PROVIDER": "nonsense"}))
    with pytest.raises(LLMError):
        llm.complete("plan", "s", "q")


def test_no_model_call_starts_after_the_request_deadline(monkeypatch):
    import time
    from app.logctx import deadline_var

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    deadline_var.set(time.monotonic() - 1)
    try:
        with pytest.raises(LLMError):
            client().complete("plan", "s", "q")
    finally:
        deadline_var.set(0.0)


def test_the_timeout_never_exceeds_the_time_left(monkeypatch):
    import time
    from app.logctx import deadline_var

    seen = {}

    def fake(request, timeout, context):
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    deadline_var.set(time.monotonic() + 5)
    try:
        client().complete("plan", "s", "q")
    finally:
        deadline_var.set(0.0)
    assert seen["timeout"] <= 5
