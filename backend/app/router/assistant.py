"""Assistant endpoints: employee-bound sessions and LLM chat (conversation only, no device control)."""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.employees import find_employee
from app.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantSessionRequest,
    AssistantSessionResponse,
)
from app.services import conversation_service
from app.services.conversation_service import SessionNotFoundError, get_session_store
from app.services.llm_service import LLMServiceError, get_llm_service

logger = logging.getLogger("nfc-welcome.assistant")

router = APIRouter(prefix="/assistant", tags=["Assistant"])


@router.post("/session", response_model=AssistantSessionResponse,
             summary="Create (or resume) the assistant session of the employee who owns this card")
async def create_session(payload: AssistantSessionRequest) -> AssistantSessionResponse:
    """
    The employee is resolved here from the NFC UID with the existing database lookup - nothing the
    client says about who the employee is is trusted. Unregistered cards get HTTP 404.

    There is ONE session per employee: tapping again resumes it with its full history.
    The lookup is read-only; attendance is recorded by /scan, not here.
    """
    try:
        employee = await run_in_threadpool(find_employee, payload.nfc_uid)
    except Exception:
        logger.exception("Employee lookup failed while creating an assistant session")
        raise HTTPException(status_code=503, detail="Employee lookup is temporarily unavailable.")

    if employee is None:
        raise HTTPException(status_code=404, detail="Unregistered NFC card")

    session, resumed = get_session_store().get_or_create_for_employee(employee)
    logger.info("Assistant session %s", "resumed" if resumed else "created")
    return AssistantSessionResponse(
        success=True,
        session_id=session.session_id,
        employee_name=session.employee_name,
        message="Assistant session resumed" if resumed else "Assistant session created",
        resumed=resumed,
    )


@router.post("/chat", response_model=AssistantChatResponse, summary="Send one message to the assistant")
async def chat(payload: AssistantChatRequest) -> AssistantChatResponse:
    try:
        session, outcome = await conversation_service.chat(
            payload.session_id, payload.message, llm_provider=get_llm_service
        )
    except SessionNotFoundError:
        raise HTTPException(status_code=401, detail="Session expired. Please tap your card again.")
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message)

    return AssistantChatResponse(
        success=True,
        session_id=payload.session_id,
        employee_name=session.employee_name,
        reply=outcome.reply,
        action=outcome.action,
        device=outcome.device,
        state=outcome.state,
    )
