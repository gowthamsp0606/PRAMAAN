import uuid
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.transfer import TransferRequest, TransferStatus
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.versioning import EnrolmentVersion
from app.schemas.transfer import (
    TransferInitiateRequest,
    TransferReleaseRequest,
    TransferAdmitRequest,
    TransferCancelRequest,
)
from app.security import Principal
from app.services.audit_service import AuditService


class TransferService:
    @staticmethod
    def initiate_transfer(
        db: Session,
        payload: TransferInitiateRequest,
        principal: Principal,
    ) -> TransferRequest:
        # 1. Verify student exists
        student = db.query(Student).filter(Student.student_ref == payload.student_ref).first()
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student record '{payload.student_ref}' not found.",
            )

        # 2. Determine and validate source institution
        source_inst = payload.source_institution_id
        if principal.role == "institution_officer":
            # If not provided, default to officer's assigned institution
            if not source_inst:
                source_inst = principal.institution_id
            # Officer must be affiliated with source OR destination
            if source_inst != principal.institution_id and payload.destination_institution_id != principal.institution_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Institution officers can only initiate transfers involving their assigned institution.",
                )

        if not source_inst:
            # Fallback to student's primary institution
            source_inst = student.primary_institution_id

        if not source_inst:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source institution must be specified.",
            )

        if source_inst == payload.destination_institution_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and destination institutions cannot be identical.",
            )

        # 3. Check for existing active transfer request for this student
        existing_active = db.query(TransferRequest).filter(
            TransferRequest.student_ref == payload.student_ref,
            TransferRequest.status.in_([
                TransferStatus.PENDING_RELEASE,
                TransferStatus.RELEASED,
                TransferStatus.PENDING_ADMISSION,
                TransferStatus.UNDER_REVIEW,
            ]),
        ).first()
        if existing_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active transfer request already exists for student '{payload.student_ref}' (Transfer ID: {existing_active.id}).",
            )

        # 4. Check for active source enrolment
        source_enrolment = db.query(Enrolment).filter(
            Enrolment.student_ref == payload.student_ref,
            Enrolment.institution_id == source_inst,
            Enrolment.enrolment_status == "Active",
        ).order_by(Enrolment.id.desc()).first()

        effective_date_val = payload.requested_effective_date or getattr(payload, 'effective_date', None) or date.today()
        reviewer_notes_val = payload.transfer_reason or getattr(payload, 'reason', None)

        transfer_id = f"TRF-{uuid.uuid4().hex[:10].upper()}"
        new_transfer = TransferRequest(
            id=transfer_id,
            student_ref=payload.student_ref,
            apaar_id=student.apaar_id,
            source_institution_id=source_inst,
            source_institution_name=payload.source_institution_name or source_inst,
            destination_institution_id=payload.destination_institution_id,
            destination_institution_name=payload.destination_institution_name or payload.destination_institution_id,
            source_state=payload.source_state,
            destination_state=payload.destination_state,
            source_enrolment_id=source_enrolment.id if source_enrolment else None,
            programme_id=payload.programme_id,
            programme_name=payload.programme_name or payload.programme_id,
            academic_year=payload.academic_year,
            initiation_date=date.today(),
            requested_effective_date=effective_date_val,
            status=TransferStatus.PENDING_RELEASE,
            reviewer_notes=reviewer_notes_val,
            created_by=principal.subject,
        )

        db.add(new_transfer)
        db.flush()

        AuditService.log_event(
            db=db,
            entity_type="TRANSFER",
            entity_id=transfer_id,
            action="TRANSFER_INITIATED",
            performed_by=principal.subject,
            details={
                "student_ref": payload.student_ref,
                "source_institution": source_inst,
                "destination_institution": payload.destination_institution_id,
                "programme_id": payload.programme_id,
                "academic_year": payload.academic_year,
                "effective_date": str(effective_date_val),
            },
        )
        db.commit()
        db.refresh(new_transfer)
        return new_transfer

    @staticmethod
    def release_transfer(
        db: Session,
        transfer_id: str,
        payload: TransferReleaseRequest,
        principal: Principal,
    ) -> TransferRequest:
        transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
        if not transfer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transfer request '{transfer_id}' not found.")

        # Institutional authorization: Only source institution officer or administrator can release
        if principal.role == "institution_officer" and principal.institution_id != transfer.source_institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only the source institution ('{transfer.source_institution_id}') can decide release of a student.",
            )

        # State transition validation
        if transfer.status in {TransferStatus.COMPLETED, TransferStatus.REJECTED, TransferStatus.CANCELLED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot release transfer in terminal status '{transfer.status}'.",
            )
        if transfer.status in {TransferStatus.RELEASED, TransferStatus.PENDING_ADMISSION}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transfer has already been approved for release.",
            )

        now = datetime.utcnow()
        if payload.action in ("APPROVE", "RELEASE"):
            transfer.status = TransferStatus.RELEASED
            transfer.source_decision = "APPROVED"
            transfer.source_decision_at = now
            transfer.source_decision_by = principal.subject
            transfer.source_decision_reason = payload.reason or "Release and migration NOC approved."
            transfer.noc_certificate_ref = payload.noc_certificate_ref or getattr(payload, 'noc_document_ref', None) or f"NOC-{transfer.source_institution_id}-{transfer.id[-6:]}"

            # Update source enrolment to Withdrawn / Transferred
            source_enrolment = None
            if transfer.source_enrolment_id:
                source_enrolment = db.query(Enrolment).filter(Enrolment.id == transfer.source_enrolment_id).first()
            if not source_enrolment:
                source_enrolment = db.query(Enrolment).filter(
                    Enrolment.student_ref == transfer.student_ref,
                    Enrolment.institution_id == transfer.source_institution_id,
                    Enrolment.enrolment_status == "Active",
                ).order_by(Enrolment.id.desc()).first()

            if source_enrolment and source_enrolment.enrolment_status == "Active":
                source_enrolment.enrolment_status = "Withdrawn"
                source_enrolment.enrolment_end = transfer.requested_effective_date
                source_enrolment.record_version += 1
                db.flush()

                # Add version tracking record
                db.add(EnrolmentVersion(
                    enrolment_id=source_enrolment.id,
                    student_ref=source_enrolment.student_ref,
                    version_number=source_enrolment.record_version,
                    institution_id=source_enrolment.institution_id,
                    programme_id=source_enrolment.programme_id,
                    enrolment_status=source_enrolment.enrolment_status,
                    academic_year=source_enrolment.academic_year,
                    changed_by=principal.subject,
                    change_reason=f"Transfer release to {transfer.destination_institution_id} ({transfer.id})",
                    diff_payload={
                        "transfer_id": transfer.id,
                        "noc_ref": transfer.noc_certificate_ref,
                        "effective_date": str(transfer.requested_effective_date),
                    },
                ))

            AuditService.log_event(
                db=db,
                entity_type="TRANSFER",
                entity_id=transfer.id,
                action="TRANSFER_RELEASE_APPROVED",
                performed_by=principal.subject,
                details={
                    "noc_ref": transfer.noc_certificate_ref,
                    "reason": transfer.source_decision_reason,
                    "effective_date": str(transfer.requested_effective_date),
                },
            )
        else:
            # REJECT
            transfer.status = TransferStatus.REJECTED
            transfer.source_decision = "REJECTED"
            transfer.source_decision_at = now
            transfer.source_decision_by = principal.subject
            transfer.source_decision_reason = payload.reason or "Release request rejected by source institution."

            AuditService.log_event(
                db=db,
                entity_type="TRANSFER",
                entity_id=transfer.id,
                action="TRANSFER_RELEASE_REJECTED",
                performed_by=principal.subject,
                details={"reason": transfer.source_decision_reason},
            )

        transfer.record_version += 1
        transfer.updated_at = now
        db.commit()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def admit_transfer(
        db: Session,
        transfer_id: str,
        payload: TransferAdmitRequest,
        principal: Principal,
    ) -> TransferRequest:
        transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
        if not transfer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transfer request '{transfer_id}' not found.")

        # Institutional authorization: Only destination institution officer or administrator can confirm admission
        if principal.role == "institution_officer" and principal.institution_id != transfer.destination_institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only the destination institution ('{transfer.destination_institution_id}') can admit a transferred student.",
            )

        # State transition validation
        if transfer.status == TransferStatus.PENDING_RELEASE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transfer cannot be admitted before being released by the source institution (current status: {transfer.status}).",
            )
        if transfer.status == TransferStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transfer has already been completed.",
            )
        if transfer.status in {TransferStatus.REJECTED, TransferStatus.CANCELLED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot admit transfer in terminal status '{transfer.status}'.",
            )

        now = datetime.utcnow()
        if payload.action == "ADMIT":
            transfer.status = TransferStatus.COMPLETED
            transfer.destination_decision = "ADMITTED"
            transfer.destination_decision_at = now
            transfer.destination_decision_by = principal.subject
            transfer.destination_decision_reason = payload.reason or "Matriculation and credit acceptance confirmed."

            # Check if active enrolment already exists at destination (prevent duplicate active enrolments)
            dest_enrolment = db.query(Enrolment).filter(
                Enrolment.student_ref == transfer.student_ref,
                Enrolment.institution_id == transfer.destination_institution_id,
                Enrolment.programme_id == transfer.programme_id,
                Enrolment.enrolment_status == "Active",
            ).first()

            if not dest_enrolment:
                # Create destination enrolment
                dest_enrolment = Enrolment(
                    student_ref=transfer.student_ref,
                    apaar_id=transfer.apaar_id,
                    institution_id=transfer.destination_institution_id,
                    institution_name=transfer.destination_institution_name or transfer.destination_institution_id,
                    programme_id=transfer.programme_id,
                    programme_name=transfer.programme_name or transfer.programme_id,
                    academic_year=transfer.academic_year,
                    admission_cycle="Transfer In-Year",
                    enrolment_start=transfer.requested_effective_date,
                    enrolment_end=None,
                    enrolment_status="Active",
                    seat_category=payload.seat_category or "General",
                    exception_ref=f"TRF-{transfer.id}",
                    source_submission_id=f"TRANSFER-MATRICULATION-{transfer.id}",
                    record_version=1,
                )
                db.add(dest_enrolment)
                db.flush()

                # Record version 1 in EnrolmentVersion
                db.add(EnrolmentVersion(
                    enrolment_id=dest_enrolment.id,
                    student_ref=dest_enrolment.student_ref,
                    version_number=1,
                    institution_id=dest_enrolment.institution_id,
                    programme_id=dest_enrolment.programme_id,
                    enrolment_status=dest_enrolment.enrolment_status,
                    academic_year=dest_enrolment.academic_year,
                    changed_by=principal.subject,
                    change_reason=f"Transfer matriculation from {transfer.source_institution_id} ({transfer.id})",
                    diff_payload={
                        "transfer_id": transfer.id,
                        "source_institution_id": transfer.source_institution_id,
                        "effective_date": str(transfer.requested_effective_date),
                    },
                ))

            # Update student primary institution to destination
            student = db.query(Student).filter(Student.student_ref == transfer.student_ref).first()
            if student:
                student.primary_institution_id = transfer.destination_institution_id
                student.updated_at = now

            AuditService.log_event(
                db=db,
                entity_type="TRANSFER",
                entity_id=transfer.id,
                action="TRANSFER_ADMISSION_CONFIRMED",
                performed_by=principal.subject,
                details={
                    "enrolment_id": dest_enrolment.id,
                    "reason": transfer.destination_decision_reason,
                    "effective_date": str(transfer.requested_effective_date),
                },
            )
        else:
            # REJECT
            transfer.status = TransferStatus.REJECTED
            transfer.destination_decision = "REJECTED"
            transfer.destination_decision_at = now
            transfer.destination_decision_by = principal.subject
            transfer.destination_decision_reason = payload.reason or "Admission rejected by receiving institution."

            AuditService.log_event(
                db=db,
                entity_type="TRANSFER",
                entity_id=transfer.id,
                action="TRANSFER_ADMISSION_REJECTED",
                performed_by=principal.subject,
                details={"reason": transfer.destination_decision_reason},
            )

        transfer.record_version += 1
        transfer.updated_at = now
        db.commit()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def cancel_transfer(
        db: Session,
        transfer_id: str,
        payload: TransferCancelRequest,
        principal: Principal,
    ) -> TransferRequest:
        transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
        if not transfer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transfer request '{transfer_id}' not found.")

        # Authorization: source officer, destination officer, or admin
        if principal.role == "institution_officer":
            if principal.institution_id not in {transfer.source_institution_id, transfer.destination_institution_id}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only affiliated institutions can cancel a transfer request.",
                )

        if transfer.status in {TransferStatus.COMPLETED, TransferStatus.CANCELLED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel transfer in status '{transfer.status}'.",
            )

        transfer.status = TransferStatus.CANCELLED
        transfer.reviewer_notes = (transfer.reviewer_notes or "") + f"\nCancelled: {payload.reason or 'User requested cancellation.'}"
        transfer.updated_at = datetime.utcnow()
        transfer.record_version += 1

        AuditService.log_event(
            db=db,
            entity_type="TRANSFER",
            entity_id=transfer.id,
            action="TRANSFER_CANCELLED",
            performed_by=principal.subject,
            details={"reason": payload.reason},
        )
        db.commit()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def list_transfers(
        db: Session,
        principal: Principal,
        institution_id: Optional[str] = None,
        student_ref: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        source_state: Optional[str] = None,
        destination_state: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[TransferRequest], int]:
        query = db.query(TransferRequest)

        # Scoping based on Role
        if principal.role == "student":
            query = query.filter(TransferRequest.student_ref == principal.student_ref)
        elif principal.role == "institution_officer":
            inst = principal.institution_id
            query = query.filter(
                (TransferRequest.source_institution_id == inst) |
                (TransferRequest.destination_institution_id == inst)
            )
        elif principal.role == "state_officer":
            st = principal.state
            query = query.filter(
                (TransferRequest.source_state == st) |
                (TransferRequest.destination_state == st)
            )
        elif institution_id:
            query = query.filter(
                (TransferRequest.source_institution_id == institution_id) |
                (TransferRequest.destination_institution_id == institution_id)
            )

        if student_ref:
            query = query.filter(TransferRequest.student_ref == student_ref)
        if status_filter:
            query = query.filter(TransferRequest.status == status_filter)
        if source_state:
            query = query.filter(TransferRequest.source_state == source_state)
        if destination_state:
            query = query.filter(TransferRequest.destination_state == destination_state)
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                (TransferRequest.id.ilike(s)) |
                (TransferRequest.student_ref.ilike(s)) |
                (TransferRequest.apaar_id.ilike(s)) |
                (TransferRequest.source_institution_name.ilike(s)) |
                (TransferRequest.destination_institution_name.ilike(s)) |
                (TransferRequest.programme_name.ilike(s))
            )

        total = query.count()
        offset = (page - 1) * limit
        items = query.order_by(TransferRequest.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    @staticmethod
    def get_transfer(
        db: Session,
        transfer_id: str,
        principal: Principal,
    ) -> TransferRequest:
        transfer = db.query(TransferRequest).filter(TransferRequest.id == transfer_id).first()
        if not transfer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transfer request '{transfer_id}' not found.")

        # Scoping
        if principal.role == "institution_officer":
            if principal.institution_id not in {transfer.source_institution_id, transfer.destination_institution_id}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-institution transfer access is not permitted.",
                )
        return transfer
