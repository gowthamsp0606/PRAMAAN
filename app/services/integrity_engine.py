from datetime import date, datetime
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.transfer import TransferRequest, TransferStatus
from app.config import settings

# Canonical end date assumption for ongoing active enrolment when end date is unspecified (e.g. 4-year limit or current academic window)
FAR_FUTURE_DATE = date(2099, 12, 31)
TEMPORAL_OVERLAP_RULE_ID = "TEMPORAL-OVERLAP-001"
DUPLICATE_SUBMISSION_RULE_ID = "DUPLICATE-SUBMISSION-001"
INTEGRITY_RULE_VERSION = "1.0"

def intervals_overlap(
    start1: date, end1: Optional[date], status1: str,
    start2: date, end2: Optional[date], status2: str
) -> Tuple[bool, Optional[date], Optional[date], str]:
    """
    Determines if two enrolment periods legitimately overlap temporally.
    Returns: (is_overlapping, overlap_start, overlap_end, explanation)
    """
    # Inactive enrolments that are closed do not cause active concurrent overlap
    inactive_statuses = {"completed", "withdrawn", "suspended", "cancelled"}
    
    effective_end1 = end1 if end1 is not None else (FAR_FUTURE_DATE if status1.lower() == "active" else start1)
    effective_end2 = end2 if end2 is not None else (FAR_FUTURE_DATE if status2.lower() == "active" else start2)

    if status1.lower() in inactive_statuses and end1 and end1 < start2:
        return False, None, None, f"Enrolment 1 closed on {end1} before Enrolment 2 started on {start2} (Legitimate transfer/progression)."
    if status2.lower() in inactive_statuses and end2 and end2 < start1:
        return False, None, None, f"Enrolment 2 closed on {end2} before Enrolment 1 started on {start1} (Legitimate transfer/progression)."

    # Chronological overlap test: start of each must be before or on end of other
    # interval 1 is [start1, effective_end1], interval 2 is [start2, effective_end2]
    overlap_start = max(start1, start2)
    overlap_end = min(effective_end1, effective_end2)

    if overlap_start <= overlap_end:
        # Check statuses: are BOTH records active at the same time during the overlap?
        both_active = (status1.lower() == "active" and status2.lower() == "active")
        
        if both_active:
            desc_end = "Ongoing" if overlap_end == FAR_FUTURE_DATE else str(overlap_end)
            return True, overlap_start, overlap_end, (
                f"Concurrent active enrolment detected between {overlap_start} and {desc_end}. "
                f"Both records declare 'Active' status without an intervening transfer or withdrawal."
            )
        else:
            return False, None, None, "Records overlap temporally but one or both are not concurrently Active."

    return False, None, None, "No temporal overlap between enrolment intervals."


