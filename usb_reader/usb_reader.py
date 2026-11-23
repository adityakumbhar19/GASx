"""
USB NFC reader client (PC/SC readers such as ACR122U, ACR1252U, etc.).

Reads the card UID from the USB reader and reports it to the FastAPI backend
(POST /api/v1/scan). The backend looks up the employee and records the event;
the Android app listens to the backend and speaks "Welcome, <name>".

Run (backend must already be running):
    pip install -r requirements.txt
    python usb_reader.py
"""
import time

import pyttsx3
import requests
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers

API_URL = "http://localhost:8000/api/v1/scan"
SPEAK_ON_LAPTOP = False       # set True to also speak the welcome on this computer
DEBOUNCE_SECONDS = 5          # same card within this window is ignored
POLL_INTERVAL = 0.3           # seconds between reader polls
GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]  # standard PC/SC "get UID" command


def speak(text: str) -> None:
    try:
        engine = pyttsx3.init()  # fresh engine each time avoids hangs on Windows
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as exc:
        print(f"[TTS error] {exc}")


def read_uid(reader) -> str | None:
    """Return the UID of the card on the reader as uppercase hex, or None if no card."""
    connection = reader.createConnection()
    try:
        connection.connect()
        data, sw1, sw2 = connection.transmit(GET_UID_APDU)
        if (sw1, sw2) != (0x90, 0x00):
            print(f"[Reader] Could not read UID (status {sw1:02X}{sw2:02X})")
            return None
        return "".join(f"{b:02X}" for b in data)
    except (NoCardException, CardConnectionException):
        return None
    finally:
        try:
            connection.disconnect()
        except Exception:
            pass


def identify(uid: str) -> None:
    print(f"[Card] UID = {uid}")
    try:
        resp = requests.post(API_URL, json={"nfc_uid": uid}, timeout=5)
    except requests.RequestException as exc:
        print(f"[Backend error] {exc}")
        return

    if resp.status_code != 200:
        print(f"[Backend] HTTP {resp.status_code}: {resp.text}")
        return

    body = resp.json()
    if body.get("success"):
        name = body["employee_name"]
        print(f"[OK] {name} ({body['employee_id']})")
        if SPEAK_ON_LAPTOP:
            speak(f"Welcome, {name}")
    else:
        print("[Unregistered Card]")


def main() -> None:
    available = readers()
    if not available:
        print("No PC/SC reader found. Is the USB reader plugged in and its driver installed?")
        return
    reader = available[0]
    print(f"Using reader: {reader}")
    print("Tap a card... (Ctrl+C to quit)")

    last_uid = None
    last_seen = 0.0
    while True:
        uid = read_uid(reader)
        now = time.monotonic()
        if uid:
            if uid == last_uid and now - last_seen < DEBOUNCE_SECONDS:
                last_seen = now  # card still on the reader
            else:
                last_uid, last_seen = uid, now
                identify(uid)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
