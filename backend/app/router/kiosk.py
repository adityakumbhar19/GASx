"""PostgreSQL-backed kiosk and administration endpoints."""
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps

from app import database
from app.schemas import CardCreate, TapResponse

router = APIRouter(tags=["Kiosk"])


def _greeting(employee_name: str, direction: str) -> str:
    from datetime import datetime

    if direction == "OUT":
        return f"Thank you, {employee_name}!"
    hour = datetime.now(database.IST).hour
    period = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {period}, {employee_name}!"


def _photo_bytes(upload: UploadFile) -> bytes:
    try:
        image = Image.open(upload.file)
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(image, (400, 400), method=Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Upload must be a valid image") from exc


@router.post("/tap/{card_uid}", response_model=TapResponse)
def tap(card_uid: str) -> TapResponse:
    result = database.record_tap(card_uid)
    if result is None:
        raise HTTPException(status_code=404, detail="Card not recognised")
    return TapResponse(
        employee_id=result["id"],
        employee_code=result["employee_id"],
        employee_name=result["employee_name"],
        department=result["department"],
        direction=result["direction"],
        greeting=_greeting(result["employee_name"], result["direction"]),
        photo_url=f"/photo/{result['id']}",
        duplicate=result["duplicate"],
    )


@router.get("/photo/{employee_id}")
def photo(employee_id: int) -> Response:
    result = database.get_photo(employee_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(
        content=bytes(result[0]),
        media_type=result[1],
        headers={"Cache-Control": "max-age=3600"},
    )


@router.post("/employees/{employee_id}/photo", status_code=204)
def upload_photo(employee_id: int, file: UploadFile = File(...)) -> Response:
    database.save_photo(employee_id, _photo_bytes(file), "image/jpeg")
    return Response(status_code=204)


@router.post("/cards", status_code=204)
def add_card(card: CardCreate) -> Response:
    database.register_card(card.card_uid, card.employee_id)
    return Response(status_code=204)