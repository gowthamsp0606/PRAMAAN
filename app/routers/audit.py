from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from app.database import get_db
from app.models.audit import AuditLog
from app.security import Principal, get_current_principal, mask_sensitive_payload

router = APIRouter(prefix="/audit-trail", tags=["Audit Trail"])

@router.get("")
def get_audit_trail(
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)

    total = query.count()
    items = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": log.id,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "action": log.action,
                "performed_by": log.performed_by,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "details": log.details if principal.role in {"administrator", "prototype_admin"} else mask_sensitive_payload(log.details)
            }
            for log in items
        ]
    }
