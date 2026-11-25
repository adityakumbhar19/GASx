"""FastAPI application entry point.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env BEFORE the app modules below are imported, because some of them
# (e.g. database.py) read their settings from the environment at import time.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.router.employee import router as employee_router
from app.router.scan import router as scan_router
from app.router.kiosk import router as kiosk_router
from app.router.voice import router as voice_router
from app.router.assistant import router as assistant_router
from app.schemas import HealthResponse
from app.database import init_db
from app.employees import use_memory_employees
from app.seed import seed_employees

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("nfc-welcome")

SERVICE_NAME = "nfc-employee-welcome-backend"
VERSION = "1.0.0"

app = FastAPI(
    title="NFC Employee Welcome API",
    version=VERSION,
    description="PostgreSQL-backed employee identification and NFC attendance kiosk API.",
)

# CORS wide open for DEVELOPMENT ONLY. Restrict allow_origins before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(employee_router, prefix="/api/v1")
app.include_router(scan_router, prefix="/api/v1")
app.include_router(kiosk_router)
app.include_router(kiosk_router, prefix="/api/v1")
app.include_router(voice_router, prefix="/api/v1")
app.include_router(voice_router)
app.include_router(assistant_router, prefix="/api/v1")


@app.on_event("startup")
def startup() -> None:
    if use_memory_employees():
        logger.warning(
            "EMPLOYEE_SOURCE=memory: using the hardcoded EMPLOYEES in app/employees.py. "
            "PostgreSQL is NOT used (no stored attendance, photos or kiosk endpoints)."
        )
        return
    init_db()
    seed_employees()


def _error_body(message: str, errors=None) -> dict:
    """Error envelope shaped like IdentifyResponse so the Android client can always parse it."""
    body = {"success": False, "message": message, "employee_id": None, "employee_name": None}
    if errors is not None:
        body["errors"] = errors
    return body


@app.get("/api/v1/health", response_model=HealthResponse, tags=["Health"], summary="Backend health check")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"), "message": str(err.get("msg", ""))}
        for err in exc.errors()
    ]
    logger.warning("Invalid request to %s: %s", request.url.path, errors)
    return JSONResponse(status_code=422, content=_error_body("Invalid request", errors))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=_error_body(str(exc.detail)))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content=_error_body("Internal server error"))
