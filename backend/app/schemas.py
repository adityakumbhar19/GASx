"""Pydantic request/response models. Android's Retrofit models mirror these exactly."""
import re
from typing import List, Optional

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