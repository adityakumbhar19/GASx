# NFC Employee Welcome — Complete Project Handover

> Purpose: hand this file to ChatGPT or another coding assistant to continue development without losing project context.

## 1. Project summary

This is an employee NFC welcome/kiosk prototype for Windows and Android.

Normal flow:

1. An NFC card is tapped on a USB NFC reader attached to a laptop.
2. `usb_reader/usb_reader.py` reads the card UID and calls `POST /api/v1/scan`.
3. FastAPI looks up the UID in PostgreSQL.
4. The backend records attendance (`IN` or `OUT`) and publishes an in-memory event.
5. The Android app polls `GET /api/v1/events` every second.
6. The app displays the employee/photo and speaks `Welcome, <name>` using Android TTS.

Important: the Android app does **not** read NFC directly. It is a polling display kiosk. Android NFC classes and manifest NFC declarations were not implemented as part of the active flow.

## 2. Repository layout

```text
nfc-employee-welcome/
├── README.md
├── PROJECT_HANDOVER.md
├── run_backend.ps1
├── backend/
│   ├── requirements.txt
│   ├── schema.sql
│   ├── seed_photos/
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       ├── database.py
│       ├── employees.py
│       ├── events.py
│       ├── schemas.py
│       ├── seed.py
│       └── router/
│           ├── __init__.py
│           ├── employee.py
│           ├── kiosk.py
│           └── scan.py
├── usb_reader/
│   ├── requirements.txt
│   ├── usb_reader.py
│   └── keyboard_reader.py
└── android/
    ├── build.gradle
    ├── gradle.properties
    ├── settings.gradle
    └── app/
        ├── build.gradle
        └── src/main/
            ├── AndroidManifest.xml
            ├── java/com/example/nfcemployeewelcome/
            └── res/
```

## 3. Architecture

```text
USB/keyboard card reader
        |
        | HTTP POST /api/v1/scan
        v
FastAPI backend
        |
        +--> PostgreSQL: employees, cards, attendance, photos
        |
        +--> In-memory events: newest scan notification
        |
        | HTTP GET /api/v1/events every 1 second
        v
Android app -> photo + UI + Android TextToSpeech
```

Components:

- **FastAPI backend:** source of truth for employees/cards and attendance.
- **PostgreSQL:** persistent storage.
- **In-memory event store:** transient Android notifications only.
- **USB reader:** transmits UID to backend.
- **Android app:** polls backend, shows employee, and speaks welcome.

## 4. Backend

### Entry point

- FastAPI app: `backend/app/main.py`
- Module: `app.main:app`
- Run from project root with `--app-dir backend`, because `app` is inside `backend/`.

Startup performs:

1. Read `backend/schema.sql`.
2. Create tables with `CREATE TABLE IF NOT EXISTS`.
3. Connect to PostgreSQL.
4. Set the PostgreSQL session timezone to `Asia/Kolkata`.
5. Seed/upsert employees and cards.
6. Import any matching seed photos into PostgreSQL.

### Database configuration

Default:

```text
postgresql://postgres:postgres@localhost:5432/nfc_attendance
```

Environment variable:

```text
DATABASE_URL
```

The `nfc_attendance` database must exist before FastAPI starts. A `.env` file is not used by the current implementation.

### Tables

#### `employees`

- `id`: SERIAL primary key
- `emp_code`: VARCHAR(20), unique, required
- `full_name`: VARCHAR(100), required
- `department`: VARCHAR(50), optional
- `is_active`: BOOLEAN, default true

#### `nfc_cards`

- `id`: SERIAL primary key
- `card_uid`: VARCHAR(32), unique, required
- `employee_id`: foreign key to `employees(id)`
- `is_active`: BOOLEAN, default true

#### `attendance_logs`

- `id`: BIGSERIAL primary key
- `employee_id`: foreign key to `employees(id)`
- `direction`: `IN` or `OUT`, constrained by SQL
- `tapped_at`: timestamptz, default `now()`
- Index: employee plus tapped timestamp descending

#### `employee_photos`

- `employee_id`: primary key and employee foreign key, cascade delete
- `photo`: BYTEA
- `mime_type`: default `image/jpeg`
- `updated_at`: timestamptz

Schema is in `backend/schema.sql`.

### Seed employees/cards

Seed data is in `backend/app/employees.py`:

| Employee ID/code | Name | UID | Department |
|---|---|---|---|
| 0011558829 | Aditya | 0011558829 | Seed database mapping |
| 0005328154 | Shubham | 0005328154 | Seed database mapping |
| 0011482126 | Gaurav | 0011482126 | Seed database mapping |

Treat the employee mapping as seed data only. Runtime employee/card lookups come from PostgreSQL.

Startup upsert behavior:

- Existing employee code: updates name/reactivates employee.
- Existing card UID: updates employee assignment/reactivates card.
- Existing matching seed photo: replaces the stored photo.

