from fastapi import APIRouter, Depends, HTTPException, Body, status, Response
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.certificate import Certificate
from app.services.certificate_service import CertificateService
from app.services.audit_service import AuditService
from app.services.pdf_generator import PdfGeneratorService
from app.security import Principal, get_current_principal, enforce_institution_scope, mask_identifier
from app.rate_limiter import rate_limit_credential_issuance

router = APIRouter(prefix="/certificates", tags=["Certificate Verification"])


class CredentialIssueRequest(BaseModel):
    student_ref: str
    student_name: str
    institution_id: str
    institution_name: str
    programme_id: str
    programme_name: str
    issue_date: str
    completion_date: str
    apaar_id: Optional[str] = None
    algorithm: Optional[str] = "Ed25519"


class CredentialRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Substantive institutional revocation reason")


@router.get("/public-keys")
def list_public_keys():
    """Returns the registry of active and deprecated public keys for offline signature verification."""
    return {"keys": CertificateService.get_public_keys()}


@router.get("/public-keys/{key_id}")
def get_public_key(key_id: str):
    key = CertificateService.get_public_key(key_id)
    if not key:
        raise HTTPException(status_code=404, detail=f"Public key {key_id} not found in Sentinel key registry.")
    return key


@router.get("/my-certificates")
def get_my_certificates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """List certificates belonging to the current caller (student or institution)."""
    from app.models.student import Student
    query = db.query(Certificate)
    if principal.role == "student":
        student = db.query(Student).filter(Student.student_ref == principal.student_ref).first() if principal.student_ref else None
        if student:
            query = query.filter(Certificate.student_ref == student.student_ref)
        else:
            return []
    elif principal.role == "institution_officer":
        query = query.filter(Certificate.institution_id == principal.institution_id)
    return query.all()


@router.get("")
def list_certificates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Certificate)
    if principal.role == "institution_officer":
        query = query.filter(Certificate.institution_id == principal.institution_id)
    certs = query.all()
    return {
        "items": [
            {
                "certificate_id": c.certificate_id,
                "student_ref": c.student_ref,
                "apaar_id": c.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(c.apaar_id),
                "student_name": c.student_name,
                "institution_name": c.institution_name,
                "programme_name": c.programme_name,
                "issue_date": c.issue_date,
                "status": c.status,
                "signature_algorithm": c.signature_algorithm,
                "public_key_id": c.public_key_id,
            }
            for c in certs
        ]
    }


