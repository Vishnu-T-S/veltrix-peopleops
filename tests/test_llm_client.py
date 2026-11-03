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
    text = client().complete("extract_claims", "SYSTEM", "Question?", corpus_text="Sick leave is 12 days.", json_mode=True)
    assert text == '{"ok": true}'
    assert seen["body"]["temperature"] == 0 and seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "gpt-test" and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert "Sick leave is 12 days." in seen["body"]["messages"][1]["content"]
    assert "purpose=extract_claims" in caplog.text and "corpus_tokens=" in caplog.text
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
