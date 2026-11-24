"""Checks what LLMService actually sends over HTTP, using a throw-away local OpenAI-compatible server."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.llm_service import LLMService, LLMServiceError, LLMSettings

STATE = {"mode": "ok", "content": "Hello Gaurav!", "last": None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["last"] = {"path": self.path, "auth": self.headers.get("Authorization"),
                         "referer": self.headers.get("HTTP-Referer"), "title": self.headers.get("X-Title"), "body": body}
        mode = STATE["mode"]
        if mode == "slow":
            time.sleep(1.5)
        status, payload = 200, {"choices": [{"message": {"role": "assistant", "content": STATE["content"]},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        if mode == "401":
            status, payload = 401, {"error": {"message": "Invalid API key", "code": 401}}
        elif mode == "429":
            status, payload = 429, {"error": {"message": "Rate limit", "code": 429}}
        elif mode == "500":
            status, payload = 500, {"error": {"message": "upstream exploded", "code": 500}}
        elif mode == "empty":
            payload["choices"][0]["message"]["content"] = ""
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture
def service(server, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key-123")
    monkeypatch.setenv("LLM_MODEL", "vendor/some-model")
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server}/v1")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0.7")
    monkeypatch.setenv("LLM_SITE_URL", "https://example.test")
    monkeypatch.setenv("LLM_SITE_TITLE", "Test App")
    STATE.update(mode="ok", content="Hello Gaurav!", last=None)
    return LLMService(LLMSettings.from_env())


def run(service, messages=None):
    return asyncio.run(service.generate("SYSTEM TEXT", messages or [{"role": "user", "content": "hi"}]))


def test_request_format_and_reply(service):
    assert run(service) == "Hello Gaurav!"
    last = STATE["last"]
    assert last["path"] == "/v1/chat/completions"
    assert last["auth"] == "Bearer test-key-123"
    assert last["referer"] == "https://example.test" and last["title"] == "Test App"
    assert last["body"]["model"] == "vendor/some-model"
    assert last["body"]["messages"] == [{"role": "system", "content": "SYSTEM TEXT"},
                                        {"role": "user", "content": "hi"}]
    assert last["body"]["max_tokens"] == 500 and last["body"]["temperature"] == 0.6


def test_reasoning_blocks_and_markdown_removed(service):
    STATE["content"] = "<think>secret reasoning</think>**Sure**, happy to help."
    assert run(service) == "Sure, happy to help."


def test_merge_system_prompt_mode(service, monkeypatch):
    monkeypatch.setenv("LLM_MERGE_SYSTEM_PROMPT", "true")
    run(LLMService(LLMSettings.from_env()))
    msgs = STATE["last"]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user"] and msgs[0]["content"].startswith("SYSTEM TEXT")


def test_blank_temperature_is_not_sent(service, monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "")
    run(LLMService(LLMSettings.from_env()))
    assert "temperature" not in STATE["last"]["body"]


@pytest.mark.parametrize("mode,fragment", [
    ("401", "not configured correctly"),
    ("429", "busy"),
    ("500", "temporarily unavailable"),
    ("empty", "did not return an answer"),
    ("slow", "took too long"),
])
def test_errors_are_sanitized(service, mode, fragment):
    STATE["mode"] = mode
    with pytest.raises(LLMServiceError) as info:
        run(service)
    assert fragment in info.value.public_message
    assert info.value.status_code == 503
    for secret in ("test-key-123", "Invalid API key", "upstream exploded"):
        assert secret not in info.value.public_message


def test_unreachable_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")      # nothing listens on port 9
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    with pytest.raises(LLMServiceError) as info:
        asyncio.run(LLMService(LLMSettings.from_env()).generate("s", [{"role": "user", "content": "x"}]))
    assert "unreachable" in info.value.public_message


def test_does_not_fall_back_to_openai_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-be-used")
    with pytest.raises(LLMServiceError):
        LLMSettings.from_env()
