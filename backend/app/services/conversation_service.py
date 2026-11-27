"""Employee-bound assistant sessions and the chat orchestration.

One assistant workflow for everything: every message goes to the LLM together with the registered tool
definitions (app/tools). The LLM decides whether to answer in text or call a tool; this module runs the
tool-calling loop. There is no keyword/intent routing in front of the LLM.

Design: ONE persistent session per employee. Tapping the card again returns the same session
(same history) instead of starting a new one. A session ends only after a long idle period
(ASSISTANT_SESSION_IDLE_HOURS, default 24; 0 = never) or when the server restarts.

The session id is a bearer credential: it is random (256 bits), only ever travels in JSON
bodies, and is never logged or included in repr().

Storage is behind the SessionStore interface so the in-memory implementation can later be
replaced by PostgreSQL or Redis without touching the router. Limitation of the in-memory
store: it lives in one process (run uvicorn with a single worker) and is lost on restart.
"""
import asyncio
import logging
import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services import context_service
from app.services.llm_service import LLMService, LLMServiceError
from app.services.tool_executor import ExecutedCall, ToolExecutor
from app.tools import get_tool_registry
from app.tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger("nfc-welcome.assistant")


class SessionNotFoundError(Exception):
    """Unknown or expired session id."""


@dataclass
class AssistantSession:
    session_id: str = field(repr=False)
    employee_pk: int
    employee_code: str = field(repr=False)
    employee_name: str = field(repr=False)
    department: Optional[str] = field(repr=False)
    created_at: float
    last_active: float
    # OpenAI-format history: user / assistant (incl. tool_calls) / tool messages, always in whole turns
    messages: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)  # serialises chat turns


class SessionStore(ABC):
    @abstractmethod
    def get_or_create_for_employee(self, employee: Dict) -> Tuple[AssistantSession, bool]:
        """Return (session, resumed). `employee` is the verified database row."""

    @abstractmethod
    def get(self, session_id: str) -> Optional[AssistantSession]:
        """Return the live session (refreshing its idle timer) or None if unknown/expired."""

    @abstractmethod
    def append_turn(self, session: AssistantSession, messages: List[Dict[str, Any]]) -> None:
        """Store one completed turn: the user message, any assistant tool calls and tool results, and the
        final assistant reply. History is trimmed only at turn boundaries so tool messages stay paired."""

    def append_exchange(self, session: AssistantSession, user_text: str, assistant_text: str) -> None:
        self.append_turn(session, [{"role": "user", "content": user_text},
                                   {"role": "assistant", "content": assistant_text}])


class InMemorySessionStore(SessionStore):
    def __init__(self, idle_ttl_seconds: Optional[float] = 24 * 3600, max_history_messages: int = 40,
                 max_sessions: int = 1000, clock: Callable[[], float] = time.monotonic):
        self._idle_ttl = idle_ttl_seconds
        self._max_history = max(2, max_history_messages - (max_history_messages % 2))  # keep user/assistant pairs
        self._max_sessions = max(1, max_sessions)
        self._clock = clock
        self._mutex = threading.Lock()
        self._by_id: Dict[str, AssistantSession] = {}
        self._by_employee: Dict[int, str] = {}

    @classmethod
    def from_env(cls) -> "InMemorySessionStore":
        def number(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, "").strip() or default)
            except ValueError:
                logger.warning("%s is not a number - using %s", name, default)
                return default

        hours = number("ASSISTANT_SESSION_IDLE_HOURS", 24)
        return cls(
            idle_ttl_seconds=hours * 3600 if hours > 0 else None,
            max_history_messages=int(number("ASSISTANT_MAX_HISTORY_MESSAGES", 40)),
            max_sessions=int(number("ASSISTANT_MAX_SESSIONS", 1000)),
        )

    # -- internals (call with _mutex held) --
    def _expired(self, session: AssistantSession, now: float) -> bool:
        return self._idle_ttl is not None and (now - session.last_active) > self._idle_ttl

    def _remove(self, session: AssistantSession) -> None:
        self._by_id.pop(session.session_id, None)
        if self._by_employee.get(session.employee_pk) == session.session_id:
            del self._by_employee[session.employee_pk]

    def _purge(self, now: float) -> None:
        for session in [s for s in self._by_id.values() if self._expired(s, now)]:
            self._remove(session)

    # -- SessionStore --
    def get_or_create_for_employee(self, employee: Dict) -> Tuple[AssistantSession, bool]:
        pk = int(employee["id"])
        now = self._clock()
        with self._mutex:
            self._purge(now)
            existing = self._by_id.get(self._by_employee.get(pk, ""))
            if existing is not None:
                existing.last_active = now
                return existing, True

            while len(self._by_id) >= self._max_sessions:      # evict the least recently used
                self._remove(min(self._by_id.values(), key=lambda s: s.last_active))

            session = AssistantSession(
                session_id=secrets.token_urlsafe(32),
                employee_pk=pk,
                employee_code=str(employee.get("employee_id") or ""),
                employee_name=context_service.clean_text(employee.get("employee_name")) or "colleague",
                department=context_service.clean_text(employee.get("department")) or None,
                created_at=now,
                last_active=now,
            )
            self._by_id[session.session_id] = session
            self._by_employee[pk] = session.session_id
            return session, False

    def get(self, session_id: str) -> Optional[AssistantSession]:
        now = self._clock()
        with self._mutex:
            session = self._by_id.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                self._remove(session)
                return None
            session.last_active = now
            return session

    def append_turn(self, session: AssistantSession, messages: List[Dict[str, Any]]) -> None:
        with self._mutex:
            session.messages.extend(messages)
            while len(session.messages) > self._max_history:
                nxt = next((i for i in range(1, len(session.messages)) if session.messages[i]["role"] == "user"), None)
                if nxt is None:
                    break
                del session.messages[:nxt]      # drop the oldest whole turn; history still starts with a user message
            session.last_active = self._clock()


