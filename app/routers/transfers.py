from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from app.database import get_db
from app.models.transfer import TransferRequest
from app.models.student import Student
from app.models.erp import StudentProfile
from app.schemas.transfer import (
    TransferInitiateRequest,
    TransferReleaseRequest,
    TransferAdmitRequest,
    TransferCancelRequest,
    TransferResponse,
    TransferListResponse,
)
from app.security import Principal, get_current_principal, enforce_institution_scope
from app.services.transfer_service import TransferService
from app.services.pdf_generator import PdfGeneratorService
from app.services.export_service import ExportService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/transfers", tags=["Student Transfers"])


@router.post("/initiate", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
def initiate_transfer(
    payload: TransferInitiateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Initiate a cross-institution/interstate student transfer request.
    Restricted to authorized institution officers (source or destination) and administrators.
    """
    return TransferService.initiate_transfer(db, payload, principal)


@router.get("", response_model=TransferListResponse)
def list_transfers(
    search: Optional[str] = Query(None, description="Search by transfer ID, student ref, apaar ID, or institution"),
    institution_id: Optional[str] = Query(None, description="Filter by institution code"),
    student_ref: Optional[str] = Query(None, description="Filter by student reference"),
    status: Optional[str] = Query(None, description="Filter by transfer status"),
    source_state: Optional[str] = Query(None, description="Filter by source state"),
    destination_state: Optional[str] = Query(None, description="Filter by destination state"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List transfer requests permitted for the authenticated principal.
    Institution officers automatically scoped to transfers involving their institution.
    """
    items, total = TransferService.list_transfers(
        db=db,
        principal=principal,
        institution_id=institution_id,
        student_ref=student_ref,
        status_filter=status,
        search=search,
        source_state=source_state,
        destination_state=destination_state,
        page=page,
        limit=limit,
    )
    return TransferListResponse(
        items=[TransferResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/student/{student_ref}", response_model=List[TransferResponse])
def get_student_transfer_history(
    student_ref: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve full transfer request history for an authorized student.
    """
    items, _ = TransferService.list_transfers(
        db=db,
        principal=principal,
        student_ref=student_ref,
        limit=100,
    )
    return [TransferResponse.model_validate(t) for t in items]


@router.get("/export-csv")
def export_transfers_csv(
    status: Optional[str] = Query(None, description="Filter by transfer status"),
    institution_id: Optional[str] = Query(None, description="Filter by institution"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export authorized transfer requests as CSV."""
    items, _ = TransferService.list_transfers(
        db=db,
        principal=principal,
        institution_id=institution_id,
        status_filter=status,
        limit=1000,
    )
    headers = [
        "Transfer ID", "Student Ref", "APAAR ID", "Student Name",
        "Source Institution", "Destination Institution", "Status",
        "Initiated At", "NOC Ref", "Remarks"
    ]
    s_refs = [t.student_ref for t in items]
    s_map = {s.student_ref: s.full_name for s in db.query(Student.student_ref, Student.full_name).filter(Student.student_ref.in_(s_refs)).all()} if s_refs else {}

    rows = [
        [
            t.id,
            t.student_ref,
            t.apaar_id or "",
            s_map.get(t.student_ref, ""),
            t.source_institution_name or t.source_institution_id,
            t.destination_institution_name or t.destination_institution_id,
            t.status,
            str(t.initiation_date or getattr(t, "created_at", "") or ""),
            t.noc_certificate_ref or "",
            getattr(t, "reviewer_notes", "") or getattr(t, "source_decision_reason", "") or "",
        ]
        for t in items
    ]
    csv_content = ExportService.generate_csv(headers, rows)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transfers_register.csv"'},
    )


@router.get("/export-excel")
def export_transfers_excel(
    status: Optional[str] = Query(None, description="Filter by transfer status"),
    institution_id: Optional[str] = Query(None, description="Filter by institution"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export authorized transfer requests as Excel (.xlsx)."""
    items, _ = TransferService.list_transfers(
        db=db,
        principal=principal,
        institution_id=institution_id,
        status_filter=status,
        limit=1000,
    )
    headers = [
        "Transfer ID", "Student Ref", "APAAR ID", "Student Name",
        "Source Institution", "Destination Institution", "Status",
        "Initiated At", "NOC Ref", "Remarks"
    ]
    s_refs = [t.student_ref for t in items]
    s_map = {s.student_ref: s.full_name for s in db.query(Student.student_ref, Student.full_name).filter(Student.student_ref.in_(s_refs)).all()} if s_refs else {}

    rows = [
        [
            t.id,
            t.student_ref,
            t.apaar_id or "",
            s_map.get(t.student_ref, ""),
            t.source_institution_name or t.source_institution_id,
            t.destination_institution_name or t.destination_institution_id,
            t.status,
            str(t.initiation_date or getattr(t, "created_at", "") or ""),
            t.noc_certificate_ref or "",
            getattr(t, "reviewer_notes", "") or getattr(t, "source_decision_reason", "") or "",
        ]
        for t in items
    ]
    xlsx_content = ExportService.generate_excel("Transfers", headers, rows)
    return Response(
        content=xlsx_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="transfers_register.xlsx"'},
    )


@router.get("/{transfer_id}", response_model=TransferResponse)
def get_transfer_detail(
    transfer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve single transfer request by ID.
    Enforces institutional tenant isolation.
    """
    transfer = TransferService.get_transfer(db, transfer_id, principal)
    return TransferResponse.model_validate(transfer)


@router.get("/{transfer_id}/bond-effect-certificate")
def get_transfer_bond_effect_certificate(
    transfer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download official Bond Effect Certificate for a transfer request.
    Verifies institutional tenancy and access control.
    """
    transfer = TransferService.get_transfer(db, transfer_id, principal)
    student = db.query(Student).filter(Student.student_ref == transfer.student_ref).first()
    profile = db.query(StudentProfile).filter(StudentProfile.student_ref == transfer.student_ref).first() if student else None

    student_data = {
        "full_name": (student.full_name if student else getattr(transfer, "student_name", "Student")),
        "student_ref": transfer.student_ref,
        "apaar_id": transfer.apaar_id or (student.apaar_id if student else "N/A"),
        "roll_number": (profile.roll_number if profile else None) or transfer.student_ref,
        "department": (profile.department if profile else None) or "Engineering",
        "programme": (transfer.programme_name or transfer.programme_id or (profile.department if profile else "Bachelor of Technology")),
        "institution_name": transfer.source_institution_id,
    }

    transfer_data = {
        "id": transfer.id,
        "source_institution_id": transfer.source_institution_id,
        "destination_institution_id": transfer.destination_institution_id,
        "status": transfer.status,
        "noc_certificate_ref": transfer.noc_certificate_ref,
    }

    inst_name = "St. Joseph's College of Engineering, Chennai" if "SJCE" in transfer.source_institution_id else transfer.source_institution_id
    pdf_bytes = PdfGeneratorService.generate_bond_effect_certificate_pdf(
        student_data=student_data,
        transfer_data=transfer_data,
        institution_name=inst_name,
    )

    AuditService.log_event(
        db=db,
        entity_type="TRANSFER_BOND_CERTIFICATE",
        entity_id=transfer_id,
        action="BOND_EFFECT_CERTIFICATE_DOWNLOAD",
        performed_by=principal.subject,
        details={"transfer_id": transfer_id, "bytes": len(pdf_bytes)},
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bond_effect_certificate_{transfer_id}.pdf"'},
    )


@router.get("/{transfer_id}/noc-download")
def get_transfer_noc_download(
    transfer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download official Transfer No Objection Certificate (NOC) and Relieving Order PDF.
    """
    transfer = TransferService.get_transfer(db, transfer_id, principal)
    student = db.query(Student).filter(Student.student_ref == transfer.student_ref).first()

    transfer_data = {
        "id": transfer.id,
        "student_name": (student.full_name if student else getattr(transfer, "student_name", "Student")),
        "student_ref": transfer.student_ref,
        "apaar_id": transfer.apaar_id or (student.apaar_id if student else "N/A"),
        "source_institution_id": transfer.source_institution_id,
        "destination_institution_id": transfer.destination_institution_id,
        "status": transfer.status,
        "noc_certificate_ref": transfer.noc_certificate_ref,
    }

    pdf_bytes = PdfGeneratorService.generate_transfer_noc_pdf(
        transfer_data=transfer_data,
        student_data={"full_name": transfer_data["student_name"], "student_ref": transfer_data["student_ref"]},
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="transfer_noc_{transfer_id}.pdf"'},
    )


@router.post("/{transfer_id}/release", response_model=TransferResponse)
def release_transfer(
    transfer_id: str,
    payload: TransferReleaseRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Source institution decision: approve release (issue NOC / update status) or reject transfer.
    Strictly restricted to source institution officers and administrators.
    """
    return TransferService.release_transfer(db, transfer_id, payload, principal)


@router.post("/{transfer_id}/admit", response_model=TransferResponse)
def admit_transfer(
    transfer_id: str,
    payload: TransferAdmitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Destination institution decision: confirm admission / matriculation or reject transfer.
    Strictly restricted to destination institution officers and administrators.
    """
    return TransferService.admit_transfer(db, transfer_id, payload, principal)


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
def cancel_transfer(
    transfer_id: str,
    payload: TransferCancelRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Cancel an uncompleted transfer request.
    """
    return TransferService.cancel_transfer(db, transfer_id, payload, principal)


@router.get("/{transfer_id}/reconcile-source")
def reconcile_transfer_source(
    transfer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Verify and reconcile transfer request against source state Higher Education portals
    (e.g., Tamil Nadu UMIS / DOTE registry).
    """
    transfer = TransferService.get_transfer(db, transfer_id, principal)
    from app.adapters.tamil_nadu_umis_adapter import tn_umis_adapter
    from app.services.state_service import StateService

    source_state = transfer.source_state or StateService.resolve_state_from_institution(transfer.source_institution_id)

    if source_state == "TAMIL_NADU":
        result = tn_umis_adapter.reconcile_transfer_source(
            transfer_id=transfer.id,
            student_ref=transfer.student_ref,
            apaar_id=transfer.apaar_id,
            source_institution_id=transfer.source_institution_id,
            noc_ref=transfer.noc_certificate_ref,
        )
    else:
        # Standard inter-state reconciliation simulation
        result = {
            "transfer_id": transfer.id,
            "student_ref": transfer.student_ref,
            "provider": f"{source_state}_HE_PORTAL",
            "provider_name": f"{source_state.title()} State Higher Education Registry",
            "is_mock": True,
            "reconciliation_status": "SOURCE_VERIFIED",
            "reconciliation_score": 98.0,
            "clearance_check": {
                "clearance_status": "CLEARED",
                "dues_outstanding_inr": 0.0,
                "verified_at": "2026-10-27T10:00:00Z",
            },
            "noc_validation": {
                "is_authentic": bool(transfer.noc_certificate_ref),
                "tc_number": transfer.noc_certificate_ref,
            },
            "recommendation": "Source records verified; proceed with transfer admission.",
        }
    return result
