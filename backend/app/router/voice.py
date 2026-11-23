"""Voice command parsing and MQTT light control endpoints."""
import json
import logging
import re

from fastapi import APIRouter
import paho.mqtt.client as mqtt

from app.schemas import VoiceCommandRequest, VoiceCommandResponse

router = APIRouter(tags=["Voice"])
logger = logging.getLogger(__name__)

MQTT_HOST = "10.1.1.177"
MQTT_PORT = 1883
MQTT_USERNAME = "mqtt_user_iiot"
MQTT_PASSWORD = "Neilsoft@1"
MQTT_TOPIC = "relayCtr"
MQTT_DEVICE_NAME = "2c:bc:bb:0d:07:20"


def publish_light_state(state: str) -> None:
    payload = json.dumps({"NM": MQTT_DEVICE_NAME, "state": state}, separators=(",", ":"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
    try:
        result = client.publish(MQTT_TOPIC, payload)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with result code {result.rc}")
    finally:
        client.disconnect()


@router.post("/voice-command", response_model=VoiceCommandResponse, summary="Parse a spoken light command")
def process_voice_command(payload: VoiceCommandRequest) -> VoiceCommandResponse:
    text = payload.text.strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    words = set(normalized.split())

    has_light = "light" in words or "lights" in words
    has_on = "on" in words or "enable" in words
    has_off = "off" in words or "disable" in words

    if not has_light:
        return VoiceCommandResponse(
            success=False,
            action="unknown",
            spoken_text=text,
            message="Please include light in your command.",
        )

    if has_off:
        state = "0"
        message = "The light has been turned off"
    elif has_on:
        state = "1"
        message = "The light has been turned on"
    else:
        return VoiceCommandResponse(
            success=False,
            action="unknown",
            spoken_text=text,
            message="Please say turn on the light or turn off the light.",
        )

    try:
        publish_light_state(state)
    except Exception:
        logger.exception("Could not publish light state to MQTT")
        return VoiceCommandResponse(
            success=False,
            action="unknown",
            spoken_text=text,
            message="Could not send the light command.",
        )

    return VoiceCommandResponse(
        success=True,
        action="on" if state == "1" else "off",
        spoken_text=text,
        message=message,
    )
