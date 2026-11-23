
"""PostgreSQL access for employees, cards, attendance, and photos."""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/nfc_attendance",
)
IST = ZoneInfo("Asia/Kolkata")


def get_connection():
    connection = psycopg2.connect(DATABASE_URL)
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'Asia/Kolkata'")
    return connection


def init_db() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schema.sql"
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(schema_path.read_text(encoding="utf-8"))


def find_employee(card_uid: str) -> Optional[Dict]:
    with get_connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT e.id, e.emp_code AS employee_id, e.full_name AS employee_name,
                   e.department, c.card_uid
            FROM nfc_cards c
            JOIN employees e ON e.id = c.employee_id
            WHERE c.card_uid = %s AND c.is_active AND e.is_active
            """,
            (card_uid.strip().upper(),),
        )
        return cursor.fetchone()


def register_card(card_uid: str, employee_id: int) -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO nfc_cards (card_uid, employee_id)
            VALUES (%s, %s)
            ON CONFLICT (card_uid) DO UPDATE
            SET employee_id = EXCLUDED.employee_id, is_active = TRUE
            """,
            (card_uid.strip().upper(), employee_id),
        )


def record_tap(card_uid: str) -> Optional[Dict]:
    """Resolve a card and record the next IN/OUT event atomically."""
    with get_connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT e.id, e.emp_code AS employee_id, e.full_name AS employee_name,
                   e.department, c.card_uid
            FROM nfc_cards c
            JOIN employees e ON e.id = c.employee_id
            WHERE c.card_uid = %s AND c.is_active AND e.is_active
            FOR UPDATE OF e
            """,
            (card_uid.strip().upper(),),
        )
        employee = cursor.fetchone()
        if employee is None:
            return None

        cursor.execute(
            """
            SELECT direction, tapped_at
            FROM attendance_logs
            WHERE employee_id = %s
            ORDER BY tapped_at DESC
            LIMIT 1
            """,
            (employee["id"],),
        )
        previous = cursor.fetchone()
        if previous and (datetime.now(IST) - previous["tapped_at"]).total_seconds() < 30:
            employee.update(direction=previous["direction"], tapped_at=previous["tapped_at"], duplicate=True)
            return employee

        direction = "OUT" if previous and previous["direction"] == "IN" else "IN"
        cursor.execute(
            """
            INSERT INTO attendance_logs (employee_id, direction)
            VALUES (%s, %s)
            RETURNING tapped_at
            """,
            (employee["id"], direction),
        )
        employee.update(direction=direction, tapped_at=cursor.fetchone()["tapped_at"], duplicate=False)
        return employee


def get_photo(employee_id: int):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT photo, mime_type FROM employee_photos WHERE employee_id = %s",
            (employee_id,),
        )
        return cursor.fetchone()


def save_photo(employee_id: int, photo: bytes, mime_type: str = "image/jpeg") -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO employee_photos (employee_id, photo, mime_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (employee_id) DO UPDATE
            SET photo = EXCLUDED.photo, mime_type = EXCLUDED.mime_type,
                updated_at = now()
            """,
            (employee_id, psycopg2.Binary(photo), mime_type),
        )