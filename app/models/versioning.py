from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime
from app.database import Base

class EnrolmentVersion(Base):
    __tablename__ = "enrolment_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enrolment_id = Column(Integer, nullable=False, index=True)
    student_ref = Column(String(64), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    institution_id = Column(String(64), nullable=False)
    programme_id = Column(String(64), nullable=False)
    enrolment_status = Column(String(32), nullable=False)
    academic_year = Column(String(16), nullable=False)
    changed_by = Column(String(128), nullable=False, default="System Data Ingest")
    change_reason = Column(String(256), nullable=True)
    diff_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
