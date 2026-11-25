"""Initial employee data and the employee lookup used by the API.

Keys are NFC UIDs in UPPERCASE hexadecimal with no separators.
To test with your real cards: tap a card, read the UID shown in the Android app
("NFC UID" field), and add it here. The server auto-reloads with --reload.

Two modes, chosen by the EMPLOYEE_SOURCE environment variable (backend/.env):

  EMPLOYEE_SOURCE=database   (default) PostgreSQL, exactly as before.
  EMPLOYEE_SOURCE=memory     Use ONLY the EMPLOYEES dictionary below. PostgreSQL is never touched,
                             so you can test the assistant / voice flow without a database.
                             Attendance IN/OUT is then kept in memory only (lost on restart), and
                             photos are unavailable.

The mapping also remains as seed data so the prototype employees can be inserted into PostgreSQL
without losing their leading-zero card UIDs.
"""
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from app.database import IST
from app.database import find_employee as find_employee_in_db
from app.database import record_tap as record_tap_in_db

EMPLOYEES: Dict[str, Dict[str, str]] = {
    "0011558829": {
        "employee_id": "0011558829",
        "employee_name": "Aditya",
    },
    "0005328154": {
        "employee_id": "0005328154",
        "employee_name": "Shubham",
    },
    "0011482126": {
        "employee_id": "0011482126",
        "employee_name": "Gaurav"
    },

    "0014724390":{
        "employee_id": "0014724390",
        "employee_name": "Aakanksha"
    }
    # Optional for memory mode: add "department": "R&D" to any entry to give the assistant that context.
}

DUPLICATE_TAP_SECONDS = 30  # same rule as the PostgreSQL version


def use_memory_employees() -> bool:
    """True when EMPLOYEE_SOURCE=memory (read at call time, so .env changes apply after a restart)."""
    return os.getenv("EMPLOYEE_SOURCE", "database").strip().lower() == "memory"


def _memory_lookup(nfc_uid: str) -> Optional[Dict]:
    """Same shape as the database row: id, employee_id, employee_name, department, card_uid."""
    uid = nfc_uid.strip().upper()
    for index, (key, employee) in enumerate(EMPLOYEES.items(), start=1):
        if key.strip().upper() == uid:
            return {
                "id": index,   # stable while the EMPLOYEES order is unchanged
                "employee_id": employee["employee_id"],
                "employee_name": employee["employee_name"],
                "department": employee.get("department"),
                "card_uid": uid,
            }
    return None


def find_employee(nfc_uid: str) -> Optional[Dict]:
    """Return an active employee, or None if unregistered."""
    if use_memory_employees():
        return _memory_lookup(nfc_uid)
    return find_employee_in_db(nfc_uid)


_last_tap: Dict[int, Tuple[str, datetime]] = {}
_tap_lock = threading.Lock()


def record_tap(nfc_uid: str) -> Optional[Dict]:
    """Resolve a card and record the next IN/OUT event (database), or simulate it in memory."""
    if not use_memory_employees():
        return record_tap_in_db(nfc_uid)

    employee = _memory_lookup(nfc_uid)
    if employee is None:
        return None
    now = datetime.now(IST)
    with _tap_lock:
        previous = _last_tap.get(employee["id"])
        if previous and (now - previous[1]) < timedelta(seconds=DUPLICATE_TAP_SECONDS):
            employee.update(direction=previous[0], tapped_at=previous[1], duplicate=True)
            return employee
        direction = "OUT" if previous and previous[0] == "IN" else "IN"
        _last_tap[employee["id"]] = (direction, now)
    employee.update(direction=direction, tapped_at=now, duplicate=False)
    return employee