@router.post("/issue", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit_credential_issuance)])
def issue_certificate(
    payload: CredentialIssueRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer":
        enforce_institution_scope(principal, payload.institution_id)
    elif principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(status_code=403, detail="Your role is not authorized to issue academic credentials.")

    issued_by = principal.subject if principal.subject != "local-prototype" else "Institutional Registrar (Demo)"
    cert = CertificateService.issue_credential(
        db=db,
        student_ref=payload.student_ref,
        student_name=payload.student_name,
        institution_id=payload.institution_id,
        institution_name=payload.institution_name,
        programme_id=payload.programme_id,
        programme_name=payload.programme_name,
        issue_date=payload.issue_date,
        completion_date=payload.completion_date,
        apaar_id=payload.apaar_id,
        algorithm=payload.algorithm or "Ed25519",
        issued_by=issued_by,
    )
    return {
        "success": True,
        "certificate_id": cert.certificate_id,
        "status": cert.status,
        "signature_algorithm": cert.signature_algorithm,
        "public_key_id": cert.public_key_id,
        "signature_hex": cert.signature_hex,
        "message": "Academic digital credential successfully issued and signed.",
    }


@router.post("/{certificate_id}/revoke")
def revoke_certificate(
    certificate_id: str,
    payload: CredentialRevokeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found.")

    if principal.role == "institution_officer":
        enforce_institution_scope(principal, cert.institution_id)
    elif principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(status_code=403, detail="Your role is not authorized to revoke credentials.")

    revoked_by = principal.subject if principal.subject != "local-prototype" else "Registrar / Compliance Officer"
    try:
        return CertificateService.revoke_credential(
            db=db,
            certificate_id=certificate_id,
            reason=payload.reason,
            revoked_by=revoked_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{certificate_id}")
def get_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    if principal.role == "institution_officer" and cert.institution_id != principal.institution_id:
        raise HTTPException(status_code=404, detail="Certificate not found.")

    payload = dict(cert.payload_json)
    signature_hex = cert.signature_hex
    apaar_id = cert.apaar_id
    if principal.role not in {"administrator", "prototype_admin"}:
        apaar_id = mask_identifier(apaar_id)
        if "apaar_id" in payload:
            payload["apaar_id"] = mask_identifier(str(payload["apaar_id"]))
        signature_hex = None

    return {
        "certificate_id": cert.certificate_id,
        "student_ref": cert.student_ref,
        "apaar_id": apaar_id,
        "student_name": cert.student_name,
        "institution_id": cert.institution_id,
        "institution_name": cert.institution_name,
        "programme_id": cert.programme_id,
        "programme_name": cert.programme_name,
        "completion_date": cert.completion_date,
        "issue_date": cert.issue_date,
        "status": cert.status,
        "revocation_reason": cert.revocation_reason,
        "signature_algorithm": cert.signature_algorithm,
        "signature_hex": signature_hex,
        "public_key_id": cert.public_key_id,
        "payload": payload,
        "watermark": "DEMO — NOT AN OFFICIAL CERTIFICATE"
    }


@router.get("/{certificate_id}/verify")
def verify_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    certificate = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
    if certificate and principal.role == "institution_officer" and certificate.institution_id != principal.institution_id:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    result = CertificateService.verify_certificate(db, certificate_id)
    AuditService.log_event(
        db=db,
        entity_type="CERTIFICATE",
        entity_id=certificate_id,
        action="VERIFICATION_CHECK",
        performed_by="Public Verification Portal (Demo)",
        details={"status": result.get("verification_status"), "is_authentic": result.get("is_authentic")}
    )
    if principal.role not in {"administrator", "prototype_admin"}:
        result["apaar_id"] = mask_identifier(result.get("apaar_id"))
        result["signature_hex"] = None
    return result


@router.post("/{certificate_id}/simulate-tamper")
def simulate_tampered_verification(
    certificate_id: str,
    tampered_field: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Demonstrates tamper rejection by altering payload attributes (e.g. changing student name or completion date)
    in an isolated in-memory copy without mutating the database record.
    """
    cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    if principal.role == "institution_officer" and cert.institution_id != principal.institution_id:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    if principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(status_code=403, detail="Your role is not authorized to execute tamper simulation testbeds.")

    # Create modified clone of payload in memory (NON-DESTRUCTIVE ISOLATED COPY)
    original_payload = dict(cert.payload_json)
    tampered_payload = dict(cert.payload_json)
    tampered_payload.update(tampered_field)

    result = CertificateService.verify_certificate(db, certificate_id, tampered_payload=tampered_payload)

    AuditService.log_event(
        db=db,
        entity_type="CERTIFICATE",
        entity_id=certificate_id,
        action="TAMPER_SIMULATION_TEST",
        performed_by=principal.subject if principal.subject != "local-prototype" else "Tamper Testbed Operator",
        details={
            "altered_fields": list(tampered_field.keys()),
            "result_status": result.get("verification_status"),
            "database_modified": False,
        }
    )

    if principal.role not in {"administrator", "prototype_admin"}:
        if "apaar_id" in original_payload:
            original_payload["apaar_id"] = mask_identifier(str(original_payload["apaar_id"]))
        if "apaar_id" in tampered_payload:
            tampered_payload["apaar_id"] = mask_identifier(str(tampered_payload["apaar_id"]))
        result["apaar_id"] = mask_identifier(result.get("apaar_id"))
        result["signature_hex"] = None

    return {
        "original_payload": original_payload,
        "tampered_payload": tampered_payload,
        "verification_result": result,
        "database_mutated": False,
        "isolation_mode": "IN_MEMORY_DISPOSABLE_CLONE",
    }


@router.get("/{certificate_id}/download")
def download_certificate_pdf(
    certificate_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download official Ed25519-signed digital academic credential as a PDF document.
    Enforces role authorization, institution tenancy, and student ownership.
    """
    cert = db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found.")

    if principal.role == "institution_officer" and cert.institution_id != principal.institution_id:
        raise HTTPException(status_code=404, detail="Certificate not found.")

    if principal.role == "student" and principal.student_ref and cert.student_ref != principal.student_ref:
        raise HTTPException(status_code=403, detail="You are not authorized to download this certificate.")

    cert_dict = {
        "certificate_id": cert.certificate_id,
        "student_ref": cert.student_ref,
        "student_name": cert.student_name,
        "apaar_id": cert.apaar_id or "N/A",
        "institution_id": cert.institution_id,
        "institution_name": cert.institution_name,
        "programme_name": cert.programme_name,
        "completion_date": cert.completion_date,
        "issue_date": cert.issue_date,
        "status": cert.status,
        "signature_algorithm": cert.signature_algorithm,
        "public_key_id": cert.public_key_id,
        "signature_hex": cert.signature_hex,
    }

    pdf_bytes = PdfGeneratorService.generate_certificate_pdf(
        certificate_data=cert_dict,
        institution_name=cert.institution_name,
    )

    AuditService.log_event(
        db=db,
        entity_type="CERTIFICATE",
        entity_id=certificate_id,
        action="CERTIFICATE_DOWNLOAD",
        performed_by=principal.subject,
        details={"format": "PDF", "bytes": len(pdf_bytes)},
    )

    filename = f"certificate_{certificate_id.replace('/', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )
