from sqlalchemy import Column, String, DateTime, Text, JSON
from datetime import datetime
from app.database import Base

class Certificate(Base):
    __tablename__ = "certificates"

    certificate_id = Column(String(64), primary_key=True, index=True)
    student_ref = Column(String(64), nullable=False, index=True)
    apaar_id = Column(String(32), nullable=False, index=True)
    student_name = Column(String(128), nullable=False)
    institution_id = Column(String(64), nullable=False)
    institution_name = Column(String(128), nullable=False)
    programme_id = Column(String(64), nullable=False)
    programme_name = Column(String(128), nullable=False)
    issue_date = Column(String(16), nullable=False)
    completion_date = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="VALID")  # VALID, REVOKED
    revocation_reason = Column(String(256), nullable=True)
    signature_algorithm = Column(String(32), nullable=False, default="HMAC-SHA256")
    signature_hex = Column(Text, nullable=False)
    public_key_id = Column(String(64), nullable=False, default="SENTINEL-TEST-ROOT-2026")
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
