from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob, ImportRowResult
from app.models.review_event import AlertReviewEvent
from app.services.intake_service import IntakeComplianceService


class ReportsService:
    def __init__(self, db: Session):
        self.db = db

    def generate_executive_reports(
        self,
        *,
        institution_id: Optional[str] = None,
        programme_id: Optional[str] = None,
        academic_year: Optional[str] = None,
        admission_cycle: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is not None:
            now = now.astimezone(timezone.utc).replace(tzinfo=None)
        lower_bound = datetime.combine(start_date, datetime.min.time()) if start_date else None
        upper_bound = datetime.combine(end_date, datetime.max.time()) if end_date else None

        enrolment_query = self.db.query(Enrolment)
        if institution_id:
            enrolment_query = enrolment_query.filter(Enrolment.institution_id == institution_id)
        if programme_id:
            enrolment_query = enrolment_query.filter(Enrolment.programme_id == programme_id)
        if academic_year:
            enrolment_query = enrolment_query.filter(Enrolment.academic_year == academic_year)
        if admission_cycle:
            enrolment_query = enrolment_query.filter(Enrolment.admission_cycle == admission_cycle)
        if lower_bound:
            enrolment_query = enrolment_query.filter(Enrolment.created_at >= lower_bound)
        if upper_bound:
            enrolment_query = enrolment_query.filter(Enrolment.created_at <= upper_bound)
        enrolments = enrolment_query.order_by(Enrolment.id.asc()).all()
        enrolment_ids = {record.id for record in enrolments}
        student_refs = {record.student_ref for record in enrolments}

        statuses = {"Active": 0, "Completed": 0, "Withdrawn": 0, "Suspended": 0}
        for record in enrolments:
            statuses[record.enrolment_status] = statuses.get(record.enrolment_status, 0) + 1

        pending_query = self.db.query(Alert).filter(
            Alert.status.in_(["OPEN", "UNDER_REVIEW", "AWAITING_CLARIFICATION", "ESCALATED"])
        )
        if lower_bound:
            pending_query = pending_query.filter(Alert.created_at >= lower_bound)
        if upper_bound:
            pending_query = pending_query.filter(Alert.created_at <= upper_bound)
        if institution_id or programme_id or academic_year or admission_cycle:
            pending_query = pending_query.filter(Alert.student_ref.in_(student_refs)) if student_refs else pending_query.filter(False)
        pending_candidates = pending_query.order_by(Alert.created_at.asc()).all()
        pending_alerts = []
        for alert in pending_candidates:
            if (institution_id or programme_id or academic_year or admission_cycle) and (
                not alert.supporting_record_ids
                or not set(alert.supporting_record_ids).issubset(enrolment_ids)
            ):
                continue
            pending_alerts.append(alert)

        pendency_by_severity: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFORMATIONAL": 0}
        pending_items = []
        for alert in pending_alerts:
            pendency_by_severity[alert.severity] = pendency_by_severity.get(alert.severity, 0) + 1
            age_days = max((now.date() - alert.created_at.date()).days, 0) if alert.created_at else None
            pending_items.append({
                "alert_id": alert.id,
                "student_ref": alert.student_ref,
                "apaar_id": alert.apaar_id,
                "type": alert.alert_type,
                "severity": alert.severity,
                "status": alert.status,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
                "days_pending": age_days,
            })

        intake_reports = IntakeComplianceService(self.db).get_all_compliance_reports()
        intake_reports = [
            report for report in intake_reports
            if (not institution_id or report["institution_id"] == institution_id)
            and (not programme_id or report["programme_id"] == programme_id)
            and (not academic_year or report["academic_year"] == academic_year)
            and (not admission_cycle or report.get("admission_cycle") == admission_cycle)
        ]
        excess_intake = [
            {
                "institution_id": report["institution_id"],
                "institution_name": report.get("institution_name"),
                "programme_id": report["programme_id"],
                "programme_name": report.get("programme_name"),
                "academic_year": report["academic_year"],
                "admission_cycle": report.get("admission_cycle"),
                "approved_capacity": report.get("approved_intake"),
                "actual_admissions": report.get("new_admissions_count"),
                "compliance_status": report["compliance_status"],
                "explanation": report.get("explanation") or report.get("summary"),
            }
            for report in intake_reports
            if report["compliance_status"] in {"NON_COMPLIANT_OVER_ADMISSION", "QUOTA_DISCREPANCY"}
        ]

        duplicate_alerts = self.db.query(Alert).filter(
            Alert.alert_type.in_(["DUPLICATE_SUBMISSION", "TEMPORAL_OVERLAP_CONFLICT"])
        ).all()
        duplicate_cases = []
        for alert in duplicate_alerts:
            if alert.student_ref not in student_refs and (institution_id or programme_id or academic_year or admission_cycle):
                continue
            if lower_bound and alert.created_at and alert.created_at < lower_bound:
                continue
            if upper_bound and alert.created_at and alert.created_at > upper_bound:
                continue
            if (institution_id or programme_id or academic_year or admission_cycle) and (
                not alert.supporting_record_ids or not set(alert.supporting_record_ids).issubset(enrolment_ids)
            ):
                continue
            duplicate_cases.append({
                "alert_id": alert.id,
                "student_ref": alert.student_ref,
                "apaar_id": alert.apaar_id,
                "title": alert.title,
                "severity": alert.severity,
                "status": alert.status,
                "decision": alert.reviewer_decision or "Pending Disposition",
            })

        job_query = self.db.query(ImportJob)
        if institution_id:
            job_query = job_query.filter(ImportJob.institution_id == institution_id)
        if lower_bound:
            job_query = job_query.filter(ImportJob.uploaded_at >= lower_bound)
        if upper_bound:
            job_query = job_query.filter(ImportJob.uploaded_at <= upper_bound)
        import_jobs = job_query.all()
        import_job_ids = [job.id for job in import_jobs]
        import_rows = self.db.query(ImportRowResult).filter(
            ImportRowResult.import_job_id.in_(import_job_ids)
        ).all() if import_job_ids else []
        issue_counts: Dict[str, int] = defaultdict(int)
        row_outcomes = {"ACCEPTED": 0, "REJECTED": 0, "NEEDS_REVIEW": 0}
        for row in import_rows:
            row_outcomes[row.outcome] = row_outcomes.get(row.outcome, 0) + 1
            for code in row.issue_codes or []:
                issue_counts[str(code)] += 1

        import_validation_issues = [
            {
                "import_job_id": row.import_job_id,
                "row_result_id": row.id,
                "row_number": row.row_number,
                "record_reference": row.record_reference,
                "outcome": row.outcome,
                "issue_codes": row.issue_codes,
                "validation_messages": row.validation_messages,
            }
            for row in import_rows
            if row.outcome != "ACCEPTED" or row.issue_codes
        ]

        monthly: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            "new_admissions": 0,
            "alerts_triggered": 0,
            "resolved_cases": 0,
            "imports_completed": 0,
        })

        def month_key(timestamp: Optional[datetime]) -> Optional[str]:
            return timestamp.strftime("%Y-%m") if timestamp else None

        for enrolment in enrolments:
            month = month_key(enrolment.created_at)
            if month:
                monthly[month]["new_admissions"] += 1
        for alert in self.db.query(Alert).all():
            if alert.student_ref not in student_refs and (institution_id or programme_id or academic_year or admission_cycle):
                continue
            if lower_bound and alert.created_at and alert.created_at < lower_bound:
                continue
            if upper_bound and alert.created_at and alert.created_at > upper_bound:
                continue
            month = month_key(alert.created_at)
            if month:
                monthly[month]["alerts_triggered"] += 1
        review_query = self.db.query(AlertReviewEvent).filter(
            AlertReviewEvent.new_status == "RESOLVED"
        )
        if lower_bound:
            review_query = review_query.filter(AlertReviewEvent.created_at >= lower_bound)
        if upper_bound:
            review_query = review_query.filter(AlertReviewEvent.created_at <= upper_bound)
        review_events = review_query.all()
        event_resolved_alert_ids = set()
        for event in review_events:
            alert = self.db.query(Alert).filter(Alert.id == event.alert_id).first()
            if alert is None:
                continue
            scoped_filters = institution_id or programme_id or academic_year or admission_cycle
            if scoped_filters and (
                alert.student_ref not in student_refs
                or not alert.supporting_record_ids
                or not set(alert.supporting_record_ids).issubset(enrolment_ids)
            ):
                continue
            month = month_key(event.created_at)
            if month:
                monthly[month]["resolved_cases"] += 1
            event_resolved_alert_ids.add(event.alert_id)
        legacy_resolved_query = self.db.query(Alert).filter(
            Alert.status == "RESOLVED",
            Alert.reviewed_at.is_not(None),
        )
        if lower_bound:
            legacy_resolved_query = legacy_resolved_query.filter(Alert.reviewed_at >= lower_bound)
        if upper_bound:
            legacy_resolved_query = legacy_resolved_query.filter(Alert.reviewed_at <= upper_bound)
        for alert in legacy_resolved_query.all():
            if alert.id in event_resolved_alert_ids:
                continue
            scoped_filters = institution_id or programme_id or academic_year or admission_cycle
            if scoped_filters and (
                alert.student_ref not in student_refs
                or not alert.supporting_record_ids
                or not set(alert.supporting_record_ids).issubset(enrolment_ids)
            ):
                continue
            month = month_key(alert.reviewed_at)
            if month:
                monthly[month]["resolved_cases"] += 1
        for job in import_jobs:
            month = month_key(job.completed_at)
            if month:
                monthly[month]["imports_completed"] += 1

        monthly_summary = [
            {"month": month, **monthly[month]}
            for month in sorted(monthly)
        ]

        return {
            "generated_at": now.isoformat() + "Z",
            "filters": {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "academic_year": academic_year,
                "admission_cycle": admission_cycle,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
            "total_pending_reviews": len(pending_alerts),
            "pendency_by_severity": pendency_by_severity,
            "pending_cases": pending_items,
            "enrolment_summary": {
                "enrolment_records": len(enrolments),
                "distinct_students": len(student_refs),
                "records_by_status": statuses,
            },
            "import_summary": {
                "jobs": len(import_jobs),
                "total_rows": sum(job.total_rows for job in import_jobs),
                "accepted_rows": sum(job.accepted_rows for job in import_jobs),
                "rejected_rows": sum(job.rejected_rows for job in import_jobs),
                "review_rows": sum(job.review_rows for job in import_jobs),
                "outcomes": row_outcomes,
                "validation_issue_counts": dict(issue_counts),
                "programme_year_cycle_filtering_available": False,
            },
            "import_validation_issues": import_validation_issues,
            "import_issue_filters_available": {
                "institution": True,
                "upload_date_range": True,
                "programme": False,
                "academic_year": False,
                "admission_cycle": False,
            },
            "intake_compliance_results": intake_reports,
            "excess_intake_colleges": excess_intake,
            "duplicate_enrolment_cases": duplicate_cases,
            "region_wise_enrolments": [],
            "region_distribution_available": False,
            "region_distribution_reason": "Institution region is not stored in the current schema.",
            "monthly_summary": monthly_summary,
        }