from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(128), nullable=False)
    role = Column(String(32), nullable=False)  # administrator, reviewer, institution_officer, external_verifier, read_only_auditor
    role_category = Column(String(32), nullable=False)  # PROTOTYPE_ADMIN, AICTE_REGIONAL_REVIEWER, INSTITUTION_REGISTRAR, BGV_VERIFIER, COMPLIANCE_AUDITOR
    institution_id = Column(String(64), nullable=True)
    verifier_org_id = Column(String(64), nullable=True)
    purpose_scope = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True, index=True)
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
