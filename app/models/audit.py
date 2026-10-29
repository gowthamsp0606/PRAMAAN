from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime
from app.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(32), nullable=False, index=True)  # ALERT, STUDENT, ENROLMENT, CERTIFICATE, VALIDATION
    entity_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)  # REVIEW_DECISION, CSV_IMPORT, CREATE, VERIFICATION
    performed_by = Column(String(128), nullable=False)
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
