"""
In-memory log of recent card scans (prototype).

The USB reader script posts scans to /api/v1/scan -> add_event().
The Android app polls /api/v1/events -> events_after().

SERVER_ID changes every time the backend restarts, so clients know the numeric
event ids restarted from 1 and can resynchronise instead of waiting forever.
"""
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

SERVER_ID: str = uuid.uuid4().hex
_MAX_EVENTS = 200

_lock = threading.Lock()
_events: Deque[Dict] = deque(maxlen=_MAX_EVENTS)
_next_id = 1


def add_event(
    nfc_uid: str,
    success: bool,
    message: str,
    employee_id: Optional[str],
    employee_name: Optional[str],
    photo_url: Optional[str],
) -> Dict:
    global _next_id
    with _lock:
        event = {
            "id": _next_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nfc_uid": nfc_uid,
            "success": success,
            "message": message,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "photo_url": photo_url,
        }
        _next_id += 1
        _events.append(event)
        return event


def latest_id() -> int:
    """Id of the newest event, or 0 if there are none yet."""
    with _lock:
        return _next_id - 1


def events_after(after_id: int, limit: int = 50) -> List[Dict]:
    with _lock:
        return [e for e in _events if e["id"] > after_id][:limit]
