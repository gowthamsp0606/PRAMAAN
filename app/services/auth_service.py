import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User, RevokedToken

# PBKDF2-HMAC-SHA256 Parameters conforming to OWASP guidelines
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 600000
SALT_BYTES = 16

ROLE_MAP = {
    "PROTOTYPE_ADMIN": "administrator",
    "AICTE_REGIONAL_REVIEWER": "reviewer",
    "INSTITUTION_REGISTRAR": "institution_officer",
    "BGV_VERIFIER": "external_verifier",
    "COMPLIANCE_AUDITOR": "read_only_auditor",
    "STUDENT": "student",
    "STATE_EDUCATION_OFFICIAL": "state_officer",
}

ROLE_CATEGORY_MAP = {
    "administrator": "PROTOTYPE_ADMIN",
    "prototype_admin": "PROTOTYPE_ADMIN",
    "reviewer": "AICTE_REGIONAL_REVIEWER",
    "institution_officer": "INSTITUTION_REGISTRAR",
    "external_verifier": "BGV_VERIFIER",
    "read_only_auditor": "COMPLIANCE_AUDITOR",
    "student": "STUDENT",
    "state_officer": "STATE_EDUCATION_OFFICIAL",
}


class PasswordHasher:
    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash password using PBKDF2-HMAC-SHA256 with cryptographically random salt."""
        salt = secrets.token_bytes(SALT_BYTES)
        derived_key = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
            dklen=32,
        )
        return f"pbkdf2_{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${derived_key.hex()}"

    @classmethod
    def verify_password(cls, password: str, password_hash: str) -> bool:
        """Verify plaintext password against stored MCF hash using constant-time comparison."""
        try:
            parts = password_hash.split("$")
            if len(parts) != 4:
                return False
            algo, iters_str, salt_hex, key_hex = parts
            if algo != f"pbkdf2_{PBKDF2_ALGORITHM}":
                return False
            iterations = int(iters_str)
            salt = bytes.fromhex(salt_hex)
            expected_key = bytes.fromhex(key_hex)
            derived = hashlib.pbkdf2_hmac(
                PBKDF2_ALGORITHM,
                password.encode("utf-8"),
                salt,
                iterations,
                dklen=len(expected_key),
            )
            return hmac.compare_digest(derived, expected_key)
        except Exception:
            return False


class TokenManager:
    @classmethod
    def create_access_token(
        cls,
        user: User,
        expires_delta: Optional[timedelta] = None,
        student_ref: Optional[str] = None,
    ) -> Tuple[str, str, datetime]:
        """Create a signed JWT access token for the authenticated user."""
        now = datetime.now(timezone.utc)
        expires_at = now + (expires_delta or timedelta(hours=8))
        jti = str(uuid.uuid4())

        state_claim = None
        if user.role == "state_officer":
            inst = user.institution_id or ""
            if inst.startswith("STATE-"):
                state_claim = inst.removeprefix("STATE-")
            elif inst.startswith("STATE:"):
                state_claim = inst.removeprefix("STATE:")
            elif inst:
                state_claim = inst

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "role_category": user.role_category,
            "institution_id": user.institution_id,
            "state": state_claim,
            "verifier_org_id": user.verifier_org_id,
            "purpose_scope": user.purpose_scope,
            "student_ref": student_ref,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        return token, jti, expires_at

    @classmethod
    def verify_token(cls, token: str, db: Optional[Session] = None) -> Dict[str, Any]:
        """Verify signature, expiry, and revocation state of a JWT."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ValueError("Authentication token has expired.")
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid authentication token: {str(e)}")

        jti = payload.get("jti")
        if db is not None and jti:
            is_revoked = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
            if is_revoked:
                raise ValueError("Session has been logged out / revoked.")

        return payload

    @classmethod
    def revoke_token(cls, token: str, db: Session) -> bool:
        """Mark a token's jti as revoked in the database."""
        try:
            # Decode without verifying expiration so even nearly-expired tokens can be revoked
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            jti = payload.get("jti")
            exp_ts = payload.get("exp")
            if not jti:
                return False

            expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).replace(tzinfo=None) if exp_ts else datetime.utcnow() + timedelta(hours=24)
            if not db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
                revoked = RevokedToken(jti=jti, expires_at=expires_at)
                db.add(revoked)
                db.commit()
            return True
        except Exception:
            return False


