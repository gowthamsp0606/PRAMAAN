from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.audit import AuditLog

class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        entity_type: str,
        entity_id: str,
        action: str,
        performed_by: str,
        details: Optional[Dict[str, Any]] = None,
        commit: bool = True
    ) -> AuditLog:
        audit_entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            performed_by=performed_by,
            details=details or {}
        )
        db.add(audit_entry)
        if commit:
            db.commit()
            db.refresh(audit_entry)
        else:
            db.flush()
        return audit_entry
