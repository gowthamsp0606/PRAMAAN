from sqlalchemy import Column, String, Boolean, DateTime
from datetime import datetime
from app.database import Base

class Student(Base):
    __tablename__ = "students"

    student_ref = Column(String(64), primary_key=True, index=True)
    apaar_id = Column(String(32), unique=True, index=True, nullable=True)
    full_name = Column(String(128), nullable=False)
    primary_institution_id = Column(String(64), nullable=True)
    
    # International & Alternative Verification Routes (MoE Higher Ed Foreign National Protocol)
    identity_route = Column(String(32), default="AADHAAR_APAAR") # AADHAAR_APAAR, PASSPORT_INTERNATIONAL, OCI_CARD, HISTORICAL_LEGACY
    identity_status = Column(String(32), nullable=False, default="APAAR_VERIFIED", server_default="APAAR_VERIFIED", index=True) # APAAR_VERIFIED, APAAR_PENDING, HISTORICAL_NO_APAAR, ALTERNATIVE_ID_PENDING_VERIFICATION, EXEMPT_WHERE_POLICY_PERMITS
    passport_ref = Column(String(64), nullable=True)
    nationality = Column(String(64), default="Indian")
    is_nri = Column(Boolean, default=False)
    is_oci = Column(Boolean, default=False)
    is_foreign_national = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
