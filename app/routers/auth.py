from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User
from app.services.auth_service import (
    AuthService,
    PasswordHasher,
    TokenManager,
    ROLE_MAP,
    ROLE_CATEGORY_MAP,
)
from app.services.audit_service import AuditService
from app.security import (
    Principal,
    get_current_principal,
    require_roles,
    bearer_scheme,
)
from app.rate_limiter import InMemoryRateLimiter
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication & Access Governance"])

login_rate_limiter = InMemoryRateLimiter(requests_limit=10, window_seconds=60)


def rate_limit_login(request: Request) -> None:
    login_rate_limiter.check(request)


def get_dashboard_route_for_role(role: str) -> str:
    routes = {
        "administrator": "/admin-dashboard",
        "prototype_admin": "/admin-dashboard",
        "reviewer": "/aicte-dashboard",
        "institution_officer": "/institution-dashboard",
        "external_verifier": "/employer-portal",
        "read_only_auditor": "/auditor-dashboard",
        "state_officer": "/state-dashboard",
        "student": "/student-dashboard",
    }
    return routes.get(role, "/aicte-dashboard")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128, description="Username or email address")
    password: str = Field(..., min_length=1, max_length=128)
    requested_role: Optional[str] = Field(None, description="Optional requested role context to validate against authenticated user's actual role")


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    role_category: str
    institution_id: Optional[str] = None
    verifier_org_id: Optional[str] = None
    purpose_scope: Optional[str] = None
    student_ref: Optional[str] = None
    is_active: bool
    dashboard_route: str
    last_login_at: Optional[datetime] = None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    email: str = Field(..., min_length=5, max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=128)
    role_category: str = Field(..., description="PROTOTYPE_ADMIN, AICTE_REGIONAL_REVIEWER, INSTITUTION_REGISTRAR, BGV_VERIFIER, COMPLIANCE_AUDITOR, STUDENT")
    institution_id: Optional[str] = None
    verifier_org_id: Optional[str] = None
    purpose_scope: Optional[str] = None
    student_ref: Optional[str] = None


@router.post("/login", dependencies=[Depends(rate_limit_login)])
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Authenticate user with credentials, returning JWT access token and setting secure session cookie.
    Applies sliding-window rate limiting and generic error messages.
    """
    user = AuthService.authenticate_user(db, payload.username, payload.password)
    if not user:
        AuditService.log_event(
            db=db,
            entity_type="AUTH",
            entity_id=payload.username[:64],
            action="LOGIN_FAILURE",
            performed_by=payload.username[:64],
            details={"ip": request.client.host if request.client else "unknown"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate requested role context if supplied (Role selection is a requested context, not a grant)
    if payload.requested_role:
        req = payload.requested_role.strip().lower()
        valid_roles = {user.role.lower()}
        if user.role_category:
            valid_roles.add(user.role_category.lower())
            valid_roles.add(user.role_category.lower().replace("_", " "))
        if user.role in ("administrator", "prototype_admin"):
            valid_roles.update({"administrator", "prototype_admin", "national administrator", "national_administrator", "prototype admin"})
        elif user.role == "reviewer":
            valid_roles.update({"reviewer", "aicte_regional_reviewer", "aicte regional reviewer"})
        elif user.role == "institution_officer":
            valid_roles.update({"institution_officer", "institution_registrar", "institution registrar"})
        elif user.role == "external_verifier":
            valid_roles.update({"external_verifier", "bgv_verifier", "bgv verifier", "employer", "verifier"})
        elif user.role == "read_only_auditor":
            valid_roles.update({"read_only_auditor", "compliance_auditor", "compliance auditor"})
        elif user.role == "state_officer":
            valid_roles.update({"state_officer", "state_education_official", "state education official", "state officer"})
        elif user.role == "student":
            valid_roles.update({"student"})

        if req not in valid_roles:
            AuditService.log_event(
                db=db,
                entity_type="AUTH",
                entity_id=str(user.id),
                action="ROLE_MISMATCH_REJECTED",
                performed_by=user.username,
                details={
                    "actual_role": user.role,
                    "requested_role": payload.requested_role,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: User '{user.username}' does not possess the requested role '{payload.requested_role}'. Actual role: '{user.role}'.",
            )

    student_ref = None
    if user.role == "student":
        from app.services.student_service import StudentService
        student = StudentService.get_student_for_user(db, user.id, user.username)
        if student:
            student_ref = student.student_ref

    token, jti, expires_at = TokenManager.create_access_token(user, student_ref=student_ref)

    # Set HttpOnly Session Cookie with appropriate flags
    is_prod = settings.ENVIRONMENT == "production"
    response.set_cookie(
        key="pramaan_token",
        value=token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=8 * 3600,
        path="/",
    )

    AuditService.log_event(
        db=db,
        entity_type="AUTH",
        entity_id=str(user.id),
        action="LOGIN_SUCCESS",
        performed_by=user.username,
        details={
            "role": user.role,
            "role_category": user.role_category,
            "institution_id": user.institution_id,
            "jti": jti,
        },
    )

    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "role_category": user.role_category,
            "institution_id": user.institution_id,
            "verifier_org_id": user.verifier_org_id,
            "purpose_scope": user.purpose_scope,
            "student_ref": student_ref,
            "dashboard_route": get_dashboard_route_for_role(user.role),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        },
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Revoke authenticated JWT session and clear session cookies.
    """
    auth_header = request.headers.get("Authorization")
    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.removeprefix("Bearer ").strip()
    else:
        raw_token = request.cookies.get("pramaan_token") or request.cookies.get("access_token")

    if raw_token:
        TokenManager.revoke_token(raw_token, db)

    response.delete_cookie(key="pramaan_token", path="/")
    response.delete_cookie(key="access_token", path="/")

    AuditService.log_event(
        db=db,
        entity_type="AUTH",
        entity_id=principal.subject,
        action="LOGOUT",
        performed_by=principal.subject,
        details={"role": principal.role},
    )

    return {"success": True, "message": "Successfully logged out. Session has been revoked."}


@router.get("/me")
def get_current_user_profile(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve authenticated user profile, validated roles, and institutional scopes.
    Unauthenticated prototype principals are rejected with 401 so the frontend
    correctly presents the authentication challenge.
    """
    if principal.subject == "local-prototype":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.username == principal.subject).first()
    role_category = getattr(principal, "role_category", None) or (user.role_category if user else ROLE_CATEGORY_MAP.get(principal.role, "PROTOTYPE_ADMIN"))
    full_name = user.full_name if user else f"Officer ({principal.subject})"

    student_ref = getattr(principal, "student_ref", None)
    if not student_ref and principal.role == "student" and user:
        from app.services.student_service import StudentService
        student = StudentService.get_student_for_user(db, user.id, user.username)
        if student:
            student_ref = student.student_ref

    return {
        "authenticated": True,
        "username": principal.subject,
        "full_name": full_name,
        "email": user.email if user else f"{principal.subject}@pramaan.local",
        "role": principal.role,
        "role_category": role_category,
        "institution_id": principal.institution_id,
        "verifier_org_id": principal.verifier_org_id,
        "purpose_scope": principal.purpose_scope,
        "student_ref": student_ref,
        "dashboard_route": get_dashboard_route_for_role(principal.role),
        "is_active": user.is_active if user else True,
    }


@router.get("/users", response_model=List[UserResponse])
def list_system_users(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_roles("administrator")),
):
    """
    Admin-only user registry overview for identity & access governance.
    """
    users = db.query(User).order_by(User.id.asc()).all()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            role_category=u.role_category,
            institution_id=u.institution_id,
            verifier_org_id=u.verifier_org_id,
            purpose_scope=u.purpose_scope,
            is_active=u.is_active,
            dashboard_route=get_dashboard_route_for_role(u.role),
            last_login_at=u.last_login_at,
        )
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def create_system_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("administrator")),
):
    """
    Admin-only user creation endpoint ensuring strictly server-assigned roles.
    Prevents horizontal privilege escalation and unauthorized self-assignment.
    """
    if payload.role_category not in ROLE_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role category '{payload.role_category}'. Allowed: {list(ROLE_MAP.keys())}",
        )

    mapped_role = ROLE_MAP[payload.role_category]

    # Check unique constraints
    if db.query(User).filter(User.username == payload.username.lower()).first():
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' is already in use.")
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=409, detail=f"Email '{payload.email}' is already registered.")

    new_user = User(
        username=payload.username.lower(),
        email=payload.email.lower(),
        password_hash=PasswordHasher.hash_password(payload.password),
        full_name=payload.full_name,
        role=mapped_role,
        role_category=payload.role_category,
        institution_id=payload.institution_id,
        verifier_org_id=payload.verifier_org_id,
        purpose_scope=payload.purpose_scope,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    if payload.student_ref:
        from app.services.student_service import StudentService
        StudentService.link_user_to_student(db, new_user.id, payload.student_ref)

    AuditService.log_event(
        db=db,
        entity_type="USER",
        entity_id=str(new_user.id),
        action="USER_CREATED",
        performed_by=principal.subject,
        details={
            "created_username": new_user.username,
            "role": new_user.role,
            "role_category": new_user.role_category,
            "institution_id": new_user.institution_id,
        },
    )

    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role,
        role_category=new_user.role_category,
        institution_id=new_user.institution_id,
        verifier_org_id=new_user.verifier_org_id,
        purpose_scope=new_user.purpose_scope,
        is_active=new_user.is_active,
        dashboard_route=get_dashboard_route_for_role(new_user.role),
        last_login_at=new_user.last_login_at,
    )
