from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from datetime import datetime
from app.database import Base

class VerifierOrganization(Base):
    __tablename__ = "verifier_organizations"

    id = Column(String(64), primary_key=True)
    org_name = Column(String(128), nullable=False)
    org_type = Column(String(64), nullable=False, default="EMPLOYER")  # EMPLOYER, REGULATOR, EMBASSY
    is_approved = Column(Boolean, default=True)
    contact_email = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class VerificationRequestLog(Base):
    __tablename__ = "verification_request_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    verifier_org_id = Column(String(64), nullable=False, index=True)
    verifier_org_name = Column(String(128), nullable=False)
    query_student_ref = Column(String(64), nullable=True)
    query_apaar_id = Column(String(32), nullable=True)
    certificate_id = Column(String(64), nullable=True)
    verification_outcome = Column(String(64), nullable=False)  # MATCH_VERIFIED, NO_MATCH, CONSENT_WITHHELD, RECORD_REVOKED
    limited_response_json = Column(JSON, nullable=True)
    ip_address = Column(String(64), default="127.0.0.1")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
