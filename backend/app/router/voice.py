"""Voice command parsing endpoints."""
import re

from fastapi import APIRouter

from app.schemas import VoiceCommandRequest, VoiceCommandResponse

router = APIRouter(tags=["Voice"])


@router.post("/voice-command", response_model=VoiceCommandResponse, summary="Parse a spoken light command")
def process_voice_command(payload: VoiceCommandRequest) -> VoiceCommandResponse:
    text = payload.text.strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    words = set(normalized.split())

    has_light = "light" in words or "lights" in words
    has_on = "on" in words or "enable" in words
    has_off = "off" in words or "disable" in words

    if not has_light:
        return VoiceCommandResponse
    se(
            success=False,
            action="unknown",
            spoken_text=text,
            message="Please include light in your command.",
        )

    if has_off:
        return VoiceCommandResponse(
            success=True,
            action="off",
            spoken_text=text,
            message="The light has been turned off",
        )

    if has_on:
        return VoiceCommandResponse(
            success=True,
            action="on",
            spoken_text=text,
            message="The light has been turned on",
        )

    return VoiceCommandResponse(
        success=False,
        action="unknown",
        spoken_text=text,
        message="Please say turn on the light or turn off the light.",
    )
