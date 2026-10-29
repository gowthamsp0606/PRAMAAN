import logging
import os
import uuid
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import engine, Base
from app.security import authorize_api_request, get_current_principal

logger = logging.getLogger("sentinel.api")
from app.routers import (
    dashboard,
    institution,
    aicte,
    students,
    enrolments,
    alerts,
    validation,
    intake,
    analytics,
    certificates,
    consent,
    verifier,
    reports,
    audit,
    auth,
    transfers,
    student,
    state,
    scholarship,
    search,
)

# Ensure tables exist and seed demo accounts only when not bound to the protected persistent demo db
if "apaar_sentinel.db" not in str(engine.url) or os.getenv("ENABLE_DB_SEED_ON_IMPORT", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)
    if settings.ENVIRONMENT != "production":
        try:
            from app.database import SessionLocal
            from app.services.auth_service import AuthService
            with SessionLocal() as _seed_db:
                AuthService.seed_demo_users(_seed_db)
        except Exception as _e:
            logger.warning("Could not auto-seed demo accounts on startup: %s", _e)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="APAAR ID-based student data management, temporal enrolment integrity, explainable conflict detection, and institutional compliance platform for AICTE-approved institutions.",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_origin_regex=r"https?://.*" if settings.ENVIRONMENT != "production" else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    incident_id = f"ERR-{uuid.uuid4().hex[:10].upper()}"
    logger.error("Unhandled API exception [incident=%s, path=%s]: %s", incident_id, request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. Please contact institutional support with the incident reference.",
            "incident_id": incident_id,
        },
    )


@app.get("/health", tags=["Health"])
def health_check():
    # Safe database target indicator without disclosing secrets or credentials
    db_target = "pramaan_india_demo.db" if "pramaan_india_demo.db" in str(engine.url) else "apaar_sentinel.db" if "apaar_sentinel.db" in str(engine.url) else "custom_db"
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database_target": db_target,
    }

# Mount Authentication Router (unprotected entrypoint for login)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)

# Mount API Routers
api_auth = [Depends(get_current_principal), Depends(authorize_api_request)]
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(institution.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(aicte.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(students.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(enrolments.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(alerts.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(validation.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(intake.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(analytics.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(certificates.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(consent.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(verifier.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(audit.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(transfers.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(student.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(state.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(scholarship.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
app.include_router(search.router, prefix=settings.API_V1_PREFIX, dependencies=api_auth)
