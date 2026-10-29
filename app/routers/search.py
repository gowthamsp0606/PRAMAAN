from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List

from app.database import get_db
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.transfer import TransferRequest
from app.models.alert import Alert
from app.models.certificate import Certificate
from app.models.intake import ApprovedIntake
from app.security import Principal, get_current_principal, mask_identifier
from app.services.state_service import KNOWN_INSTITUTION_STATES, STATE_NAMES

router = APIRouter(prefix="/search", tags=["Global Search"])


@router.get("", response_model=Dict[str, Any])
def global_search(
    q: str = Query(..., min_length=1, description="Search term across entities"),
    type: Optional[str] = Query(None, description="Entity type: all, student, institution, transfer, alert, credential"),
    limit: int = Query(10, ge=1, le=50, description="Max results per category"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query_str = q.strip()
    term = f"%{query_str}%"
    type_filter = (type or "all").lower()

    results: Dict[str, List[Dict[str, Any]]] = {
        "students": [],
        "institutions": [],
        "transfers": [],
        "alerts": [],
        "credentials": [],
    }

    # Helper for institution IDs in a state
    def get_state_inst_ids(state_code: Optional[str]) -> List[str]:
        if not state_code:
            return []
        st_clean = state_code.upper().replace(" ", "_")
        return [inst_id for inst_id, st in KNOWN_INSTITUTION_STATES.items() if st.upper().replace(" ", "_") == st_clean]

    # -------------------------------------------------------------
    # 1. STUDENTS
    # -------------------------------------------------------------
    if type_filter in ("all", "student") and principal.role != "external_verifier":
        s_query = db.query(Student).filter(
            (Student.student_ref.ilike(term)) |
            (Student.apaar_id.ilike(term)) |
            (Student.full_name.ilike(term))
        )

        if principal.role == "student":
            s_query = s_query.filter(Student.student_ref == principal.student_ref)
        elif principal.role == "institution_officer":
            inst_stu_refs = db.query(Enrolment.student_ref).filter(
                Enrolment.institution_id == principal.institution_id
            ).distinct().scalar_subquery()
            s_query = s_query.filter(Student.student_ref.in_(inst_stu_refs))
        elif principal.role == "state_officer":
            state_inst_ids = get_state_inst_ids(principal.state)
            state_stu_refs = db.query(Enrolment.student_ref).filter(
                Enrolment.institution_id.in_(state_inst_ids)
            ).distinct().scalar_subquery()
            s_query = s_query.filter(Student.student_ref.in_(state_stu_refs))

        students = s_query.limit(limit).all()
        for s in students:
            results["students"].append({
                "id": s.student_ref,
                "category": "student",
                "title": s.full_name,
                "subtitle": f"{s.student_ref} • {s.primary_institution_id or 'Enrolled'}",
                "badge": s.identity_status,
                "deep_link": f"/students/{s.student_ref}",
                "metadata": {
                    "student_ref": s.student_ref,
                    "apaar_id": s.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(s.apaar_id),
                    "primary_institution_id": s.primary_institution_id,
                    "identity_status": s.identity_status,
                }
            })

    # -------------------------------------------------------------
    # 2. INSTITUTIONS
    # -------------------------------------------------------------
    if type_filter in ("all", "institution") and principal.role != "student":
        inst_query = db.query(
            ApprovedIntake.institution_id,
            ApprovedIntake.institution_name,
        ).distinct().filter(
            (ApprovedIntake.institution_id.ilike(term)) |
            (ApprovedIntake.institution_name.ilike(term))
        )

        if principal.role == "state_officer":
            state_inst_ids = get_state_inst_ids(principal.state)
            inst_query = inst_query.filter(ApprovedIntake.institution_id.in_(state_inst_ids))

        inst_rows = inst_query.limit(limit).all()
        for inst_id, inst_name in inst_rows:
            st = KNOWN_INSTITUTION_STATES.get(inst_id, "All-India")
            st_label = STATE_NAMES.get(st, st.replace("_", " ").title())
            results["institutions"].append({
                "id": inst_id,
                "category": "institution",
                "title": inst_name,
                "subtitle": f"{inst_id} • {st_label}",
                "badge": st_label,
                "deep_link": f"/institutions/{inst_id}",
                "metadata": {
                    "institution_id": inst_id,
                    "state": st,
                    "state_label": st_label,
                }
            })

    # -------------------------------------------------------------
    # 3. TRANSFERS
    # -------------------------------------------------------------
    if type_filter in ("all", "transfer") and principal.role != "external_verifier":
        t_query = db.query(TransferRequest).filter(
            (TransferRequest.id.ilike(term)) |
            (TransferRequest.student_ref.ilike(term)) |
            (TransferRequest.apaar_id.ilike(term)) |
            (TransferRequest.source_institution_name.ilike(term)) |
            (TransferRequest.destination_institution_name.ilike(term)) |
            (TransferRequest.programme_name.ilike(term))
        )

        if principal.role == "student":
            t_query = t_query.filter(TransferRequest.student_ref == principal.student_ref)
        elif principal.role == "institution_officer":
            inst = principal.institution_id
            t_query = t_query.filter(
                (TransferRequest.source_institution_id == inst) |
                (TransferRequest.destination_institution_id == inst)
            )
        elif principal.role == "state_officer":
            st = principal.state
            t_query = t_query.filter(
                (TransferRequest.source_state == st) |
                (TransferRequest.destination_state == st)
            )

        transfers = t_query.order_by(TransferRequest.created_at.desc()).limit(limit).all()
        for t in transfers:
            results["transfers"].append({
                "id": t.id,
                "category": "transfer",
                "title": f"{t.student_ref}: {t.source_institution_name or t.source_institution_id} → {t.destination_institution_name or t.destination_institution_id}",
                "subtitle": f"{t.programme_name or t.programme_id} • {t.academic_year}",
                "badge": t.status,
                "deep_link": f"/transfers?id={t.id}",
                "metadata": {
                    "transfer_id": t.id,
                    "student_ref": t.student_ref,
                    "source_institution_id": t.source_institution_id,
                    "destination_institution_id": t.destination_institution_id,
                    "status": t.status,
                }
            })

    # -------------------------------------------------------------
    # 4. ALERTS / COMPLIANCE SIGNALS
    # -------------------------------------------------------------
    if type_filter in ("all", "alert") and principal.role not in ("student", "external_verifier"):
        a_query = db.query(Alert).filter(
            (Alert.id.ilike(term)) |
            (Alert.student_ref.ilike(term)) |
            (Alert.apaar_id.ilike(term)) |
            (Alert.title.ilike(term)) |
            (Alert.alert_type.ilike(term))
        )

        if principal.role == "institution_officer":
            inst_stu_refs = db.query(Enrolment.student_ref).filter(
                Enrolment.institution_id == principal.institution_id
            ).distinct().scalar_subquery()
            a_query = a_query.filter(Alert.student_ref.in_(inst_stu_refs))
        elif principal.role == "state_officer":
            state_inst_ids = get_state_inst_ids(principal.state)
            state_stu_refs = db.query(Enrolment.student_ref).filter(
                Enrolment.institution_id.in_(state_inst_ids)
            ).distinct().scalar_subquery()
            a_query = a_query.filter(Alert.student_ref.in_(state_stu_refs))

        alerts = a_query.order_by(Alert.created_at.desc()).limit(limit).all()
        for a in alerts:
            results["alerts"].append({
                "id": a.id,
                "category": "alert",
                "title": a.title,
                "subtitle": f"{a.student_ref} • {a.alert_type.replace('_', ' ')}",
                "badge": a.severity,
                "deep_link": f"/alerts?id={a.id}",
                "metadata": {
                    "alert_id": a.id,
                    "student_ref": a.student_ref,
                    "severity": a.severity,
                    "status": a.status,
                }
            })

    # -------------------------------------------------------------
    # 5. CREDENTIALS
    # -------------------------------------------------------------
    if type_filter in ("all", "credential"):
        c_query = db.query(Certificate).filter(
            (Certificate.certificate_id.ilike(term)) |
            (Certificate.student_ref.ilike(term)) |
            (Certificate.student_name.ilike(term)) |
            (Certificate.institution_name.ilike(term)) |
            (Certificate.programme_name.ilike(term))
        )

        if principal.role == "student":
            c_query = c_query.filter(Certificate.student_ref == principal.student_ref)
        elif principal.role == "institution_officer":
            c_query = c_query.filter(Certificate.institution_id == principal.institution_id)
        elif principal.role == "external_verifier":
            # DPDP Act 2023 Consent Gate: Verifier can only discover credentials of candidates with ACTIVE EMPLOYMENT_VERIFICATION consent
            from app.models.consent import StudentConsent
            active_consent_subq = db.query(StudentConsent.student_ref).filter(
                StudentConsent.purpose == "EMPLOYMENT_VERIFICATION",
                StudentConsent.consent_granted == True,
                StudentConsent.status == "ACTIVE",
            ).distinct().scalar_subquery()
            c_query = c_query.filter(
                Certificate.status == "VALID",
                Certificate.student_ref.in_(active_consent_subq),
            )

        certificates = c_query.limit(limit).all()
        for c in certificates:
            results["credentials"].append({
                "id": c.certificate_id,
                "category": "credential",
                "title": f"{c.programme_name} ({c.certificate_id})",
                "subtitle": f"{c.student_name} • {c.institution_name}",
                "badge": c.status,
                "deep_link": f"/credentials?id={c.certificate_id}",
                "metadata": {
                    "certificate_id": c.certificate_id,
                    "student_ref": mask_identifier(c.student_ref) if principal.role == "external_verifier" else c.student_ref,
                    "apaar_id": mask_identifier(c.apaar_id) if c.apaar_id else None,
                    "institution_id": c.institution_id,
                    "status": c.status,
                }
            })

    total_count = sum(len(items) for items in results.values())
    flat_results = []
    for cat, items in results.items():
        flat_results.extend(items)

    return {
        "query": query_str,
        "type": type_filter,
        "total": total_count,
        "categories": results,
        "flat_results": flat_results,
    }