class TemporalIntegrityEngine:
    """
    Explainable, uncertainty-aware engine for evaluating student enrolment integrity.
    Distinguishes legitimate transfers, concurrent active enrolments, and documented exceptions.
    Never marks a student as fraudulent; generates investigative signals for human review.
    """

    def __init__(self, db: Session):
        self.db = db

    def evaluate_student(self, student_ref: str) -> Dict[str, Any]:
        """
        Evaluates all enrolments for a given student_ref.
        Returns a comprehensive report and generates or updates alerts in the database.
        """
        enrolments: List[Enrolment] = self.db.query(Enrolment).filter(
            Enrolment.student_ref == student_ref
        ).order_by(Enrolment.enrolment_start.asc()).all()

        if not enrolments:
            return {
                "student_ref": student_ref,
                "status": "NO_RECORDS",
                "enrolment_count": 0,
                "alerts": [],
                "timeline": [],
                "summary": "No enrolment records found for this student reference."
            }

        apaar_id = enrolments[0].apaar_id
        timeline = []
        for e in enrolments:
            timeline.append({
                "id": e.id,
                "institution_id": e.institution_id,
                "institution_name": e.institution_name or e.institution_id,
                "programme_id": e.programme_id,
                "programme_name": e.programme_name or e.programme_id,
                "academic_year": e.academic_year,
                "admission_cycle": e.admission_cycle,
                "start": str(e.enrolment_start),
                "end": str(e.enrolment_end) if e.enrolment_end else "Ongoing (Unspecified)",
                "status": e.enrolment_status,
                "seat_category": e.seat_category,
                "exception_ref": e.exception_ref,
                "source_submission_id": e.source_submission_id,
                "version": e.record_version
            })

        # Pairwise analysis
        alerts_to_upsert: List[Dict[str, Any]] = []
        n = len(enrolments)

        for i in range(n):
            for j in range(i + 1, n):
                rec1 = enrolments[i]
                rec2 = enrolments[j]

                # Check 1: Duplicate submission check (same institution, same programme, same cycle)
                if (
                    rec1.institution_id == rec2.institution_id and
                    rec1.programme_id == rec2.programme_id and
                    rec1.academic_year == rec2.academic_year and
                    rec1.admission_cycle == rec2.admission_cycle
                ):
                    alerts_to_upsert.append({
                        "id": f"ALT-DUP-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                        "student_ref": student_ref,
                        "apaar_id": apaar_id,
                        "alert_type": "DUPLICATE_SUBMISSION",
                        "severity": "LOW",
                        "title": f"Duplicate Submission Detected: {rec1.institution_id}",
                        "explanation": (
                            f"Multiple submissions detected for the same institution ({rec1.institution_id}), "
                            f"programme ({rec1.programme_id}), and academic year ({rec1.academic_year}). "
                            f"Source submissions: {rec1.source_submission_id} (v{rec1.record_version}) and "
                            f"{rec2.source_submission_id} (v{rec2.record_version}). "
                            "This represents a repeated administrative submission rather than a concurrent enrolment."
                        ),
                        "evidence_summary": {
                            "type": "DUPLICATE_RECORD",
                            "rule_id": DUPLICATE_SUBMISSION_RULE_ID,
                            "rule_version": INTEGRITY_RULE_VERSION,
                            "severity": "LOW",
                            "recommended_action": "Compare source submissions and confirm whether one administrative record should be retained.",
                            "triggered_fields": [
                                "institution_id", "programme_id", "academic_year", "admission_cycle"
                            ],
                            "record_ids": [rec1.id, rec2.id],
                            "records": [
                                {
                                    "id": rec1.id,
                                    "institution_id": rec1.institution_id,
                                    "programme_id": rec1.programme_id,
                                    "academic_year": rec1.academic_year,
                                    "admission_cycle": rec1.admission_cycle,
                                    "enrolment_start": str(rec1.enrolment_start),
                                    "enrolment_end": str(rec1.enrolment_end) if rec1.enrolment_end else None,
                                    "enrolment_status": rec1.enrolment_status,
                                },
                                {
                                    "id": rec2.id,
                                    "institution_id": rec2.institution_id,
                                    "programme_id": rec2.programme_id,
                                    "academic_year": rec2.academic_year,
                                    "admission_cycle": rec2.admission_cycle,
                                    "enrolment_start": str(rec2.enrolment_start),
                                    "enrolment_end": str(rec2.enrolment_end) if rec2.enrolment_end else None,
                                    "enrolment_status": rec2.enrolment_status,
                                },
                            ],
                            "submission_ids": [rec1.source_submission_id, rec2.source_submission_id]
                        },
                        "confidence_score": 0.99,
                        "supporting_record_ids": [rec1.id, rec2.id],
                        "exception_ref": None
                    })
                    continue

                # Check 2: Temporal overlap check
                is_overlap, o_start, o_end, detail = intervals_overlap(
                    rec1.enrolment_start, rec1.enrolment_end, rec1.enrolment_status,
                    rec2.enrolment_start, rec2.enrolment_end, rec2.enrolment_status
                )

                if is_overlap:
                    # Check 2b: Cross-institution transfer request and grace period check
                    transfer = None
                    if rec1.institution_id != rec2.institution_id:
                        transfer = self.db.query(TransferRequest).filter(
                            TransferRequest.student_ref == student_ref,
                            (
                                ((TransferRequest.source_institution_id == rec1.institution_id) & (TransferRequest.destination_institution_id == rec2.institution_id)) |
                                ((TransferRequest.source_institution_id == rec2.institution_id) & (TransferRequest.destination_institution_id == rec1.institution_id))
                            )
                        ).order_by(TransferRequest.created_at.desc()).first()

                    if transfer and transfer.status in (TransferStatus.RELEASED, TransferStatus.PENDING_ADMISSION, TransferStatus.COMPLETED):
                        overlap_days = (o_end - o_start).days if (o_end and o_end != FAR_FUTURE_DATE and o_start) else (
                            (date.today() - o_start).days if o_start else 0
                        )
                        grace_period = getattr(settings, "TRANSFER_GRACE_PERIOD_DAYS", 30)
                        if overlap_days <= grace_period:
                            alerts_to_upsert.append({
                                "id": f"ALT-TRF-GRACE-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                                "student_ref": student_ref,
                                "apaar_id": apaar_id,
                                "alert_type": "TRANSFER_GRACE_PERIOD_NOTICE",
                                "severity": "LOW",
                                "title": f"Transfer Transition Within Grace Period: {rec1.institution_id} & {rec2.institution_id}",
                                "explanation": (
                                    f"Temporary enrolment overlap of {overlap_days} days detected between {rec1.institution_name or rec1.institution_id} "
                                    f"and {rec2.institution_name or rec2.institution_id}. This is within the permitted {grace_period}-day transfer "
                                    f"grace period under Transfer Request '{transfer.id}' (Status: {transfer.status}). Legitimate migration transition."
                                ),
                                "evidence_summary": {
                                    "scenario": "TRANSFER_WITHIN_GRACE_PERIOD",
                                    "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                                    "rule_version": INTEGRITY_RULE_VERSION,
                                    "severity": "LOW",
                                    "recommended_action": "Verify source institution records final exit closure during normal reconciliation.",
                                    "transfer_id": transfer.id,
                                    "transfer_status": transfer.status,
                                    "overlap_days": overlap_days,
                                    "grace_period_days": grace_period,
                                    "overlap_period": f"{o_start} to {'Ongoing' if o_end == FAR_FUTURE_DATE else str(o_end)}",
                                },
                                "confidence_score": 0.95,
                                "supporting_record_ids": [rec1.id, rec2.id],
                                "exception_ref": f"TRF-{transfer.id}",
                            })
                            continue
                        else:
                            alerts_to_upsert.append({
                                "id": f"ALT-TRF-EXP-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                                "student_ref": student_ref,
                                "apaar_id": apaar_id,
                                "alert_type": "TRANSFER_OVERLAP_EXCEEDED_GRACE_PERIOD",
                                "severity": "MEDIUM",
                                "title": f"Transfer Overlap Exceeded Grace Period: {rec1.institution_id} & {rec2.institution_id}",
                                "explanation": (
                                    f"Active enrolment overlap between {rec1.institution_name or rec1.institution_id} and "
                                    f"{rec2.institution_name or rec2.institution_id} ({overlap_days} days) exceeds the permitted {grace_period}-day "
                                    f"transfer grace period under Transfer Request '{transfer.id}'. Source system update may be delayed or concurrent active seats persist."
                                ),
                                "evidence_summary": {
                                    "scenario": "TRANSFER_EXCEEDED_GRACE_PERIOD",
                                    "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                                    "rule_version": INTEGRITY_RULE_VERSION,
                                    "severity": "MEDIUM",
                                    "recommended_action": "Contact source institution to confirm release and exit date reconciliation.",
                                    "transfer_id": transfer.id,
                                    "transfer_status": transfer.status,
                                    "overlap_days": overlap_days,
                                    "grace_period_days": grace_period,
                                    "overlap_period": f"{o_start} to {'Ongoing' if o_end == FAR_FUTURE_DATE else str(o_end)}",
                                },
                                "confidence_score": 0.85,
                                "supporting_record_ids": [rec1.id, rec2.id],
                                "exception_ref": f"TRF-{transfer.id}",
                            })
                            continue
                    elif transfer and transfer.status == TransferStatus.PENDING_RELEASE:
                        alerts_to_upsert.append({
                            "id": f"ALT-TRF-PEND-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                            "student_ref": student_ref,
                            "apaar_id": apaar_id,
                            "alert_type": "TRANSFER_PENDING_RELEASE_REVIEW",
                            "severity": "MEDIUM",
                            "title": f"Pending Transfer Overlap: {rec1.institution_id} & {rec2.institution_id}",
                            "explanation": (
                                f"Concurrent active enrolments found while Transfer Request '{transfer.id}' is pending source release. "
                                f"Receiving institution has recorded enrolment before source institution has officially released the student."
                            ),
                            "evidence_summary": {
                                "scenario": "TRANSFER_PENDING_RELEASE",
                                "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                                "rule_version": INTEGRITY_RULE_VERSION,
                                "severity": "MEDIUM",
                                "recommended_action": "Awaiting source institution release action before completing transfer.",
                                "transfer_id": transfer.id,
                                "transfer_status": transfer.status,
                                "overlap_period": f"{o_start} to {'Ongoing' if o_end == FAR_FUTURE_DATE else str(o_end)}",
                            },
                            "confidence_score": 0.80,
                            "supporting_record_ids": [rec1.id, rec2.id],
                            "exception_ref": f"TRF-{transfer.id}",
                        })
                        continue

                    # Check 3: Is there a documented permitted exception reference?
                    has_exception = bool(rec1.exception_ref or rec2.exception_ref)
                    exc_ref = rec1.exception_ref or rec2.exception_ref

                    if has_exception:
                        # Scenario C: Documented Permitted Exception
                        alerts_to_upsert.append({
                            "id": f"ALT-EXC-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                            "student_ref": student_ref,
                            "apaar_id": apaar_id,
                            "alert_type": "EXCEPTION_REVIEW_REQUIRED",
                            "severity": "MEDIUM",
                            "title": f"Documented Exception Review: {exc_ref}",
                            "explanation": (
                                f"Concurrent active enrolments found between {rec1.institution_name or rec1.institution_id} "
                                f"and {rec2.institution_name or rec2.institution_id}, but a documented regulatory exception "
                                f"reference is attached ({exc_ref}). "
                                "Policy requires an authorised institutional officer to verify documentation "
                                "for valid dual-degree, credit-mobility, or joint academic programmes. "
                                "Case held for officer review; not automatically cleared."
                            ),
                            "evidence_summary": {
                                "scenario": "C_DOCUMENTED_EXCEPTION",
                                "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                                "rule_version": INTEGRITY_RULE_VERSION,
                                "severity": "MEDIUM",
                                "recommended_action": "Review the referenced exception evidence and verify that concurrent enrolment is permitted for this programme combination.",
                                "triggered_fields": [
                                    "institution_id", "programme_id", "enrolment_start",
                                    "enrolment_end", "enrolment_status", "exception_ref"
                                ],
                                "record_1": {
                                    "id": rec1.id, "inst": rec1.institution_id, "prog": rec1.programme_id,
                                    "start": str(rec1.enrolment_start), "status": rec1.enrolment_status
                                },
                                "record_2": {
                                    "id": rec2.id, "inst": rec2.institution_id, "prog": rec2.programme_id,
                                    "start": str(rec2.enrolment_start), "status": rec2.enrolment_status
                                },
                                "exception_ref": exc_ref,
                                "overlap_period": f"{o_start} to {'Ongoing' if o_end == FAR_FUTURE_DATE else str(o_end)}"
                            },
                            "confidence_score": 0.85,  # Needs human verification of physical certificate/decree
                            "supporting_record_ids": [rec1.id, rec2.id],
                            "exception_ref": exc_ref
                        })
                    else:
                        # Scenario B: Potential Overlapping Active Enrolment
                        # Calculate defensible certainty
                        both_missing_end = (rec1.enrolment_end is None and rec2.enrolment_end is None)
                        confidence = 0.95 if both_missing_end else 0.90
                        
                        alerts_to_upsert.append({
                            "id": f"ALT-OVL-{min(rec1.id, rec2.id)}-{max(rec1.id, rec2.id)}",
                            "student_ref": student_ref,
                            "apaar_id": apaar_id,
                            "alert_type": "TEMPORAL_OVERLAP_CONFLICT",
                            "severity": "HIGH",
                            "title": f"Potential Concurrent Active Enrolment: {rec1.institution_id} & {rec2.institution_id}",
                            "explanation": (
                                f"Active enrolment at {rec1.institution_name or rec1.institution_id} ({rec1.programme_name or rec1.programme_id}) "
                                f"starting {rec1.enrolment_start} overlaps with active enrolment at "
                                f"{rec2.institution_name or rec2.institution_id} ({rec2.programme_name or rec2.programme_id}) "
                                f"starting {rec2.enrolment_start}. Neither record reports a withdrawal or completion date. "
                                "Under standard AICTE norms, full-time undergraduate/diploma students may not hold concurrent "
                                "active regular seats without prior approval. This signal is generated for investigation."
                            ),
                            "evidence_summary": {
                                "scenario": "B_CONCURRENT_ACTIVE",
                                "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                                "rule_version": INTEGRITY_RULE_VERSION,
                                "severity": "HIGH",
                                "recommended_action": "Compare both enrolment periods and statuses, then request source documentation before deciding.",
                                "triggered_fields": [
                                    "institution_id", "programme_id", "enrolment_start",
                                    "enrolment_end", "enrolment_status"
                                ],
                                "record_1": {
                                    "id": rec1.id,
                                    "institution_id": rec1.institution_id,
                                    "institution_name": rec1.institution_name,
                                    "programme_id": rec1.programme_id,
                                    "programme_name": rec1.programme_name,
                                    "academic_year": rec1.academic_year,
                                    "enrolment_start": str(rec1.enrolment_start),
                                    "enrolment_end": str(rec1.enrolment_end) if rec1.enrolment_end else None,
                                    "enrolment_status": rec1.enrolment_status,
                                },
                                "record_2": {
                                    "id": rec2.id,
                                    "institution_id": rec2.institution_id,
                                    "institution_name": rec2.institution_name,
                                    "programme_id": rec2.programme_id,
                                    "programme_name": rec2.programme_name,
                                    "academic_year": rec2.academic_year,
                                    "enrolment_start": str(rec2.enrolment_start),
                                    "enrolment_end": str(rec2.enrolment_end) if rec2.enrolment_end else None,
                                    "enrolment_status": rec2.enrolment_status,
                                },
                                "overlap_period": f"{o_start} to {'Ongoing' if o_end == FAR_FUTURE_DATE else str(o_end)}",
                                "matched_student_ref": student_ref,
                            },
                            "confidence_score": confidence,
                            "supporting_record_ids": [rec1.id, rec2.id],
                            "exception_ref": None
                        })

        # Save or update alerts idempotently (preserve reviewer decisions if already reviewed!)
        generated_alerts = []
        for a_data in alerts_to_upsert:
            existing = self.db.query(Alert).filter(Alert.id == a_data["id"]).first()
            if existing:
                # Do not overwrite reviewer decision if already made!
                existing.title = a_data["title"]
                existing.explanation = a_data["explanation"]
                existing.evidence_summary = a_data["evidence_summary"]
                existing.supporting_record_ids = a_data["supporting_record_ids"]
                generated_alerts.append(existing)
            else:
                new_alert = Alert(
                    id=a_data["id"],
                    student_ref=a_data["student_ref"],
                    apaar_id=a_data["apaar_id"],
                    alert_type=a_data["alert_type"],
                    severity=a_data["severity"],
                    status="OPEN",
                    title=a_data["title"],
                    explanation=a_data["explanation"],
                    evidence_summary=a_data["evidence_summary"],
                    confidence_score=a_data["confidence_score"],
                    supporting_record_ids=a_data["supporting_record_ids"],
                    exception_ref=a_data["exception_ref"]
                )
                self.db.add(new_alert)
                generated_alerts.append(new_alert)

        self.db.commit()

        # Generate scenario conclusion
        if not alerts_to_upsert:
            status = "COMPLIANT_TRANSFER" if len(enrolments) > 1 else "SINGLE_ENROLMENT_OK"
            summary = (
                "All enrolment records are chronologically sequential with proper completion/withdrawal status. "
                "Legitimate transfer or progression verified with zero temporal conflict."
                if len(enrolments) > 1 else "Single regular enrolment record without temporal conflict."
            )
        else:
            has_high = any(a["severity"] == "HIGH" for a in alerts_to_upsert)
            status = "REQUIRES_INVESTIGATION" if has_high else "EXCEPTION_REVIEW"
            summary = f"{len(alerts_to_upsert)} potential integrity signal(s) require officer attention."

        return {
            "student_ref": student_ref,
            "apaar_id": apaar_id,
            "status": status,
            "enrolment_count": len(enrolments),
            "timeline": timeline,
            "alerts": [
                {
                    "id": a.id if isinstance(a, Alert) else a["id"],
                    "alert_type": a.alert_type if isinstance(a, Alert) else a["alert_type"],
                    "severity": a.severity if isinstance(a, Alert) else a["severity"],
                    "status": a.status if isinstance(a, Alert) else "OPEN",
                    "title": a.title if isinstance(a, Alert) else a["title"],
                    "explanation": a.explanation if isinstance(a, Alert) else a["explanation"],
                    "evidence_summary": a.evidence_summary if isinstance(a, Alert) else a.get("evidence_summary"),
                    "confidence_score": a.confidence_score if isinstance(a, Alert) else a.get("confidence_score"),
                    "reviewer_decision": getattr(a, "reviewer_decision", None),
                    "reviewer_note": getattr(a, "reviewer_note", None)
                }
                for a in generated_alerts
            ],
            "summary": summary
        }

    def evaluate_all(self) -> int:
        """Evaluates all students in the database and generates alerts."""
        students = self.db.query(Enrolment.student_ref).distinct().all()
        count = 0
        for (s_ref,) in students:
            self.evaluate_student(s_ref)
            count += 1
        return count
