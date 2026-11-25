"""Voice command parsing and MQTT light control endpoints."""
import json
import logging
import os
import re

from fastapi import APIRouter
import paho.mqtt.client as mqtt

from app.schemas import VoiceCommandRequest, VoiceCommandResponse

router = APIRouter(tags=["Voice"])
logger = logging.getLogger(__name__)


def _mqtt_settings() -> dict:
    """MQTT connection settings, read from the backend environment (backend/.env) at call time.
    Username and password have NO default: if they are missing, the light command fails safely."""
    username = os.getenv("MQTT_USERNAME", "").strip()
    password = os.getenv("MQTT_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("MQTT_USERNAME and MQTT_PASSWORD are not set in the backend environment")
    return {
        "host": os.getenv("MQTT_HOST", "10.1.1.177"),
        "port": int(os.getenv("MQTT_PORT", "1883")),
        "username": username,
        "password": password,
        "topic": os.getenv("MQTT_TOPIC", "relayCtr"),
        "device_name": os.getenv("MQTT_DEVICE_NAME", "2c:bc:bb:0d:07:20"),
    }


def publish_light_state(state: str) -> None:
    settings = _mqtt_settings()
    payload = json.dumps({"NM": settings["device_name"], "state": state}, separators=(",", ":"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(settings["username"], settings["password"])
    client.connect(settings["host"], settings["port"], keepalive=10)
    try:
        result = client.publish(settings["topic"], payload)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with result code {result.rc}")
    finally:
        client.disconnect()


# @router.post("/voice-command", response_model=VoiceCommandResponse, summary="Parse a spoken light command")
# def process_voice_command(payload: VoiceCommandRequest) -> VoiceCommandResponse:
#     text = payload.text.strip()
#     normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
#     words = set(normalized.split())

#     has_light = "light" in words or "lights" in words
#     has_on = "on" in words or "enable" in words
#     has_off = "off" in words or "disable" in words

#     if not has_light:
#         return VoiceCommandResponse(
#             success=False,
#             action="unknown",
#             spoken_text=text,
#             message="Please include light in your command.",
#         )

#     if has_off:
#         state = "0"
#         message = "The light has been turned off"
#     elif has_on:
#         state = "1"
#         message = "The light has been turned on"
#     else:
#         return VoiceCommandResponse(
#             success=False,
#             action="unknown",
#             spoken_text=text,
#             message="Please say turn on the light or turn off the light.",
#         )

#     try:
#         publish_light_state(state)
#     except Exception:
#         logger.exception("Could not publish light state to MQTT")
#         return VoiceCommandResponse(
#             success=False,
#             action="unknown",
#             spoken_text=text,
#             message="Could not send the light command.",
#         )

#     return VoiceCommandResponse(
#         success=True,
#         action="on" if state == "1" else "off",
#         spoken_text=text,
#         message=message,
#     )

@router.post(
    "/voice-command",
    response_model=VoiceCommandResponse,
    summary="Process voice command or identify normal conversation"
)
async def process_voice_command(
    payload: VoiceCommandRequest
) -> VoiceCommandResponse:

    text = payload.text.strip()

    if not text:
        return VoiceCommandResponse(
            success=False,
            action="unknown",
            spoken_text=payload.text,
            message="No voice input received."
        )

    normalized = text.lower()
    words = set(normalized.split())

    has_light = bool({"light", "lights"} & words)
    has_on = bool({"on", "enable"} & words)
    has_off = bool({"off", "disable"} & words)

    # Both ON and OFF detected: ambiguous command
    if has_light and has_on and has_off:
        return VoiceCommandResponse(
            success=False,
            action="unknown",
            spoken_text=text,
            message="Please give a clear light ON or OFF command."
        )

    # Explicit light ON command
    if has_light and has_on:
        try:
            publish_light_state("1")

            return VoiceCommandResponse(
                success=True,
                action="on",
                spoken_text=text,
                message="Light turned ON."
            )

        except Exception:
            logger.exception("Failed to publish light ON command")

            return VoiceCommandResponse(
                success=False,
                action="on",
                spoken_text=text,
                message="Unable to turn ON the light."
            )

    # Explicit light OFF command
    if has_light and has_off:
        try:
            publish_light_state("0")

            return VoiceCommandResponse(
                success=True,
                action="off",
                spoken_text=text,
                message="Light turned OFF."
            )

        except Exception:
            logger.exception("Failed to publish light OFF command")

            return VoiceCommandResponse(
                success=False,
                action="off",
                spoken_text=text,
                message="Unable to turn OFF the light."
            )

    # Everything else goes to normal conversation
    return VoiceCommandResponse(
        success=True,
        action="chat",
        spoken_text=text,
        message="Voice input received."
    )
