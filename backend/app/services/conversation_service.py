"""Employee-bound assistant sessions and the chat orchestration.

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
from typing import Callable, Dict, List, Optional, Tuple

from app.services import context_service, device_service, intent_service
from app.services.llm_service import LLMService, LLMServiceError

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
    messages: List[Dict[str, str]] = field(default_factory=list, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)  # serialises chat turns
    last_light_at: Optional[float] = field(default=None, repr=False)        # last light command sent (monotonic time)
    awaiting_choice_at: Optional[float] = field(default=None, repr=False)   # when we asked "on or off?"


class SessionStore(ABC):
    @abstractmethod
    def get_or_create_for_employee(self, employee: Dict) -> Tuple[AssistantSession, bool]:
        """Return (session, resumed). `employee` is the verified database row."""

    @abstractmethod
    def get(self, session_id: str) -> Optional[AssistantSession]:
        """Return the live session (refreshing its idle timer) or None if unknown/expired."""

    @abstractmethod
    def append_exchange(self, session: AssistantSession, user_text: str, assistant_text: str) -> None:
        """Store one completed user + assistant exchange."""


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

    def append_exchange(self, session: AssistantSession, user_text: str, assistant_text: str) -> None:
        with self._mutex:
            session.messages.append({"role": "user", "content": user_text})
            session.messages.append({"role": "assistant", "content": assistant_text})
            excess = len(session.messages) - self._max_history
            if excess > 0:
                del session.messages[:excess]       # always even, so history still starts with a user turn
            session.last_active = self._clock()


_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = InMemorySessionStore.from_env()
    return _store


_now = time.monotonic          # indirection so tests can control time

DEVICE_CONTEXT_SECONDS = 120.0   # how long "turn it off" / a bare "on" still refers to the light

CLARIFY_REPLY = "Do you want me to turn the light on or off?"
LIGHT_FAILED_REPLY = "I couldn't send the light command. Please try again."
PARTIAL_FALLBACK_REPLY = "I couldn't answer the rest of your message right now."
# Wording is deliberate: publishing to the broker is not proof that the relay switched (no feedback channel).
LIGHT_SENT_REPLY = {
    "on": "I've sent the command to turn on the light.",
    "off": "I've sent the command to turn off the light.",
}


@dataclass(frozen=True)
class ChatOutcome:
    """Result of one assistant turn. `action` tells the client what happened; `reply` is always what to speak."""
    reply: str
    action: str = "chat"            # chat | device_control | device_control_failed | clarification | unsupported_device
    device: Optional[str] = None
    state: Optional[str] = None


def _join_names(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


async def _answer_with_llm(session: AssistantSession, text: str, llm_provider: Callable[[], LLMService]) -> str:
    llm = llm_provider()
    system_prompt = context_service.build_system_prompt(session.employee_name, session.department)
    return await llm.generate(system_prompt, list(session.messages) + [{"role": "user", "content": text}])


async def _handle_device_intent(session: AssistantSession, intent: intent_service.Intent, message: str,
                                llm_provider: Callable[[], LLMService], store: SessionStore,
                                now: float) -> ChatOutcome:
    """Run a device command without involving the LLM, then (only if the message also contained a
    normal question) answer that remainder with the LLM so neither half of the message is lost."""
    parts: List[str] = []
    device: Optional[str] = None
    state: Optional[str] = None

    if intent.kind is intent_service.IntentKind.LIGHT:
        device, state = "light", intent.state
        if await device_service.set_light(intent.state):
            action = "device_control"
            parts.append(LIGHT_SENT_REPLY[intent.state])
            session.last_light_at = now
        else:
            action = "device_control_failed"
            parts.append(LIGHT_FAILED_REPLY)
        if intent.unsupported_devices:
            parts.append(f"I can't control the {_join_names(intent.unsupported_devices)} yet.")
    elif intent.kind is intent_service.IntentKind.CLARIFY:
        device, action = "light", "clarification"
        session.awaiting_choice_at = now
        parts.append(CLARIFY_REPLY)
    else:  # UNSUPPORTED
        names = intent.unsupported_devices or ("device",)
        device, action = names[0].lower(), "unsupported_device"
        parts.append(f"I can only control the light right now, so I can't do that with the {_join_names(names)} yet.")

    if intent.remainder:
        try:
            parts.append(await _answer_with_llm(session, intent.remainder, llm_provider))
        except LLMServiceError:
            parts.append(PARTIAL_FALLBACK_REPLY)   # the command already happened; do not fail the whole turn

    reply = " ".join(parts)
    store.append_exchange(session, message, reply)
    return ChatOutcome(reply=reply, action=action, device=device, state=state)


async def chat(session_id: str, message: str, llm_provider: Callable[[], LLMService],
               store: Optional[SessionStore] = None) -> Tuple[AssistantSession, ChatOutcome]:
    """Run one conversation turn: detect the intent first, then either control the device or ask the LLM.

    Normal conversation keeps the old guarantee: the exchange is saved only if the LLM call succeeds, so a
    failed request leaves the history untouched and the user can simply repeat themselves.
    """
    store = store or get_session_store()
    session = store.get(session_id)
    if session is None:
        raise SessionNotFoundError()

    async with session.lock:
        now = _now()
        light_context = session.last_light_at is not None and now - session.last_light_at <= DEVICE_CONTEXT_SECONDS
        awaiting_choice = (session.awaiting_choice_at is not None
                           and now - session.awaiting_choice_at <= DEVICE_CONTEXT_SECONDS)
        session.awaiting_choice_at = None          # a clarification only applies to the very next message

        intent = intent_service.detect_intent(message, light_context=light_context, awaiting_choice=awaiting_choice)
        logger.info("Assistant intent: %s", intent.kind.value)       # never log the message text

        if intent.kind is not intent_service.IntentKind.CHAT:
            return session, await _handle_device_intent(session, intent, message, llm_provider, store, now)

        reply = await _answer_with_llm(session, message, llm_provider)   # resolved after the session check:
        store.append_exchange(session, message, reply)                   # bad session -> 401 even if LLM unconfigured
    return session, ChatOutcome(reply=reply)
