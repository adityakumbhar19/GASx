"""End-to-end through the REAL LLMService (OpenAI SDK over HTTP to a local mock provider) and the REAL
publish_light_state with a fake MQTT client. Proves tool_calls survive the wire and the payload is unchanged."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.router import assistant as assistant_router
from app.router import voice
from app.services import conversation_service as cs
from app.services import llm_service
from app.services.llm_service import LLMService, LLMSettings

UID = "0011482126"
EMPLOYEE = {"id": 7, "employee_id": UID, "employee_name": "Gaurav", "department": None, "card_uid": UID}
SEEN = []


class Provider(BaseHTTPRequestHandler):
    """Behaves like a tool-calling model: asks for control_light once, then answers after the tool result."""
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        last = body["messages"][-1]
        if last["role"] == "tool":
            msg = {"role": "assistant", "content": "I've sent the command to turn on the light."}
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_abc", "type": "function",
                 "function": {"name": "control_light", "arguments": "{\"state\": \"on\"}"}}]}
        data = json.dumps({"choices": [{"message": msg, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeMqtt:
    calls = []

    def __init__(self, *a, **k): FakeMqtt.calls = []
    def username_pw_set(self, u, p): pass
    def connect(self, host, port, keepalive): pass
    def disconnect(self): pass

    def publish(self, topic, payload):
        FakeMqtt.calls.append((topic, payload))

        class R:
            rc = 0
            def wait_for_publish(self): pass
        return R()


def test_tool_call_over_http_reaches_mqtt_with_unchanged_payload(monkeypatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("LLM_API_KEY", "k"); monkeypatch.setenv("LLM_MODEL", "m")
        monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{httpd.server_address[1]}/v1")
        monkeypatch.setenv("LLM_MAX_RETRIES", "0")
        monkeypatch.setenv("MQTT_USERNAME", "u"); monkeypatch.setenv("MQTT_PASSWORD", "p")
        monkeypatch.setattr(voice.mqtt, "Client", FakeMqtt)
        monkeypatch.setattr(cs, "_store", None)
        monkeypatch.setattr(llm_service, "_service", None)
        monkeypatch.setattr(assistant_router, "find_employee", lambda uid: EMPLOYEE)
        SEEN.clear()

        client = TestClient(app)
        sid = client.post("/api/v1/assistant/session", json={"nfc_uid": UID}).json()["session_id"]
        body = client.post("/api/v1/assistant/chat", json={"session_id": sid, "message": "Turn on the light"}).json()

        assert FakeMqtt.calls == [("relayCtr", '{"NM":"2c:bc:bb:0d:07:20","state":"1"}')]
        assert body["action"] == "device_control" and body["state"] == "on"
        assert body["tool_calls"] == [{"tool": "control_light", "arguments": {"state": "on"}, "success": True}]
        # what the provider received: tool schema on request 1, tool result message on request 2
        assert SEEN[0]["tools"][0]["function"]["name"] == "control_light" and SEEN[0]["tool_choice"] == "auto"
        assert SEEN[1]["messages"][-1]["role"] == "tool" and SEEN[1]["messages"][-1]["tool_call_id"] == "call_abc"
        assert "MQTT_PASSWORD" not in json.dumps(SEEN) and "p" != SEEN[0]["messages"][0]["content"]
    finally:
        httpd.shutdown()