### Seed photos

Photo source directory: `backend/seed_photos/`

Expected current/demo photos:

- `0011558829.png`
- `0005328154.jpg`
- `0011482126.jpg`

Photos are:

- Accepted as JPG/JPEG/PNG.
- EXIF-normalized.
- Converted to RGB.
- Center-cropped and resized to exactly 400×400.
- Compressed as JPEG at quality 85.
- Stored in PostgreSQL as `BYTEA`.
- Served with MIME type `image/jpeg`.

## 5. Backend API

Routers are included in `backend/app/main.py`.

All `/api/v1` routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Service health |
| POST | `/api/v1/employee/identify` | Look up employee without recording attendance |
| POST | `/api/v1/scan` | Normal USB-reader scan ingestion |
| GET | `/api/v1/events?after_id=N` | Poll Android scan events |
| POST | `/api/v1/tap/{card_uid}` | Direct kiosk attendance tap |
| GET | `/api/v1/photo/{employee_id}` | Retrieve photo |
| POST | `/api/v1/employees/{employee_id}/photo` | Upload/replace photo |
| POST | `/api/v1/cards` | Register/activate card |

Duplicate unprefixed aliases are also available:

- `/tap/{card_uid}`
- `/photo/{employee_id}`
- `/employees/{employee_id}/photo`
- `/cards`

### Health

`GET /api/v1/health`

Returns service status, version, and UTC timestamp.

### Employee identify

`POST /api/v1/employee/identify`

Request:

```json
{
  "nfc_uid": "04A1B2C3D4"
}
```

UID processing:

- Trims whitespace.
- Removes `:` and `-`.
- Converts to uppercase.
- Requires 1–64 characters.
- Requires hexadecimal characters.
- Invalid UID produces HTTP 422.

Response:

- `success`
- `message`
- `employee_id`, optional
- `employee_name`, optional
- `photo_url`, optional

Unknown card returns HTTP 200 with `success=false`. It does not record an attendance row.

### Scan

`POST /api/v1/scan`

This is the main USB-reader endpoint.

Behavior:

1. Normalize card UID.
2. Find an active card and active employee.
3. Serialize direction updates with `SELECT FOR UPDATE OF e`.
4. Read the latest attendance row.
5. If the latest tap is less than 30 seconds old:
   - suppress as duplicate
   - do not create a new attendance row
   - do not create an Android event
6. Otherwise alternate direction:
   - first tap: `IN`
   - then `OUT`
   - then `IN`, and so on.

Unknown card returns HTTP 200 with `success=false`.

Valid successful/identified scans create an in-memory event. Duplicates and unknown cards do not create Android events.

### Direct tap/kiosk route

`POST /tap/{card_uid}` or `POST /api/v1/tap/{card_uid}`

This route records or duplicates attendance and returns:

- internal employee ID
- employee code
- employee name
- department
- direction
- greeting
- photo URL
- duplicate flag

Greeting uses IST (`Asia/Kolkata`):

- IN: Good morning/afternoon/evening based on time
- OUT: `Thank you, <name>!`

Unknown UID returns HTTP 404.

### Card registration

`POST /cards` or `POST /api/v1/cards`

Request:

```json
{
  "card_uid": "04A1B2C3D4",
  "employee_id": 1
}
```

Card UID is normalized as uppercase hex and the row is deactivated/reactivated as needed.

### Photos

- `GET /photo/{employee_id}` serves stored JPEG bytes.
- `POST /employees/{employee_id}/photo` accepts multipart upload `file` and replaces the photo.
- `POST /api/v1/employees/{employee_id}/photo` is the prefixed alias.
- Successful upload is HTTP 204.

## 6. In-memory event store

Implementation: `backend/app/events.py`

- Events exist only in backend process memory.
- Maximum 200 events are retained.
- Event IDs restart from 1 after backend restart.
- The backend has a random process/server ID.
- Poll endpoint can return at most 50 events.

Event shape:

- `id`
- `timestamp`
- `nfc_uid`
- `success`
- `message`
- `employee_id`, optional
- `employee_name`, optional
- `photo_url`, optional

Without `after_id`, `GET /api/v1/events` returns `latest_id` but no event history.

## 7. USB reader

### PC/SC reader: `usb_reader/usb_reader.py`

Assumptions:

- Windows
- PC/SC-compatible NFC reader
- `pyscard` is installed
- First reader returned by `smartcard.System.readers()` is used
- Reader supports APDU `FF CA 00 00 00`
- Reader returns status `90 00`

Behavior:

- Poll interval: 0.3 seconds.
- Posts to `http://localhost:8000/api/v1/scan`.
- Debounces the same UID for 5 seconds in the script.
- Prints UID and backend response.
- Optional laptop TTS controlled by `SPEAK_ON_LAPTOP = True/False`.

