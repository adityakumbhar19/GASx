"""Regression checks: the assistant work must not change existing routes or the MQTT payload."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.router import voice


@pytest.fixture
def client():
    return TestClient(app)


def test_all_existing_routes_still_registered():
    app.openapi_schema = None
    paths = set(app.openapi()["paths"])      # OpenAPI lists every registered path
    expected = {
        "/api/v1/health", "/api/v1/employee/identify", "/api/v1/scan", "/api/v1/events",
        "/tap/{card_uid}", "/api/v1/tap/{card_uid}", "/photo/{employee_id}", "/api/v1/photo/{employee_id}",
        "/cards", "/api/v1/cards", "/employees/{employee_id}/photo", "/api/v1/employees/{employee_id}/photo",
        "/voice-command", "/api/v1/voice-command",
        "/api/v1/assistant/session", "/api/v1/assistant/chat",
    }
    assert expected <= paths
    assert "/assistant/session" not in paths          # new router registered once, under /api/v1 only


def test_health_unchanged(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["service"] == "nfc-employee-welcome-backend"


class FakeMqttClient:
    calls = []

    def __init__(self, *args, **kwargs):
        FakeMqttClient.calls = []

    def username_pw_set(self, user, password):
        FakeMqttClient.calls.append(("auth", user, password))

    def connect(self, host, port, keepalive):
        FakeMqttClient.calls.append(("connect", host, port, keepalive))

    def publish(self, topic, payload):
        FakeMqttClient.calls.append(("publish", topic, payload))

        class Result:
            rc = 0

            def wait_for_publish(self):
                pass
        return Result()

    def disconnect(self):
        FakeMqttClient.calls.append(("disconnect",))


@pytest.mark.parametrize("path", ["/voice-command", "/api/v1/voice-command"])
def test_voice_command_payload_format_unchanged(client, monkeypatch, path):
    monkeypatch.setenv("MQTT_USERNAME", "test-user")
    monkeypatch.setenv("MQTT_PASSWORD", "test-pass")
    monkeypatch.setattr(voice.mqtt, "Client", FakeMqttClient)

    r = client.post(path, json={"text": "Turn off the light"})
    assert r.json() == {"success": True, "action": "off", "spoken_text": "Turn off the light",
                        "message": "The light has been turned off"}
    calls = FakeMqttClient.calls
    assert ("auth", "test-user", "test-pass") in calls
    assert ("connect", "10.1.1.177", 1883, 10) in calls
    publish = [c for c in calls if c[0] == "publish"][0]
    assert publish[1] == "relayCtr"
    assert publish[2] == '{"NM":"2c:bc:bb:0d:07:20","state":"0"}'      # byte-for-byte the old payload

    r = client.post(path, json={"text": "turn the lights on"})
    assert r.json()["action"] == "on"
    assert [c for c in FakeMqttClient.calls if c[0] == "publish"][0][2] == '{"NM":"2c:bc:bb:0d:07:20","state":"1"}'


def test_missing_mqtt_credentials_fail_safely_without_connecting(client, monkeypatch):
    monkeypatch.delenv("MQTT_USERNAME", raising=False)
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    monkeypatch.setattr(voice.mqtt, "Client", FakeMqttClient)
    FakeMqttClient.calls = []
    r = client.post("/voice-command", json={"text": "Turn off the light"})
    assert r.json()["success"] is False and r.json()["message"] == "Could not send the light command."
    assert FakeMqttClient.calls == []


def test_non_light_voice_commands_unchanged(client):
    assert client.post("/voice-command", json={"text": "play music"}).json()["message"] == \
        "Please include light in your command."
