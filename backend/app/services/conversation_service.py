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

from app.services import context_service
from app.services.llm_service import LLMService

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


async def chat(session_id: str, message: str, llm_provider: Callable[[], LLMService],
               store: Optional[SessionStore] = None) -> Tuple[AssistantSession, str]:
    """Run one conversation turn. The exchange is saved only if the LLM call succeeds, so a failed
    request leaves the history untouched and the user can simply repeat themselves."""
    store = store or get_session_store()
    session = store.get(session_id)
    if session is None:
        raise SessionNotFoundError()

    llm = llm_provider()   # resolved after the session check: bad session -> 401 even if LLM is unconfigured
    async with session.lock:
        history = list(session.messages)
        system_prompt = context_service.build_system_prompt(session.employee_name, session.department)
        reply = await llm.generate(system_prompt, history + [{"role": "user", "content": message}])
        store.append_exchange(session, message, reply)
    return session, reply
