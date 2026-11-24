"""Builds the system instruction sent to the LLM for every chat turn."""
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly voice assistant in an office, talking with an employee through a speaker. "
    "Everything you write is read aloud, so reply in one to three short sentences of plain spoken "
    "English. Never use markdown, bullet points, lists, emojis or web links. "
    "Be warm and natural. Use the employee's first name now and then, not in every reply. "
    "Remember the earlier messages of this conversation and resolve words like 'it', 'that', "
    "'again' and 'also' from that context. "
    "You know only the employee details listed below. Never invent facts about the employee or "
    "anyone else, and never share information about other employees. "
    "In this version you can only chat. You cannot control lights, air conditioning or any other "
    "device, and you cannot look up attendance or records. If asked to do something like that, say "
    "plainly that you cannot do it yet. Never say or imply that an action was carried out. "
    "If you do not know something, say so briefly."
)


def clean_text(value: Optional[str], limit: int = 60) -> str:
    """Single line, no control characters, length-limited. Employee fields come from the database
    but are placed inside the system prompt, so keep them from carrying instructions/newlines."""
    if not value:
        return ""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    return " ".join(text.split())[:limit]


def build_system_prompt(employee_name: str, department: Optional[str] = None,
                        now: Optional[datetime] = None) -> str:
    base = os.getenv("ASSISTANT_SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT
    tz_name = os.getenv("ASSISTANT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz, tz_name = ZoneInfo("UTC"), "UTC"
    now = now or datetime.now(tz)

    lines = [base, "", "Employee details (the only ones you know):", f"- Name: {clean_text(employee_name)}"]
    department = clean_text(department)
    if department:
        lines.append(f"- Department: {department}")
    lines.append(f"Current local date and time: {now.strftime('%A, %d %B %Y, %I:%M %p')} ({tz_name}).")
    return "\n".join(lines)
