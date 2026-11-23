"""Idempotently seed the employees from the original prototype mapping."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from app.database import get_connection
from app.employees import EMPLOYEES

PHOTO_DIR = Path(__file__).resolve().parents[1] / "seed_photos"


def _read_photo(employee_code: str):
    for extension in (".jpg", ".jpeg", ".png"):
        path = PHOTO_DIR / f"{employee_code}{extension}"
        if path.exists():
            image = Image.open(path)
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, (400, 400), method=Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
            return output.getvalue()
    return None
from app.employees import EMPLOYEES


def seed_employees() -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        for employee in EMPLOYEES.values():
            cursor.execute(
                """
                INSERT INTO employees (emp_code, full_name)
                VALUES (%s, %s)
                ON CONFLICT (emp_code) DO UPDATE
                SET full_name = EXCLUDED.full_name, is_active = TRUE
                RETURNING id
                """,
                (employee["employee_id"], employee["employee_name"]),
            )
            employee_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO nfc_cards (card_uid, employee_id)
                VALUES (%s, %s)
                ON CONFLICT (card_uid) DO UPDATE
                SET employee_id = EXCLUDED.employee_id, is_active = TRUE
                """,
                (employee["employee_id"].strip().upper(), employee_id),
            )
            photo = _read_photo(employee["employee_id"])
            if photo is not None:
                cursor.execute(
                    """
                    INSERT INTO employee_photos (employee_id, photo, mime_type)
                    VALUES (%s, %s, 'image/jpeg')
                    ON CONFLICT (employee_id) DO UPDATE
                    SET photo = EXCLUDED.photo, mime_type = EXCLUDED.mime_type,
                        updated_at = now()
                    """,
                    (employee_id, photo),
                )