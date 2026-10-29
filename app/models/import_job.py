from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id = Column(String(36), primary_key=True)
    institution_id = Column(String(64), nullable=True, index=True)
    submitted_by = Column(String(128), nullable=False)
    original_filename = Column(String(255), nullable=False)
    previous_job_id = Column(String(36), ForeignKey("import_jobs.id"), nullable=True, index=True)
    status = Column(String(32), nullable=False, index=True)
    total_rows = Column(Integer, nullable=False, default=0)
    accepted_rows = Column(Integer, nullable=False, default=0)
    rejected_rows = Column(Integer, nullable=False, default=0)
    review_rows = Column(Integer, nullable=False, default=0)
    validation_summary = Column(JSON, nullable=False, default=dict)
    safe_error_summary = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)


class ImportRowResult(Base):
    __tablename__ = "import_row_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_job_id = Column(String(36), ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_row_result_id = Column(Integer, ForeignKey("import_row_results.id"), nullable=True, index=True)
    row_number = Column(Integer, nullable=False)
    record_reference = Column(String(64), nullable=True, index=True)
    identity_hash = Column(String(64), nullable=True, index=True)
    outcome = Column(String(24), nullable=False, index=True)
    persisted = Column(Boolean, nullable=False, default=False)
    issue_codes = Column(JSON, nullable=False, default=list)
    validation_messages = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("import_job_id", "row_number", name="uq_import_row_job_number"),
        Index("idx_import_row_identity", "import_job_id", "identity_hash"),
    )