class AuthService:
    @classmethod
    def authenticate_user(
        cls,
        db: Session,
        username_or_email: str,
        password: str,
    ) -> Optional[User]:
        """Authenticate user by username or email and plaintext password."""
        identifier = username_or_email.strip().lower()
        user = db.query(User).filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if not user or not user.is_active:
            # Run dummy verification to resist timing attacks
            PasswordHasher.verify_password("dummy", "pbkdf2_sha256$600000$00000000000000000000000000000000$0000000000000000000000000000000000000000000000000000000000000000")
            return None

        if not PasswordHasher.verify_password(password, user.password_hash):
            return None

        user.last_login_at = datetime.utcnow()
        db.commit()
        return user

    @classmethod
    def seed_demo_users(cls, db: Session) -> Dict[str, str]:
        """
        Seed initial demo users for development and verification environments.
        Strictly skipped if ENVIRONMENT is 'production'.
        Does not overwrite existing user accounts or their modified passwords.
        """
        if settings.ENVIRONMENT == "production":
            return {}

        demo_accounts = [
            {
                "username": "admin",
                "email": "admin@pramaan.gov.in",
                "full_name": "Sovereign Administrator (Demo)",
                "role": "administrator",
                "role_category": "PROTOTYPE_ADMIN",
                "institution_id": None,
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_ADMIN",
                "default_pwd": "PramaanAdmin@2026!",
            },
            {
                "username": "aicte_reviewer",
                "email": "ro102@aicte.gov.in",
                "full_name": "AICTE Regional Officer (RO-102)",
                "role": "reviewer",
                "role_category": "AICTE_REGIONAL_REVIEWER",
                "institution_id": None,
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_REVIEWER",
                "default_pwd": "AicteReviewer@2026!",
            },
            {
                "username": "sjce_registrar",
                "email": "registrar@stjosephs.ac.in",
                "full_name": "Registrar, St. Joseph's College of Engineering",
                "role": "institution_officer",
                "role_category": "INSTITUTION_REGISTRAR",
                "institution_id": "INST-CHENNAI-SJCE",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_SJCE_REGISTRAR",
                "default_pwd": "SjceRegistrar@2026!",
            },
            {
                "username": "dtu_registrar",
                "email": "registrar@dtu.ac.in",
                "full_name": "Registrar, Delhi Tech University",
                "role": "institution_officer",
                "role_category": "INSTITUTION_REGISTRAR",
                "institution_id": "INST-DELHI-DTU",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_INSTITUTION",
                "default_pwd": "DtuRegistrar@2026!",
            },
            {
                "username": "tcs_verifier",
                "email": "bgv.verify@tcs.com",
                "full_name": "TCS Background Verification Cell",
                "role": "external_verifier",
                "role_category": "BGV_VERIFIER",
                "institution_id": None,
                "verifier_org_id": "ORG-TCS-BGV",
                "purpose_scope": "EMPLOYMENT_VERIFICATION",
                "env_pwd_key": "DEMO_PASSWORD_VERIFIER",
                "default_pwd": "TcsVerifier@2026!",
            },
            {
                "username": "compliance_auditor",
                "email": "auditor@cag.gov.in",
                "full_name": "Principal Regulatory Auditor",
                "role": "read_only_auditor",
                "role_category": "COMPLIANCE_AUDITOR",
                "institution_id": None,
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_AUDITOR",
                "default_pwd": "ComplianceAuditor@2026!",
            },
            {
                "username": "student_demo",
                "email": "student.demo@pramaan.gov.in",
                "full_name": "Aarav Sharma (Student Demo)",
                "role": "student",
                "role_category": "STUDENT",
                "institution_id": "INST-DELHI-DTU",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STUDENT",
                "default_pwd": "StudentDemo@2026!",
                "student_ref": "STU-DEMO-001",
            },
            {
                "username": "student_karthik",
                "email": "student.karthik@pramaan.gov.in",
                "full_name": "Karthik Raja S",
                "role": "student",
                "role_category": "STUDENT",
                "institution_id": "INST-CHENNAI-SJCE",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STUDENT_KARTHIK",
                "default_pwd": "StudentKarthik@2026!",
                "student_ref": "STU-SJCE-001",
            },
            {
                "username": "student_aarav",
                "email": "student.aarav@pramaan.gov.in",
                "full_name": "Aarav Sharma",
                "role": "student",
                "role_category": "STUDENT",
                "institution_id": "INST-DELHI-DTU",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STUDENT_AARAV",
                "default_pwd": "StudentAarav@2026!",
                "student_ref": "STU-IND-081",
            },
            {
                "username": "pes_registrar",
                "email": "registrar@pes.edu",
                "full_name": "Registrar, PES University",
                "role": "institution_officer",
                "role_category": "INSTITUTION_REGISTRAR",
                "institution_id": "INST-BLR-PES",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_PES_REGISTRAR",
                "default_pwd": "PesRegistrar@2026!",
            },
            {
                "username": "student_priya",
                "email": "priya.student@pramaan.gov.in",
                "full_name": "Priya Patel (Student Demo 2)",
                "role": "student",
                "role_category": "STUDENT",
                "institution_id": "INST-DELHI-IIITD",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STUDENT2",
                "default_pwd": "StudentPriya@2026!",
                "student_ref": "STU-DEMO-002",
            },
            {
                "username": "delhi_state_officer",
                "email": "delhi.officer@education.delhi.gov.in",
                "full_name": "Director of Higher Education, Delhi",
                "role": "state_officer",
                "role_category": "STATE_EDUCATION_OFFICIAL",
                "institution_id": "STATE-DELHI",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STATE_DELHI",
                "default_pwd": "DelhiOfficer@2026!",
            },
            {
                "username": "tn_state_officer",
                "email": "tn.officer@tn.gov.in",
                "full_name": "Commissioner of Technical Education, Tamil Nadu",
                "role": "state_officer",
                "role_category": "STATE_EDUCATION_OFFICIAL",
                "institution_id": "STATE-TAMIL_NADU",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STATE_TN",
                "default_pwd": "TnOfficer@2026!",
            },
            {
                "username": "mh_state_officer",
                "email": "mh.officer@maharashtra.gov.in",
                "full_name": "Director of Technical Education, Maharashtra",
                "role": "state_officer",
                "role_category": "STATE_EDUCATION_OFFICIAL",
                "institution_id": "STATE-MAHARASHTRA",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STATE_MH",
                "default_pwd": "MhOfficer@2026!",
            },
            {
                "username": "karnataka_state_officer",
                "email": "karnataka.officer@dhte.karnataka.gov.in",
                "full_name": "Director of Technical Education, Karnataka",
                "role": "state_officer",
                "role_category": "STATE_EDUCATION_OFFICIAL",
                "institution_id": "STATE-KARNATAKA",
                "verifier_org_id": None,
                "purpose_scope": None,
                "env_pwd_key": "DEMO_PASSWORD_STATE_KA",
                "default_pwd": "KarnatakaOfficer@2026!",
            },
        ]

        from app.models.student_user import StudentUserLink

        seeded = {}
        for acc in demo_accounts:
            existing = db.query(User).filter(
                (User.username == acc["username"]) | (User.email == acc["email"])
            ).first()
            if not existing:
                pwd = os.getenv(acc["env_pwd_key"], os.getenv("DEMO_DEFAULT_PASSWORD", acc["default_pwd"]))
                user = User(
                    username=acc["username"],
                    email=acc["email"],
                    password_hash=PasswordHasher.hash_password(pwd),
                    full_name=acc["full_name"],
                    role=acc["role"],
                    role_category=acc["role_category"],
                    institution_id=acc["institution_id"],
                    verifier_org_id=acc["verifier_org_id"],
                    purpose_scope=acc["purpose_scope"],
                    is_active=True,
                )
                db.add(user)
                db.flush()
                seeded[acc["username"]] = acc["role_category"]
            else:
                user = existing

            if acc.get("student_ref") and user:
                link = db.query(StudentUserLink).filter(
                    StudentUserLink.user_id == user.id,
                    StudentUserLink.student_ref == acc["student_ref"],
                ).first()
                if not link:
                    db.add(StudentUserLink(
                        user_id=user.id,
                        student_ref=acc["student_ref"],
                        is_primary=True,
                    ))

        if seeded:
            db.commit()
        return seeded