_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = InMemorySessionStore.from_env()
    return _store


def _max_tool_rounds() -> int:
    try:
        return max(1, int(os.getenv("ASSISTANT_MAX_TOOL_ITERATIONS", "").strip() or 3))
    except ValueError:
        return 3


@dataclass(frozen=True)
class ChatOutcome:
    """Result of one assistant turn. `action` tells the client what happened; `reply` is always what to speak."""
    reply: str
    action: str = "chat"            # chat | device_control | device_control_failed
    device: Optional[str] = None    # e.g. "light" when a device tool ran
    state: Optional[str] = None     # e.g. "on" / "off"
    tool_calls: Tuple[Dict[str, Any], ...] = ()


def _outcome(reply: str, executed: List[ExecutedCall]) -> ChatOutcome:
    ran = [c for c in executed if c.ran]
    if not ran:
        action = "chat"                          # nothing was executed (rejected calls are only reported)
    elif all(c.success for c in ran):
        action = "device_control"
    else:
        action = "device_control_failed"
    last = next((c for c in reversed(ran) if c.device), None)
    return ChatOutcome(
        reply=reply, action=action,
        device=last.device if last else None,
        state=last.arguments.get("state") if last else None,
        tool_calls=tuple({"tool": c.tool, "arguments": c.arguments, "success": c.success} for c in executed),
    )


async def _run_turn(session: AssistantSession, text: str, llm: LLMService, registry: ToolRegistry,
                    ) -> Tuple[List[Dict[str, Any]], str, List[ExecutedCall]]:
    """The tool-calling loop. Returns (messages of this turn, final reply, executed tool calls).

    LLM -> (text? done) | (tool calls? validate + execute each, send results back, repeat).
    After ASSISTANT_MAX_TOOL_ITERATIONS rounds the model is told it may not call tools any more.
    """
    system_prompt = context_service.build_system_prompt(session.employee_name, session.department)
    ctx = ToolContext(session.employee_pk, session.employee_code, session.employee_name, session.department)
    executor = ToolExecutor(registry)
    schemas = registry.openai_schemas()
    history = list(session.messages)
    turn: List[Dict[str, Any]] = [{"role": "user", "content": text}]
    executed: List[ExecutedCall] = []
    turn_cache: Dict[Tuple[str, str], ExecutedCall] = {}
    rounds = _max_tool_rounds()

    for round_no in range(rounds + 1):
        choice = "auto" if round_no < rounds else "none"
        try:
            step = await llm.complete(system_prompt, history + turn, tools=schemas, tool_choice=choice)
        except LLMServiceError:
            if not executed:
                raise                              # nothing happened yet: fail the request, history untouched
            # A tool already ran, so never lose that fact: answer from the tool results themselves.
            logger.warning("LLM failed after tool execution; replying from tool results")
            reply = " ".join(dict.fromkeys(c.user_message for c in executed))
            turn.append({"role": "assistant", "content": reply})
            return turn, reply, executed

        if not step.tool_calls or choice == "none":
            reply = step.text or " ".join(dict.fromkeys(c.user_message for c in executed)) or \
                "I couldn't complete that request."
            turn.append({"role": "assistant", "content": reply})
            return turn, reply, executed

        turn.append({"role": "assistant", "content": step.text or None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in step.tool_calls]})
        for call in step.tool_calls:
            result = await executor.execute(call.name, call.arguments, ctx, turn_cache)
            executed.append(result)
            turn.append({"role": "tool", "tool_call_id": call.id, "content": result.content})

    raise AssertionError("unreachable")          # the last round always has tool_choice="none"


async def chat(session_id: str, message: str, llm_provider: Callable[[], LLMService],
               store: Optional[SessionStore] = None,
               registry: Optional[ToolRegistry] = None) -> Tuple[AssistantSession, ChatOutcome]:
    """Run one conversation turn through the unified LLM + tools workflow.

    The turn is saved only if it completes, so a failed request leaves the history untouched and the
    user can simply repeat themselves. (If a tool already ran, the turn IS saved: the command happened.)
    """
    store = store or get_session_store()
    session = store.get(session_id)
    if session is None:
        raise SessionNotFoundError()

    async with session.lock:                      # one turn at a time per employee: no interleaved tool runs
        llm = llm_provider()                      # resolved after the session check: bad session -> 401 even
        turn, reply, executed = await _run_turn(session, message, llm, registry or get_tool_registry())   # if LLM unconfigured
        store.append_turn(session, turn)
    return session, _outcome(reply, executed)
