"""
Keyboard-style USB card reader client.

These readers "type" the card number followed by Enter, like a keyboard. This script
reads those lines from its own terminal window and reports each card to the backend
(POST /api/v1/scan). The Android app then speaks the welcome.

Usage:
    pip install requests
    python keyboard_reader.py
Keep THIS terminal window focused while tapping cards (that is where the reader types).
"""
import time

import requests

API_URL = "http://localhost:8000/api/v1/scan"
DEBOUNCE_SECONDS = 5  # same card seen again within this window is ignored


def report(uid: str) -> None:
    print(f"[Card] {uid}")
    try:
        resp = requests.post(API_URL, json={"nfc_uid": uid}, timeout=5)
    except requests.RequestException as exc:
        print(f"[Backend error] {exc}")
        return

    if resp.status_code == 200:
        body = resp.json()
        if body.get("success"):
            print(f"[OK] {body['employee_name']} ({body['employee_id']})")
        else:
            print("[Unregistered card] Add this value to backend/app/employees.py:")
            print(f'    "{uid}": {{"employee_id": "EMP00X", "employee_name": "Name Here"}},')
    elif resp.status_code == 422:
        print("[Rejected] The backend only accepts hex characters (0-9, A-F). Value was not valid.")
    else:
        print(f"[Backend] HTTP {resp.status_code}: {resp.text}")


def main() -> None:
    print("Waiting for cards... tap a card on the reader (Ctrl+C to quit)")
    last_uid = None
    last_time = 0.0
    while True:
        try:
            raw = input()
        except (EOFError, KeyboardInterrupt):
            print("\nStopped.")
            return

        # Exactly what the reader typed, minus spaces/colons, uppercased.
        uid = raw.strip().replace(" ", "").replace(":", "").upper()
        if not uid:
            continue

        now = time.monotonic()
        if uid == last_uid and now - last_time < DEBOUNCE_SECONDS:
            last_time = now  # card still on the reader
            continue
        last_uid, last_time = uid, now
        report(uid)


if __name__ == "__main__":
    main()