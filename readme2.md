# NFC Employee Welcome and Light Voice Commands

A Windows/Android kiosk prototype that combines employee NFC attendance with a spoken light-command control demonstration.

## Project Features

- NFC card scan ingestion through a USB/keyboard card reader
- Employee lookup and attendance storage in PostgreSQL
- FastAPI API for kiosk, scan, and employee operations
- Android polling client for scan notifications
- Android Text-to-Speech employee welcomes
- Android speech recognition for light commands
- FastAPI parsing of the transcribed text
- On-screen and spoken responses for valid light commands

## Architecture

```text
USB/keyboard NFC reader
        |
        | POST /api/v1/scan
        v
FastAPI + PostgreSQL
        |
        | GET /api/v1/events every 1 second
        v
Android app -> employee UI -> Android TTS

Android microphone
        |
        | Android speech recognition converts voice to text
        v
POST /api/v1/voice-command
        |
        v
FastAPI parses light/on/off words
        |
        v
Android displays and speaks the response
```

```text
nfc-employee-welcome/
├── backend/                 FastAPI and PostgreSQL integration
├── android/                 Android Studio Java project
├── usb_reader/              USB HID and keyboard reader scripts
├── Handover.md              Detailed project handover
├── run_backend.ps1          Windows backend startup script
└── README.md
```

## 1. Backend Setup

Create the PostgreSQL database:

```sql
CREATE DATABASE nfc_attendance;
```

The default database URL is:

```text
postgresql://postgres:postgres@localhost:5432/nfc_attendance
```

It can be overridden with:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/nfc_attendance"
```

Install dependencies and start from the project root:

```powershell
cd C:\Users\S168\Downloads\nfc-employee-welcome_new
.\run_backend.ps1
```

You can also start it manually:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Startup creates the tables from `backend/schema.sql` and seeds employee/card data from `backend/app/employees.py`.

Useful URLs:

- Swagger UI: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/v1/health>

## 2. Voice-Light API

Endpoint:

```text
POST /api/v1/voice-command
```

Request:

```json
{
  "text": "Turn on the light"
}
```

Turn-on response:

```json
{
  "success": true,
  "action": "on",
  "spoken_text": "Turn on the light",
  "message": "The light has been turned on"
}
```

Turn-off response:

```json
{
  "success": true,
  "action": "off",
  "spoken_text": "Turn off the light",
  "message": "The light has been turned off"
}
```

The FastAPI router normalizes the text to lowercase words and checks for:

- `light` or `lights`
- `on` or `enable`
- `off` or `disable`

This endpoint is a command parser only. It does not control a physical light or smart-home device.

The equivalent unprefixed endpoint `/voice-command` is also registered.

## Voice Recognition Flow

1. Tap **Speak light command** in the Android app.
2. Android asks for microphone permission when required.
3. Android speech recognition converts the spoken phrase to text.
4. The app sends the text to FastAPI.
5. FastAPI determines `on`, `off`, or an invalid/unknown command.
6. The app displays the result.
7. Android Text-to-Speech speaks the returned message.

Android performs speech-to-text. FastAPI does not receive audio and does not perform speech recognition itself.

```mermaid
flowchart TD
    A[Tap Speak light command] --> B[Request microphone permission]
    B --> C[Android speech recognition]
    C --> D[Convert speech to text]
    D --> E[POST /api/v1/voice-command]
    E --> F{Contains light?}
    F -->|No| G[Return light-required instruction]
    F -->|Yes| H{Contains on or off?}
    H -->|On/enable| I[The light has been turned on]
    H -->|Off/disable| J[The light has been turned off]
    H -->|Neither| K[Ask for turn on or turn off]
    I --> L[Android displays and speaks response]
    J --> L
    G --> L
    K --> L