The 5-second script debounce prevents duplicate submissions, but the backend independently suppresses duplicates within 30 seconds.

Hardware compatibility varies. A reader or card may not support the standard UID APDU, and random/private UIDs cannot be matched reliably.

### Keyboard/keyboard-wedge reader: `usb_reader/keyboard_reader.py`

Assumptions:

- Reader acts as a HID keyboard and types UID followed by Enter.
- Terminal must have focus.
- `pyscard` is not required for this script.
- Posts to `http://localhost:8000/api/v1/scan`.
- Debounces repeated UID input for 5 seconds.

`keyboard_reader.py` has a hard-coded API base URL and is the current editor file. It removes whitespace/colons and sends text to FastAPI. Hyphens may be normalized by backend Pydantic validation.

## 8. Android app

### Main activity

Implementation: `MainActivity.java`

- One exported `MainActivity`.
- App is in Java.
- Minimum SDK: 26.
- Target/compile SDK: 34.
- The app is a vertical scroll-based kiosk UI.
- It does not use Android NFC APIs in the active implementation.

### Polling lifecycle

- Polling begins in `onResume()`.
- Polling stops in `onPause()`.
- Normal interval: 1 second.
- Network failure/retry interval: 3 seconds.
- On resume, the app resets `server_id`, `last_event_id`, and polls from the beginning.
- The first successful poll records `latest_id` but does not replay old events.
- If backend `server_id` changes, Android resynchronizes.
- The app announces the newest identified event in a batch of up to 50.
- Events arriving while the app is paused are not replayed after resume.

### Server status

- Green: server connected.
- Red: server unavailable or backend polling failed.
- HTTP/UI reset behavior: transient scan status resets after roughly 6 seconds.

### UI

Layout: `activity_main.xml`

Includes:

- App title
- server connection pill
- NFC icon/status area
- ready or connection heading
- current scan status/detail pill
- TTS warning area
- employee photo
- employee name/code/UID/department
- last successful scan card
- Test Mode card

### Test Mode

Test Mode uses no USB reader and does not record attendance.

- Switch reveals manual UID input.
- Default UID: `04A1B2C3D4`.
- Calls `POST /api/v1/employee/identify`.
- Displays `(manual test)` in the UID/status area.
- Speaks `Welcome, <name>` for a successful test lookup.
- Unknown test card shows `Unregistered Card` and produces no welcome TTS.

### TTS

Implementation: `TtsManager.java`

- Uses Android `TextToSpeech`.
- Requires an available English locale/voice.
- Speech queue mode: `QUEUE_FLUSH`.
- Each utterance has a unique ID.
- Stops TTS on pause and shuts down TTS on activity destroy.
- UI warns if TTS engine initialization fails or English voice data is unavailable.

### Networking

Networking uses Retrofit, OkHttp, and Gson.

- Retrofit base URL: `BuildConfig.BASE_URL`
- Call timeout: 15 seconds
- Connect timeout: 8 seconds
- Read/write timeout: 10 seconds
- Debug builds enable full HTTP body logging.
- Release builds disable HTTP logging.

Android API methods:

- `POST api/v1/employee/identify`
- `GET api/v1/events`
- Dynamic photo request via `@Url`

### Android base URL

Defined in `android/app/build.gradle`:

```gradle
debug {
    buildConfigField "String", "BASE_URL", "\"http://YOUR_LAPTOP_IP:8000/\""
}

release {
    buildConfigField "String", "BASE_URL", "\"http://YOUR_LAPTOP_IP:8000/\""
}
```

Before phone testing, replace the placeholder with the laptop LAN IP, for example:

```text
http://192.168.1.25:8000/
```

The base URL must end in `/` and must not use `localhost` on the phone. Phone and laptop must share the same Wi-Fi network.

### Android manifest

- Internet permission
- Network state permission
- Cleartext HTTP enabled for local development
- `MainActivity` exported, `singleTop`
- No NFC feature declarations
- No NFC reader mode or NFC intent filters

## 9. Build and dependencies

### Backend dependencies

`backend/requirements.txt`:

- fastapi >= 0.115.0
- uvicorn[standard] >= 0.30.0
- psycopg2-binary >= 2.9.9
- Pillow >= 10.4.0
- python-multipart >= 0.0.9
- tzdata >= 2024.1

No migration framework is included. Schema changes must be manually/algebraically managed by editing `schema.sql` or future migration tooling.

### USB dependencies

`usb_reader/requirements.txt`:

- pyscard >= 2.0.7
- requests >= 2.31.0
- pyttsx3 >= 2.90

### Android dependencies

- AppCompat 1.7.0
- Material 1.12.0
- Retrofit 2.11.0
- Gson converter 2.11.0
- OkHttp 4.12.0
- OkHttp logging interceptor 4.12.0
- Gson 2.10.1
- Android Gradle Plugin 8.5.2
- Gradle wrapper 8.7
- Java 1.8 source/target compatibility

