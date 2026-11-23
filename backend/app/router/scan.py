"""Scan routes: the USB reader reports cards here; the Android app listens here."""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from app import database
from app import events as event_store
from app.schemas import EventsResponse, IdentifyRequest, IdentifyResponse

logger = logging.getLogger("nfc-welcome.scan")

router = APIRouter(tags=["Scan"])


@router.post("/scan", response_model=IdentifyResponse, summary="Report a card scan (used by the USB reader script)")
def register_scan(payload: IdentifyRequest) -> IdentifyResponse:
    """
    Looks the UID up in PostgreSQL, records the attendance direction, and
    records a compatible event for the Android app to pick up.
    """
    employee = database.record_tap(payload.nfc_uid)

    if employee is None:
        response = IdentifyResponse(success=False, message="Unregistered NFC card")
    else:
        response = IdentifyResponse(
            success=True,
            message="Employee identified successfully",
            employee_id=employee["employee_id"],
            employee_name=employee["employee_name"],
            photo_url=f"/photo/{employee['id']}",
        )

    if employee is not None and not employee["duplicate"]:
        event = event_store.add_event(
            nfc_uid=payload.nfc_uid,
            success=response.success,
            message=response.message,
            employee_id=response.employee_id,
            employee_name=response.employee_name,
            photo_url=response.photo_url,
        )
        logger.info("Scan event #%s uid=%s success=%s", event["id"], payload.nfc_uid, response.success)
    return response


@router.get("/events", response_model=EventsResponse, summary="Poll for new scan events (used by the Android app)")
def get_events(
    after_id: Optional[int] = Query(
        None, ge=0, description="Return events with id greater than this. Omit to just learn latest_id."
    ),
) -> EventsResponse:
    """
    First call: omit after_id -> events is empty, latest_id tells the client where to start
    (so old scans are never replayed). Later calls: pass the last id you have seen.
    """
    items = [] if after_id is None else event_store.events_after(after_id)
    return EventsResponse(server_id=event_store.SERVER_ID, latest_id=event_store.latest_id(), events=items)
