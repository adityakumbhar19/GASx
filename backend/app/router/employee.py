"""Employee identification routes."""
import logging

from fastapi import APIRouter

from app.employees import find_employee
from app.schemas import IdentifyRequest, IdentifyResponse

logger = logging.getLogger("nfc-welcome.employee")

router = APIRouter(prefix="/employee", tags=["Employee"])


@router.post(
    "/identify",
    response_model=IdentifyResponse,
    summary="Identify an employee from an NFC card UID",
)
def identify_employee(payload: IdentifyRequest) -> IdentifyResponse:
    """
    Looks up the (already normalized, uppercase) UID.

    * Registered card   -> HTTP 200, success=true  + employee details
    * Unregistered card -> HTTP 200, success=false (a valid lookup outcome, not a server error)
    * Malformed request -> HTTP 422 (handled globally in main.py)
    * Unexpected error  -> HTTP 500 (handled globally in main.py)
    """
    employee = find_employee(payload.nfc_uid)

    if employee is None:
        logger.info("Unregistered NFC card: %s", payload.nfc_uid)
        return IdentifyResponse(
            success=False,
            message="Unregistered NFC card",
            employee_id=None,
            employee_name=None,
        )

    logger.info("Identified %s (%s) for UID %s", employee["employee_name"], employee["employee_id"], payload.nfc_uid)
    return IdentifyResponse(
        success=True,
        message="Employee identified successfully",
        employee_id=employee["employee_id"],
        employee_name=employee["employee_name"],
        photo_url=f"/photo/{employee['id']}",
    )