## 10. Setup and run

### Backend setup

From project root:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nfc_attendance
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Recommended Windows launcher:

```powershell
.\run_backend.ps1
```

The launcher uses:

```text
backend\.venv\Scripts\python.exe
```

and runs uvicorn with `--app-dir backend`.

The PostgreSQL `nfc_attendance` database must already exist.

### USB reader

```powershell
cd usb_reader
pip install -r requirements.txt
python usb_reader.py
```

If using keyboard-wedge reader:

```powershell
python keyboard_reader.py
```

Keep the terminal active as the keyboard reader requires it to receive its input.

### Android app

1. Open the `android/` folder in Android Studio.
2. Update `android/app/build.gradle` with the laptop LAN IP.
3. Sync Gradle.
4. Start backend.
5. Start USB/keyboard reader.
6. Run app on a phone connected to the same Wi-Fi.

Useful URLs:

- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`
- Phone health check: `http://<laptop-ip>:8000/api/v1/health`

## 11. Current known behavior and limitations

1. Android is a polling kiosk, not an NFC tag reader.
2. Backend events are in memory and lost on restart.
3. Event IDs restart after backend restart; Android uses `server_id` to resynchronize.
4. Backend duplicate window is 30 seconds.
5. USB reader has an additional 5-second debounce.
6. A held card can repeatedly appear to the USB script and delay debouncing depending on loop behavior.
7. A 30-second duplicate `/scan` creates no Android event.
8. `Identify` and Test Mode do not record attendance.
9. Unknown card `/identify` is HTTP 200 with `success=false`, not HTTP 404.
10. Invalid UID returns HTTP 422.
11. `/tap/{uid}` unknown card returns HTTP 404.
12. HTTPS is not used; cleartext HTTP is development-only.
13. Phone and laptop firewall/router must allow local HTTP 8000 traffic.
14. Randomized NFC UIDs cannot be matched unless the database is updated to map the changing UID or card identity is changed.
15. Seed photos are optional and missing photos simply remain absent.
16. No authentication/authorization exists.
17. No attendance history/admin UI is implemented in Android.
18. No formal migrations are included.
19. Card directions alternate solely by latest database attendance row, not by a separate employee presence field.

## 12. Current workspace/run observations

The following commands/statuses were observed in the active workspace:

- Backend terminal command: `.
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload`
- That backend terminal returned exit code 1; inspect the actual terminal output and environment before restarting.
- One USB terminal previously tried `python usb_reader0005328154.py`, which appears to be a UID-based filename rather than an existing project script.
- Actual scripts are `usb_reader/usb_reader.py` and `usb_reader/keyboard_reader.py`.
- The current editor file is `usb_reader/keyboard_reader.py`.

## 13. Suggested continuation workflow for ChatGPT

When changing the project, preserve these rules unless the user explicitly requests redesign:

1. Use FastAPI as the backend source of truth.
2. Use PostgreSQL for employees/cards/photos/attendance.
3. Keep `/api/v1/scan` compatible with the USB reader if changing request models.
4. Keep `/api/v1/events` compatible with Android polling if changing event delivery.
5. Respect the active-card and active-employee checks.
6. Preserve 30-second duplicate attendance suppression unless redesigning it.
7. Add NFC directly to Android only if explicitly requested; do not assume Android currently reads cards.
8. For LAN testing, use the laptop LAN IP and cleartext HTTP unless TLS is intentionally added.
9. Update `schema.sql`, startup seed logic, Pydantic models, routers, Android models, and reader scripts together when changing data contracts.
10. Test unknown UID, invalid UID, duplicate tap, 400/404/422/500 HTTP behavior, photo upload/display, backend restart, and Android polling restart.

## 14. First files to inspect for future requests

- Backend startup and routes: `backend/app/main.py`
- Database and attendance logic: `backend/app/database.py`
- Seed/upsert/data: `backend/app/employees.py`, `backend/app/seed.py`
- API schemas: `backend/app/schemas.py`
- Events: `backend/app/events.py`
- Scan endpoint: `backend/app/router/scan.py`
- Direct tap/photos/cards: `backend/app/router/kiosk.py`
- USB reader: `usb_reader/usb_reader.py`
- Keyboard reader: `usb_reader/keyboard_reader.py`
- Android UI/activity: `android/app/src/main/java/com/example/nfcemployeewelcome/MainActivity.java`
- Android HTTP models/client: `android/app/src/main/java/com/example/nfcemployeewelcome/network/`
- TTS: `android/app/src/main/java/com/example/nfcemployeewelcome/tts/TtsManager.java`
- Android layout: `android/app/src/main/res/layout/activity_main.xml`
- Android configuration: `android/app/build.gradle`
