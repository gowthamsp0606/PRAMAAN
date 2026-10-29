import hashlib
import re
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import settings


from sqlalchemy.orm import Session
from app.database import get_db

Role = Literal[
    "administrator",
    "institution_officer",
    "reviewer",
    "read_only_auditor",
    "external_verifier",
    "prototype_admin",
    "student",
    "state_officer",
]


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    role: Role
    institution_id: Optional[str] = None
    state: Optional[str] = None
    verifier_org_id: Optional[str] = None
    purpose_scope: Optional[Literal["EMPLOYMENT_VERIFICATION"]] = None
    role_category: Optional[str] = None
    user_id: Optional[int] = None
    student_ref: Optional[str] = None


bearer_scheme = HTTPBearer(auto_error=False)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_token_registry() -> None:
    registry = settings.API_TOKEN_PRINCIPALS
    if not isinstance(registry, dict):
        raise RuntimeError("API_TOKEN_PRINCIPALS_JSON must be a JSON object keyed by SHA-256 token hashes.")
    if settings.AUTH_REQUIRED and not registry:
        raise RuntimeError("AUTH_REQUIRED is true, but no API token principals are configured.")
    for token_hash, claims in registry.items():
        if not _SHA256_RE.fullmatch(token_hash):
            raise RuntimeError("API_TOKEN_PRINCIPALS_JSON keys must be lowercase SHA-256 hex digests.")
        try:
            principal = Principal.model_validate(claims)
        except ValidationError as exc:
            raise RuntimeError("API_TOKEN_PRINCIPALS_JSON contains invalid principal claims.") from exc
        if settings.AUTH_REQUIRED and principal.role == "prototype_admin":
            raise RuntimeError("prototype_admin principals are only available when AUTH_REQUIRED is false.")


def get_current_principal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    raw_token: Optional[str] = None
    if credentials is not None:
        raw_token = credentials.credentials
    elif request is not None:
        raw_token = request.cookies.get("pramaan_token") or request.cookies.get("access_token")

    if not raw_token:
        if settings.AUTH_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Principal(subject="local-prototype", role="prototype_admin", role_category="PROTOTYPE_ADMIN")

    # 1. Attempt database-backed JWT verification
    from app.services.auth_service import TokenManager
    try:
        payload = TokenManager.verify_token(raw_token, db=db)
        state_val = payload.get("state")
        if not state_val and payload.get("role") == "state_officer":
            inst = payload.get("institution_id") or ""
            if inst.startswith("STATE-"):
                state_val = inst.removeprefix("STATE-")
            elif inst.startswith("STATE:"):
                state_val = inst.removeprefix("STATE:")
            elif inst:
                state_val = inst

        return Principal(
            subject=payload["sub"],
            role=payload["role"],
            institution_id=payload.get("institution_id"),
            state=state_val,
            verifier_org_id=payload.get("verifier_org_id"),
            purpose_scope=payload.get("purpose_scope"),
            role_category=payload.get("role_category"),
            user_id=payload.get("user_id"),
            student_ref=payload.get("student_ref"),
        )
    except ValueError as val_err:
        # If the token is formatted as a JWT, reject it directly
        if raw_token.count(".") == 2 or raw_token.startswith("eyJ"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(val_err),
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 2. Backward compatibility: Fallback to static SHA-256 token registry
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    claims = settings.API_TOKEN_PRINCIPALS.get(token_hash)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer credential.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return Principal.model_validate(claims)
    except ValidationError as exc:
        raise HTTPException(status_code=503, detail="Configured bearer principal is invalid.") from exc


def require_roles(*allowed_roles: Role):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role != "prototype_admin" and principal.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="This role is not permitted to perform this action.")
        return principal

    return dependency


