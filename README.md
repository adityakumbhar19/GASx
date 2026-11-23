# NFC Employee Welcome (prototype)

Tap an NFC employee card on an Android phone -> the app reads the UID -> FastAPI identifies the
employee -> the phone says **"Welcome, <name>"**.

```
nfc-employee-welcome/
├── backend/   FastAPI service with PostgreSQL storage
└── android/   Android Studio project (Java, minSdk 26)
```

## 1. Backend
```bash
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nfc_attendance
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
From the project root, the equivalent Windows command is `.\run_backend.ps1`.
Using `uvicorn app.main:app` from the project root causes `ModuleNotFoundError: No module named 'app'`
because the `app` package is inside `backend/`.
Create the `nfc_attendance` PostgreSQL database before starting the server. On startup,
the server creates the tables in `schema.sql` and seeds the three employees/cards from
`backend/app/employees.py`. The mapping is now seed data; employee lookups come from PostgreSQL.
Put demo photos in `backend/seed_photos/` using the employee UID as the filename:
`0011558829.jpg`, `0005328154.jpg`, and `0011482126.jpg`. JPG, JPEG, and PNG are accepted;
startup converts them to 400x400 JPEG files and stores them in PostgreSQL.

The handover kiosk endpoints are available at `/tap/{card_uid}`, `/photo/{employee_id}`,
`/employees/{employee_id}/photo`, and `/cards` (also under `/api/v1`). Taps create an
IN/OUT row in `attendance_logs`, ignore duplicate taps within 30 seconds, and use IST
for the greeting period.
* Swagger UI: http://localhost:8000/docs  (try POST /api/v1/employee/identify with `{"nfc_uid":"04A1B2C3D4"}`)
* Health: http://localhost:8000/api/v1/health
* Find your laptop IPv4: Windows `ipconfig` (Wi-Fi adapter -> IPv4 Address); macOS `ipconfig getifaddr en0`;
  Linux `hostname -I`.
* Windows: allow Python through the firewall on **private** networks (or allow inbound TCP 8000),
  otherwise the phone cannot connect.
* From the phone's browser, open `http://<laptop-ip>:8000/api/v1/health`. If that works, the app will too.

## Architecture
```
USB NFC reader --> usb_reader.py --POST /api/v1/scan--> FastAPI (looks up PostgreSQL, stores attendance)
                                                            ^
Android app  --GET /api/v1/events?after_id=N (every 1 s)----+   -> shows name + speaks "Welcome, <name>"
```
The phone does not use NFC at all. Start order: backend -> `usb_reader/usb_reader.py` -> Android app.

## 2. USB reader script
```bash
cd usb_reader
pip install -r requirements.txt
python usb_reader.py
```
Tap a card on the reader. The terminal prints the UID and the backend result.

## 3. Android
1. Android Studio -> **Open** -> select the `android/` folder; let Gradle sync.
2. In `app/build.gradle` set `backendBaseUrl` to `"http://<laptop-ip>:8000/"`.
3. Phone on the same Wi-Fi; run the app. The pill at the top turns green ("Server connected").
4. Tap a card on the USB reader: the phone shows the employee and speaks the welcome.
5. Test Mode (bottom card) still works without any reader.

## Notes
* Unknown card -> HTTP 200 with `success:false` (the app shows "Unregistered Card", no announcement).
* Invalid UID (non-hex / missing) -> HTTP 422.
* Duplicate taps are suppressed by `usb_reader.py` (`DEBOUNCE_SECONDS`, 5 s). The app only announces scans that arrive while it is open.
* Some cards/phones present a *random* UID on each tap (privacy feature, e.g. some NTAG/DESFire configs, phone wallets).
  Those cannot be matched by UID.
* Cleartext HTTP is enabled for local development only (`usesCleartextTraffic` in the manifest).
