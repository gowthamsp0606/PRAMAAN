from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from datetime import datetime, timezone
from app.database import Base


class StudentUserLink(Base):
    __tablename__ = "student_user_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    student_ref = Column(String(64), nullable=False, index=True)
    is_primary = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_student_user_link_unique", "user_id", "student_ref", unique=True),
    )