def authorize_api_request(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if principal.role in {"administrator", "prototype_admin"}:
        return principal

    path = request.url.path.removeprefix(settings.API_V1_PREFIX)
    if path in {"/auth/logout", "/auth/me"}:
        return principal
    method = request.method.upper()
    allowed = False

    if principal.role == "external_verifier":
        allowed = (
            (method == "POST" and path == "/verifier/verify-credential")
            or (method == "GET" and path == "/verifier/organizations")
            or (method == "GET" and path == "/verifier/logs")
            or (method == "GET" and path.startswith("/certificates/public-keys"))
            or (method == "GET" and (path == "/search" or path.startswith("/search")))
        )
    elif principal.role == "read_only_auditor":
        allowed = method in {"GET", "HEAD"}
    elif principal.role == "state_officer":
        allowed = (method in {"GET", "HEAD"} and (
            path.startswith("/state")
            or path.startswith("/analytics")
            or path.startswith("/transfers")
            or path.startswith("/intake-compliance")
            or path.startswith("/alerts")
            or path.startswith("/scholarship")
            or path.startswith("/reports")
            or path == "/institution/dashboard-summary"
            or path == "/institution/list"
            or path.startswith("/institution/list")
            or path == "/students"
            or path.startswith("/students/")
            or path == "/search"
            or path.startswith("/search")
        )) or (
            method in {"POST", "PATCH"}
            and (
                path.startswith("/state/")
                or (path.startswith("/alerts/") and any(path.endswith(s) for s in ("/review", "/notes", "/clarification")))
            )
        )
    elif principal.role == "reviewer":
        allowed = method in {"GET", "HEAD"}
        if method in {"POST", "PATCH"}:
            allowed = (
                any(path.endswith(suffix) for suffix in (
                    "/review", "/assignment", "/clarification", "/notes", "/reopen", "/identity-status"
                ))
                or (path.startswith("/analytics/anomalies/") and path.endswith("/dismiss"))
            )
    elif principal.role == "student":
        allowed = (
            method in {"GET", "HEAD"}
            and (
                path.startswith("/student/")
                or path.startswith("/search")
                or (path.startswith("/certificates/") and (path.endswith("/download") or "/verify" in path or path.count("/") == 2))
                or path.startswith("/transfers/")
                or path == "/transfers"
            )
        ) or (
            method in {"PATCH", "POST", "PUT"}
            and (
                path.startswith("/student/")
                or (path.startswith("/transfers/") and path.endswith("/cancel"))
            )
        )
    elif principal.role == "institution_officer":
        allowed = (
            method in {"GET", "HEAD"}
            and (
                path.startswith("/institution/")
                or path == "/students"
                or path.startswith("/students/")
                or path == "/enrolments"
                or path.startswith("/enrolments/")
                or path == "/search"
                or path.startswith("/search")
                or path == "/intake-compliance"
                or path.startswith("/intake-compliance/")
                or path == "/alerts"
                or path.startswith("/alerts/")
                or path == "/analytics"
                or path.startswith("/analytics/")
                or path == "/certificates"
                or path.startswith("/certificates/")
                or path == "/consent"
                or path.startswith("/consent/")
                or path == "/validation"
                or path.startswith("/validation/")
                or path == "/transfers"
                or path.startswith("/transfers/")
                or path == "/scholarship"
                or path.startswith("/scholarship/")
                or path.startswith("/reports")
            )
        ) or (
            method in {"POST", "PATCH", "PUT"}
            and (
                path.startswith("/institution/")
                or path in {"/students", "/students/upload", "/students/upload-csv", "/enrolments", "/certificates/issue", "/consent", "/transfers/initiate"}
                or path.startswith("/consent/")
                or path.startswith("/validation/")
                or path.startswith("/transfers/")
                or path.endswith("/identity-status")
                or (path.startswith("/certificates/") and path.endswith("/revoke"))
                or (path.startswith("/alerts/") and any(path.endswith(s) for s in ("/review", "/assignment", "/clarification", "/notes", "/reopen")))
            )
        )

    if not allowed:
        raise HTTPException(status_code=403, detail="This role is not permitted to access this API operation.")
    return principal


INSTITUTION_ALIASES = {
    "INST-DEMO-01": "INST-CHENNAI-SJCE",
    "INST-CHENNAI-SJC": "INST-CHENNAI-SJCE",
}


def canonicalize_institution_id(inst_id: Optional[str]) -> Optional[str]:
    if not inst_id:
        return inst_id
    inst_clean = str(inst_id).strip()
    return INSTITUTION_ALIASES.get(inst_clean, inst_clean)


def enforce_institution_scope(principal: Principal, requested_institution_id: Optional[str]) -> Optional[str]:
    if principal.role == "institution_officer":
        if not principal.institution_id:
            raise HTTPException(status_code=403, detail="No institution is assigned to this principal.")
        canon_principal = canonicalize_institution_id(principal.institution_id)
        canon_requested = canonicalize_institution_id(requested_institution_id)
        if canon_requested and canon_requested != canon_principal:
            raise HTTPException(status_code=403, detail="Cross-institution access is not permitted.")
        return principal.institution_id
    return requested_institution_id


def enforce_state_scope(principal: Principal, requested_state: Optional[str] = None) -> str:
    if principal.role == "state_officer":
        if not principal.state:
            raise HTTPException(status_code=403, detail="No state jurisdiction is assigned to this principal.")
        assigned_state = principal.state.strip().upper()
        if requested_state and requested_state.strip().upper() != assigned_state:
            raise HTTPException(status_code=403, detail=f"Cross-state access denied. You only have jurisdiction over {assigned_state}.")
        return assigned_state

    if requested_state:
        return requested_state.strip().upper()
    return "DELHI"


def mask_identifier(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    visible = value[-4:]
    return f"{'*' * max(4, len(value) - len(visible))}{visible}"


def mask_sensitive_payload(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {"apaar_id", "query_apaar_id", "passport_ref"}:
                masked[key] = mask_identifier(str(item)) if item is not None else None
            elif normalized_key in {"identity_evidence", "matched_identity"}:
                masked[key] = "[redacted]"
            elif normalized_key in {"signature_hex", "private_key", "access_token", "refresh_token"}:
                masked[key] = None
            else:
                masked[key] = mask_sensitive_payload(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive_payload(item) for item in value]
    return value


def require_student_institution(db, student_ref: str, institution_id: Optional[str]) -> None:
    if not institution_id:
        return
    from app.models.enrolment import Enrolment
    from app.models.student import Student

    student = db.query(Student).filter(Student.student_ref == student_ref).first()
    has_primary_scope = bool(student and student.primary_institution_id == institution_id)
    has_enrolment_scope = db.query(Enrolment.id).filter(
        Enrolment.student_ref == student_ref,
        Enrolment.institution_id == institution_id,
    ).first() is not None
    if not has_primary_scope and not has_enrolment_scope:
        raise HTTPException(status_code=404, detail="Student not found in this institution.")


_validate_token_registry()