```

## 3. USB NFC Reader

Install and run the reader:

```powershell
cd usb_reader
pip install -r requirements.txt
python usb_reader.py
```

The script reads a card UID and calls:

```text
POST /api/v1/scan
```

Successful or identified scans create an in-memory event for the Android app. Duplicate taps within 30 seconds are suppressed.

A valid scan alternates employee attendance direction:

- First tap: `IN`
- Next tap: `OUT`
- Following taps continue alternating

## 4. Android Setup

Open the `android/` directory in Android Studio, not the repository root.

Find the laptop IPv4 address:

```powershell
ipconfig
```

Use the Wi-Fi adapter address, for example `192.168.1.25`, in:

```text
android/app/build.gradle
```

Set:

```gradle
def backendBaseUrl = "http://192.168.1.25:8000/"
```

Do not use `localhost` or `127.0.0.1`, because an Android phone/tablet cannot use those addresses to reach the laptop.

Requirements:

- Android minimum SDK: 26
- Android phone or tablet with microphone access
- Tablet and laptop on the same Wi-Fi network
- FastAPI running on TCP port `8000`
- Android internet, network state, and record-audio permissions
- Google speech recognition availability on the tablet

Start the app through Android Studio. Open the `android/` folder, let Gradle synchronize, select the tablet, and press **Run**.

There is no Gradle wrapper in the Android project directory, so Android Studio will download or use the configured Gradle version and Android SDK needed for the build.

## Running with a Tablet

1. Start PostgreSQL.
2. Start FastAPI with `run_backend.ps1`.
3. Set the laptop IP in `android/app/build.gradle`.
4. Allow TCP port `8000` through Windows Firewall.
5. Connect the tablet to the same Wi-Fi network.
6. Open the tablet browser and test:

```text
http://<laptop-ip>:8000/api/v1/health
```

7. Open the `android/` project in Android Studio.
8. Connect the tablet over USB and enable Developer Options and USB debugging.
9. Select the tablet and run the app.
10. Allow microphone permission.
11. Tap **Speak light command** and say `turn on the light` or `turn off the light`.

Allow FastAPI through the Windows firewall if needed:

```powershell
New-NetFirewallRule -DisplayName "FastAPI Port 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

## Testing the Voice Endpoint

Open Swagger at <http://localhost:8000/docs> and execute `POST /api/v1/voice-command` with:

```json
{
  "text": "Turn on the light"
}
```

Test another command:

```json
{
  "text": "Turn off the light"
}
```

## NFC Test Mode

The Android app retains manual NFC test mode.

1. Enable manual test mode.
2. Enter an NFC UID.
3. Tap **Test UID**.
4. The app calls `POST /api/v1/employee/identify`.

Test UIDs include the seeded employee values:

```text
04A1B2C3D4
0011558829
0005328154
0011482126
```

## Existing API Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Backend health |
| POST | `/api/v1/employee/identify` | Identify a card UID without recording attendance |
| POST | `/api/v1/scan` | USB-reader scan ingestion |
| GET | `/api/v1/events?after_id=N` | Android scan-event polling |
| POST | `/api/v1/voice-command` | Parse speech-recognized text for light commands |
| POST | `/api/v1/tap/{card_uid}` | Direct kiosk attendance tap |
| GET | `/api/v1/photo/{employee_id}` | Retrieve employee photo |
| POST | `/api/v1/employees/{employee_id}/photo` | Upload/replace employee photo |
| POST | `/api/v1/cards` | Register or activate an NFC card |

The kiosk photo/card routes are also available without `/api/v1`:

- `/tap/{card_uid}`
- `/photo/{employee_id}`
- `/employees/{employee_id}/photo`
- `/cards`

## Notes

- Unknown NFC cards return `success: false` and do not create an Android welcome event.
- Invalid card UIDs return HTTP 422.
- Duplicate NFC taps are ignored within the debounce period.
- Employee photos are resized to 400×400 JPEG images and stored in PostgreSQL.
- Plain HTTP is enabled only for local development.
- The speech recognizer depends on Android/Google services and may need internet access.
- Current light commands produce text responses only; no GPIO or physical relay is connected.

command to check the mqtt connected
.\.venv\Scripts\python.exe -c "import paho.mqtt.client as mqtt; c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); c.username_pw_set('mqtt_user_iiot','Neilsoft@1'); c.connect('10.1.1.177',1883,10); print('MQTT_CONNECTED'); c.disconnect()"