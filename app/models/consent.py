from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.database import Base

class StudentConsent(Base):
    __tablename__ = "student_consents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    apaar_id = Column(String(32), nullable=False, index=True)
    purpose = Column(String(64), nullable=False, default="EMPLOYMENT_VERIFICATION")
    # Purposes: EMPLOYMENT_VERIFICATION, AICTE_AUDIT, CREDIT_MOBILITY, SCHOLARSHIP
    consent_granted = Column(Boolean, nullable=False, default=True)
    status = Column(String(32), nullable=False, default="ACTIVE")  # ACTIVE, WITHDRAWN
    data_scope = Column(String(128), default="NAME_PROGRAMME_COMPLETION_ONLY")
    granted_at = Column(DateTime, default=datetime.utcnow)
    withdrawn_at = Column(DateTime, nullable=True)
    ip_or_device = Column(String(64), default="STUDENT_PORTAL_WEB")
