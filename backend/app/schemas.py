"""Pydantic request/response models. Android's Retrofit models mirror these exactly."""
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

_HEX_RE = re.compile(r"^[0-9A-F]+$")


class IdentifyRequest(BaseModel):
    nfc_uid: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="NFC card UID as hexadecimal text, e.g. 04A1B2C3D4",
        examples=["04A1B2C3D4"],
    )

    @field_validator("nfc_uid")
    @classmethod
    def normalize_uid(cls, value: str) -> str:
        cleaned = re.sub(r"[\s:\-]", "", value).upper()
        if not cleaned:
            raise ValueError("nfc_uid must not be empty")
        if not _HEX_RE.match(cleaned):
            raise ValueError("nfc_uid must contain only hexadecimal characters (0-9, A-F)")
        return cleaned


class IdentifyResponse(BaseModel):
    success: bool
    message: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    photo_url: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str


class ScanEvent(BaseModel):
    id: int
    timestamp: str
    nfc_uid: str
    success: bool
    message: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    photo_url: Optional[str] = None


class EventsResponse(BaseModel):
    server_id: str
    latest_id: int
    events: List[ScanEvent]


class CardCreate(BaseModel):
    card_uid: str = Field(..., min_length=1, max_length=32)
    employee_id: int = Field(..., gt=0)

    @field_validator("card_uid")
    @classmethod
    def normalize_card_uid(cls, value: str) -> str:
        cleaned = re.sub(r"[\s:\-]", "", value).upper()
        if not _HEX_RE.match(cleaned):
            raise ValueError("card_uid must contain only hexadecimal characters")
        return cleaned


class TapResponse(BaseModel):
    employee_id: int
    employee_code: str
    employee_name: str
    department: Optional[str] = None
    direction: str
    greeting: str
    photo_url: str
    duplicate: bool = False


class VoiceCommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


class VoiceCommandResponse(BaseModel):
    success: bool
    action: str
    spoken_text: str
    message: str


class AssistantSessionRequest(IdentifyRequest):
    """Create/resume an assistant session. Same NFC UID validation and normalization as IdentifyRequest."""


class AssistantSessionResponse(BaseModel):
    success: bool
    session_id: str
    employee_name: str
    message: str
    resumed: bool = False


class AssistantChatRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=256)
    message: str = Field(..., min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ToolCallInfo(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    success: bool


class AssistantChatResponse(BaseModel):
    success: bool
    session_id: str
    employee_name: str
    reply: str
    # Fields below were added for device control. Old clients that ignore unknown JSON fields keep working.
    # success is true whenever `reply` is valid; `action` says what actually happened.
    action: str = "chat"            # chat | device_control | device_control_failed
    device: Optional[str] = None    # "light" when a device tool ran
    state: Optional[str] = None     # "on" | "off" for light commands
    tool_calls: List[ToolCallInfo] = Field(default_factory=list)   # tools the assistant used this turn
