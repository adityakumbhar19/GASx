"""Initial employee data and the database-backed lookup used by the API.

Keys are NFC UIDs in UPPERCASE hexadecimal with no separators.
To test with your real cards: tap a card, read the UID shown in the Android app
("NFC UID" field), and add it here. The server auto-reloads with --reload.

The mapping remains as seed data so the three existing prototype employees can
be inserted into PostgreSQL without losing their leading-zero card UIDs.
"""
from typing import Dict, Optional

from app.database import find_employee as find_employee_in_db

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
}

# Defensive: guarantee lookup keys are normalized even if someone edits the dict sloppily.
def find_employee(nfc_uid: str) -> Optional[Dict[str, str]]:
    """Return an active employee from PostgreSQL, or None if unregistered."""
    return find_employee_in_db(nfc_uid)
