"""Tool-calling orchestration through the real FastAPI app: scripted LLM, fake MQTT publisher, no network.

The scripted LLM plays the role of the model. What is verified here is everything the BACKEND is responsible
for: the loop, validation, allow-listing, de-duplication, failure handling, history and the response contract.
(Whether a real model picks the right tool for a sentence is a model-quality question - see the manual checklist.)
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.router import assistant as assistant_router
from app.services import conversation_service as cs
from app.services import device_service
from app.services.llm_service import LLMServiceError, LLMTurn, ToolCallRequest

UID = "0011482126"
EMPLOYEE = {"id": 7, "employee_id": UID, "employee_name": "Gaurav", "department": "R&D", "card_uid": UID}


def call(name="control_light", args=None, cid="c1", raw=None):
    return ToolCallRequest(id=cid, name=name, arguments=raw if raw is not None else json.dumps(args or {}))


class ScriptedLLM:
    """Plays back a list of LLMTurn (or exceptions) and records what it was sent."""
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def complete(self, system, messages, tools=None, tool_choice="auto"):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture(autouse=True)
def state(monkeypatch):
    monkeypatch.setattr(cs, "_store", None)
    monkeypatch.setattr(assistant_router, "find_employee", lambda uid: EMPLOYEE if uid == UID else None)
    monkeypatch.delenv("DEVICE_CONTROL_ALLOWED_EMPLOYEE_IDS", raising=False)
    published = []
    monkeypatch.setattr(device_service, "publish_light_state", lambda v: published.append(v), raising=False)

    async def fake_set_light(s):
        if fake_set_light.fail:
            return False
        published.append("1" if s == "on" else "0")
        return True
    fake_set_light.fail = False
    monkeypatch.setattr(device_service, "set_light", fake_set_light)
    return type("S", (), {"published": published, "mqtt": fake_set_light})


@pytest.fixture
def client():
    return TestClient(app)


def use(monkeypatch, llm):
    monkeypatch.setattr(assistant_router, "get_llm_service", lambda: llm)


def session(client):
    return client.post("/api/v1/assistant/session", json={"nfc_uid": UID}).json()["session_id"]


def say(client, sid, text):
    r = client.post("/api/v1/assistant/chat", json={"session_id": sid, "message": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_normal_question_never_touches_the_light(client, monkeypatch, state):
    use(monkeypatch, ScriptedLLM([LLMTurn("Computer vision lets machines interpret images.")]))
    body = say(client, session(client), "What is computer vision?")
    assert body["action"] == "chat" and body["tool_calls"] == [] and body["device"] is None
    assert state.published == []


def test_tool_schema_is_sent_with_every_request(client, monkeypatch):
    llm = ScriptedLLM([LLMTurn("Hi!")])
    use(monkeypatch, llm)
    say(client, session(client), "Hello")
    tool = llm.calls[0]["tools"][0]["function"]
    assert tool["name"] == "control_light"
    assert tool["parameters"]["properties"]["state"]["enum"] == ["on", "off"]


@pytest.mark.parametrize("state_arg,payload", [("on", "1"), ("off", "0")])
def test_light_command_full_cycle(client, monkeypatch, state, state_arg, payload):
    llm = ScriptedLLM([LLMTurn("", [call(args={"state": state_arg})]),
                       LLMTurn(f"I've sent the command to turn {state_arg} the light.")])
    use(monkeypatch, llm)
    body = say(client, session(client), "Turn the light " + state_arg)
    assert state.published == [payload]
    assert body["action"] == "device_control" and body["device"] == "light" and body["state"] == state_arg
    assert body["tool_calls"] == [{"tool": "control_light", "arguments": {"state": state_arg}, "success": True}]
    assert body["reply"] == f"I've sent the command to turn {state_arg} the light."
    # the second LLM call received the assistant tool_call and the tool result
    second = llm.calls[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "control_light"
    result = json.loads(second[-1]["content"])
    assert second[-1]["role"] == "tool" and result["success"] is True and "not confirmed" in result["message"]


def test_command_plus_question_in_one_message(client, monkeypatch, state):
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args={"state": "on"})]),
                                  LLMTurn("Light command sent. MQTT is a lightweight publish subscribe protocol.")]))
    body = say(client, session(client), "Turn on the light and explain how MQTT works")
    assert state.published == ["1"] and body["action"] == "device_control" and "MQTT" in body["reply"]


def test_mqtt_failure_is_reported_honestly_and_does_not_crash(client, monkeypatch, state):
    state.mqtt.fail = True
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args={"state": "on"})]),
                                  LLMTurn("I couldn't send the light command. Please try again.")]))
    body = say(client, session(client), "Turn on the light")
    assert body["action"] == "device_control_failed" and body["tool_calls"][0]["success"] is False
    assert body["success"] is True      # `reply` is valid; clients keep parsing exactly as before


def test_llm_failure_after_tool_ran_still_reports_the_command(client, monkeypatch, state):
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args={"state": "off"})]), LLMServiceError("busy")]))
    body = say(client, session(client), "Turn off the light")
    assert state.published == ["0"] and body["action"] == "device_control"
    assert body["reply"] == "I've sent the command to turn off the light."


def test_llm_failure_before_any_tool_gives_503_and_keeps_history_clean(client, monkeypatch):
    llm = ScriptedLLM([LLMServiceError("The assistant is busy. Please try again in a moment."), LLMTurn("ok")])
    use(monkeypatch, llm)
    sid = session(client)
    r = client.post("/api/v1/assistant/chat", json={"session_id": sid, "message": "hello"})
    assert r.status_code == 503
    say(client, sid, "hello again")
    assert llm.calls[-1]["messages"] == [{"role": "user", "content": "hello again"}]


@pytest.mark.parametrize("bad", [
    {"state": "dim"}, {"state": 1}, {}, {"state": "on", "extra": "x"}, {"state": None},
])
def test_invalid_arguments_are_rejected_and_never_reach_mqtt(client, monkeypatch, state, bad):
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args=bad)]), LLMTurn("Do you want it on or off?")]))
    body = say(client, session(client), "Do something with the lights")
    assert state.published == [] and body["action"] == "chat"
    assert body["tool_calls"][0]["success"] is False and body["reply"] == "Do you want it on or off?"


def test_unparseable_arguments_rejected(client, monkeypatch, state):
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(raw="{not json")]), LLMTurn("Sorry, on or off?")]))
    say(client, session(client), "lights")
    assert state.published == []


def test_unregistered_tool_names_are_never_executed(client, monkeypatch, state):
    llm = ScriptedLLM([LLMTurn("", [call(name="os.system", args={"cmd": "rm -rf /"}),
                                    call(name="control_ac", args={"state": "on"}, cid="c2")]),
                       LLMTurn("I can only control the light.")])
    use(monkeypatch, llm)
    body = say(client, session(client), "hack")
    assert state.published == [] and body["action"] == "chat"
    assert [c["success"] for c in body["tool_calls"]] == [False, False]
    assert "Unknown tool" in llm.calls[1]["messages"][-1]["content"]


def test_duplicate_identical_calls_in_one_turn_publish_once(client, monkeypatch, state):
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args={"state": "on"}), call(args={"state": "on"}, cid="c2")]),
                                  LLMTurn("Sent.")]))
    say(client, session(client), "Turn on the light")
    assert state.published == ["1"]


def test_conflicting_calls_in_one_turn_run_only_the_first(client, monkeypatch, state):
    llm = ScriptedLLM([LLMTurn("", [call(args={"state": "on"}), call(args={"state": "off"}, cid="c2")]),
                       LLMTurn("Which one do you want?")])
    use(monkeypatch, llm)
    say(client, session(client), "on and off")
    assert state.published == ["1"]
    assert "Conflicting" in llm.calls[1]["messages"][-1]["content"]


def test_tool_loop_is_bounded(client, monkeypatch, state):
    monkeypatch.setenv("ASSISTANT_MAX_TOOL_ITERATIONS", "2")
    looping = [LLMTurn("", [call(args={"state": "on"}, cid=f"c{i}")]) for i in range(10)]
    llm = ScriptedLLM(looping)
    use(monkeypatch, llm)
    body = say(client, session(client), "Turn on the light")
    assert len(llm.calls) == 3 and llm.calls[-1]["tool_choice"] == "none"      # 2 tool rounds + forced final
    assert state.published == ["1"]                                           # not re-run each round
    assert body["reply"] == "I've sent the command to turn on the light."


def test_unauthorized_employee_cannot_control_the_light(client, monkeypatch, state):
    monkeypatch.setenv("DEVICE_CONTROL_ALLOWED_EMPLOYEE_IDS", "SOMEONE-ELSE")
    use(monkeypatch, ScriptedLLM([LLMTurn("", [call(args={"state": "on"})]), LLMTurn("Sorry, not permitted.")]))
    body = say(client, session(client), "Turn on the light")
    assert state.published == [] and body["tool_calls"][0]["success"] is False


def test_history_keeps_tool_turns_and_mixes_chat_and_commands(client, monkeypatch, state):
    llm = ScriptedLLM([LLMTurn("Hello!"),
                       LLMTurn("", [call(args={"state": "on"})]), LLMTurn("Sent."),
                       LLMTurn("", [call(args={"state": "off"}, cid="c9")]), LLMTurn("Sent off."),
                       LLMTurn("Because it saves energy.")])
    use(monkeypatch, llm)
    sid = session(client)
    say(client, sid, "hi")                                   # chat
    say(client, sid, "turn on the light")                    # tool right after a question
    say(client, sid, "turn it off")                          # pronoun resolved by the LLM from history
    after = say(client, sid, "why turn lights off when leaving?")   # question right after a tool
    assert after["action"] == "chat" and state.published == ["1", "0"]
    roles = [m["role"] for m in llm.calls[-1]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "tool", "assistant",
                     "user", "assistant", "tool", "assistant", "user"]


def test_history_trim_never_splits_a_tool_turn():
    store = cs.InMemorySessionStore(max_history_messages=6)
    s, _ = store.get_or_create_for_employee(EMPLOYEE)
    tool_turn = [{"role": "user", "content": "u"}, {"role": "assistant", "content": None, "tool_calls": []},
                 {"role": "tool", "tool_call_id": "1", "content": "{}"}, {"role": "assistant", "content": "a"}]
    store.append_turn(s, tool_turn)
    store.append_turn(s, tool_turn)
    assert s.messages[0]["role"] == "user" and len(s.messages) == 4
