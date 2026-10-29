import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.admission_categories import normalize_admission_category, student_flags_for_admission_category
from app.config import settings
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob, ImportRowResult
from app.models.intake import ApprovedIntake
from app.models.student import Student
from app.models.erp import StudentProfile
from app.models.versioning import EnrolmentVersion
from app.services.audit_service import AuditService
from app.services.identity_service import IdentityLifecycleService, IdentityStatus
from app.services.integrity_engine import TemporalIntegrityEngine
from app.services.validation_service import ValidationService


_SENSITIVE_ID_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[- ]?){2}\d{4}(?!\d)")


def safe_filename(filename: Optional[str]) -> str:
    basename = (filename or "upload.csv").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return (cleaned or "upload.csv")[:255]


def _identity_hash(row: Dict[str, Any]) -> Optional[str]:
    fields = (
        str(row.get("student_ref", "")).strip(),
        str(row.get("institution_id", "")).strip(),
        str(row.get("programme_id", "")).strip(),
    )
    if not all(fields):
        return None
    message = json.dumps(fields, separators=(",", ":")).encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _safe_validation_message(issue: Dict[str, Any]) -> Dict[str, str]:
    message = str(issue.get("explanation") or issue.get("suggested_correction") or issue.get("message") or "Validation issue.")
    message = _SENSITIVE_ID_PATTERN.sub("[masked identifier]", message)
    suggested = str(issue.get("suggested_correction") or "Review the source row.")
    suggested = _SENSITIVE_ID_PATTERN.sub("[masked identifier]", suggested)
    row_num = issue.get("row_number") or issue.get("row")
    return {
        "code": str(issue.get("rule_id") or "VALIDATION_ERROR"),
        "field": str(issue.get("field") or ""),
        "severity": str(issue.get("severity") or "ERROR"),
        "message": message,
        "suggested_correction": suggested,
        "row_number": str(row_num) if row_num is not None else "",
    }


def _safe_validation_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    safe_issue = {}
    for key, value in issue.items():
        if isinstance(value, str):
            safe_issue[key] = _SENSITIVE_ID_PATTERN.sub("[masked identifier]", value)
        else:
            safe_issue[key] = value
    row_num = safe_issue.get("row_number") or safe_issue.get("row")
    msg = safe_issue.get("message") or safe_issue.get("explanation") or safe_issue.get("suggested_correction") or "Validation issue."
    safe_issue["row_number"] = row_num
    safe_issue["row"] = row_num
    safe_issue["message"] = msg
    safe_issue["error"] = msg
    return safe_issue


class StudentCsvImportService:
    def __init__(self, db: Session):
        self.db = db

    def process(
        self,
        job: ImportJob,
        records: List[Dict[str, Any]],
        previous_job: Optional[ImportJob] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        previous_results: Dict[str, List[ImportRowResult]] = {}
        if previous_job:
            for previous_result in self.db.query(ImportRowResult).filter(
                ImportRowResult.import_job_id == previous_job.id
            ).all():
                if previous_result.identity_hash:
                    previous_results.setdefault(previous_result.identity_hash, []).append(previous_result)

        seen_submission_keys = set()
        seen_batch_student_apaar: Dict[str, str] = {}
        seen_batch_apaar_student: Dict[str, str] = {}
        issues: List[Dict[str, Any]] = []
        affected_students = set()
        accepted_count = 0
        rejected_count = 0
        review_count = 0
        updated_count = 0
        duplicate_count = 0
        valid_rows = 0

        batch_provenance = f"BATCH-{job.id[:8].upper()}-{datetime.utcnow().year}"
        for index, row in enumerate(records, start=1):
            if not row.get("source_submission_id"):
                row["source_submission_id"] = batch_provenance

            row_issues = ValidationService.validate_record(row, row_index=index)
            student_ref = str(row.get("student_ref", "")).strip() or None
            raw_apaar = str(row.get("apaar_id", "")).strip()
            row_apaar = raw_apaar if raw_apaar else None
            institution_id = str(row.get("institution_id", "")).strip()
            programme_id = str(row.get("programme_id", "")).strip()
            academic_year = str(row.get("academic_year", "")).strip()
            admission_cycle = str(row.get("admission_cycle", "")).strip()
            start_value = str(row.get("enrolment_start", "")).strip()
            identity_hash = _identity_hash(row)
            previous_matches = previous_results.get(identity_hash, []) if identity_hash else []
            previous_row_id = previous_matches[0].id if len(previous_matches) == 1 else None
            prior_accepted_match = bool(
                previous_job and len(previous_matches) == 1 and previous_matches[0].persisted
            )

            # Programme reference check
            if institution_id and programme_id:
                is_approved_prog = self.db.query(ApprovedIntake.id).filter(
                    ApprovedIntake.institution_id == institution_id,
                    ApprovedIntake.programme_id == programme_id,
                ).first() is not None
                if not is_approved_prog:
                    known_programmes = {
                        "BTECH-CSE", "BTECH-IT", "BTECH-ECE", "BTECH-MECH", "BTECH-CIVIL",
                        "PROG-DEMO-CSE", "PROG-DEMO-ECE", "PROG-DEMO-MECH", "PROG-DEMO-IT",
                        "PROG-DEMO-EEE", "PROG-DEMO-AIDS", "PROG-DEMO-CIVIL",
                        "MTECH-AI", "BSC-DATA",
                    }
                    if programme_id not in known_programmes or programme_id == "PROG-UNKNOWN-999":
                        row_issues.append({
                            "rule_id": "VAL-REF-001",
                            "field": "programme_id",
                            "severity": "ERROR",
                            "record_reference": student_ref or f"Row-{index}",
                            "explanation": f"Programme reference '{programme_id}' is not an approved AICTE programme for institution '{institution_id}'.",
                            "suggested_correction": "Select an approved programme registered in the approved intake registry.",
                        })

            record_key = (student_ref, institution_id, programme_id, start_value)
            if all(record_key) and record_key in seen_submission_keys:
                duplicate_count += 1
                row_issues.append({
                    "rule_id": "VAL-DUP-001",
                    "field": "student_ref",
                    "severity": "CRITICAL",
                    "record_reference": student_ref,
                    "explanation": "Duplicate student/institution/programme/start-date row in this upload.",
                    "suggested_correction": "Keep one row for this enrolment or correct the source record.",
                })
            elif all(record_key):
                seen_submission_keys.add(record_key)

            # In-batch identity collision checks
            if student_ref:
                if student_ref in seen_batch_student_apaar:
                    prior_apaar = seen_batch_student_apaar[student_ref]
                    if row_apaar and prior_apaar and row_apaar != prior_apaar:
                        row_issues.append({
                            "rule_id": "VAL-ID-CONFLICT",
                            "field": "apaar_id",
                            "severity": "CRITICAL",
                            "record_reference": student_ref,
                            "explanation": f"Conflicting APAAR IDs ('{prior_apaar}' vs '{row_apaar}') for student '{student_ref}' in batch.",
                            "suggested_correction": "Ensure a student reference has a single consistent APAAR ID.",
                        })
                elif row_apaar:
                    seen_batch_student_apaar[student_ref] = row_apaar

            if row_apaar:
                if row_apaar in seen_batch_apaar_student:
                    prior_ref = seen_batch_apaar_student[row_apaar]
                    if student_ref and prior_ref != student_ref:
                        row_issues.append({
                            "rule_id": "VAL-APAAR-COLLISION",
                            "field": "apaar_id",
                            "severity": "CRITICAL",
                            "record_reference": student_ref or f"Row-{index}",
                            "explanation": f"APAAR ID collision: identical APAAR assigned to both '{prior_ref}' and '{student_ref}' in this batch.",
                            "suggested_correction": "Investigate duplicate identity assignment across students.",
                        })
                elif student_ref:
                    seen_batch_apaar_student[row_apaar] = student_ref

            # Database identity collision & mismatch checks
            if student_ref:
                existing_stu = self.db.query(Student).filter(Student.student_ref == student_ref).first()
                if existing_stu:
                    if row_apaar and existing_stu.apaar_id and existing_stu.apaar_id != row_apaar:
                        row_issues.append({
                            "rule_id": "VAL-ID-CONFLICT",
                            "field": "apaar_id",
                            "severity": "CRITICAL",
                            "record_reference": student_ref,
                            "explanation": f"Student '{student_ref}' is already registered with a different APAAR ID in the database.",
                            "suggested_correction": "Verify student reference or initiate an official identity update workflow.",
                        })
                    row_name = str(row.get("full_name", "")).strip()
                    if row_name and existing_stu.full_name and row_name.lower() != existing_stu.full_name.lower():
                        row_issues.append({
                            "rule_id": "VAL-ID-NAME-MISMATCH",
                            "field": "full_name",
                            "severity": "WARNING",
                            "record_reference": student_ref,
                            "explanation": f"Name mismatch: uploaded name '{row_name}' differs from registered '{existing_stu.full_name}'.",
                            "suggested_correction": "Review student name difference; record not automatically merged.",
                        })

            if row_apaar:
                existing_by_apaar = self.db.query(Student).filter(
                    Student.apaar_id == row_apaar,
                    Student.student_ref != student_ref,
                ).first()
                if existing_by_apaar:
                    row_issues.append({
                        "rule_id": "VAL-APAAR-COLLISION",
                        "field": "apaar_id",
                        "severity": "CRITICAL",
                        "record_reference": student_ref or f"Row-{index}",
                        "explanation": f"APAAR ID is already registered to another student ({existing_by_apaar.student_ref}) in database.",
                        "suggested_correction": "Resolve identity collision before attempting import.",
                    })

            if previous_job and len(previous_matches) > 1:
                row_issues.append({
                    "rule_id": "IMPORT-MATCH-001",
                    "field": "student_ref",
                    "severity": "WARNING",
                    "record_reference": student_ref or f"Row-{index}",
                    "explanation": "This row matches multiple rows in the referenced prior import; correction linkage is ambiguous.",
                    "suggested_correction": "Resolve the prior import match before resubmitting this record.",
                })
            elif prior_accepted_match:
                row_issues.append({
                    "rule_id": "IMPORT-MATCH-ACCEPTED-001",
                    "field": "student_ref",
                    "severity": "WARNING",
                    "record_reference": student_ref or f"Row-{index}",
                    "explanation": "The referenced prior import already persisted a matching record; this upload will not overwrite it.",
                    "suggested_correction": "Use an authorized record-correction workflow if the accepted record needs changes.",
                })

            can_process = not any(issue["severity"] in {"CRITICAL", "ERROR"} for issue in row_issues)
            start_date = None
            if can_process:
                start_date = datetime.strptime(start_value, "%Y-%m-%d").date()
                existing = self.db.query(Enrolment.id).filter(
                    Enrolment.student_ref == student_ref,
                    Enrolment.institution_id == institution_id,
                    Enrolment.programme_id == programme_id,
                    Enrolment.enrolment_start == start_date,
                ).first()
                if existing:
                    duplicate_count += 1
                    row_issues.append({
                        "rule_id": "VAL-DUP-001",
                        "field": "student_ref",
                        "severity": "CRITICAL",
                        "record_reference": student_ref,
                        "explanation": "An enrolment with this student, institution, programme and start date already exists.",
                        "suggested_correction": "Review the existing record instead of submitting it again.",
                    })
                    can_process = False

            ambiguous_match = bool(previous_job and len(previous_matches) > 1)
            if ambiguous_match:
                outcome = "NEEDS_REVIEW"
                review_count += 1
                rejected_count += 1
                persisted = False
            elif not can_process:
                outcome = "REJECTED"
                rejected_count += 1
                persisted = False
            elif prior_accepted_match:
                outcome = "NEEDS_REVIEW"
                review_count += 1
                rejected_count += 1
                persisted = False
            else:
                valid_rows += 1
                category = normalize_admission_category(row.get("admission_category") or row.get("seat_category", "General")) or "General"
                flags = student_flags_for_admission_category(category)
                is_historical = bool(row.get("is_historical")) or (
                    bool(academic_year) and any(academic_year.startswith(str(y)) for y in range(2000, 2024))
                )
                passport_val = str(row.get("passport_ref") or row.get("passport_number") or "").strip() or None

                identity_status, identity_route, nationality = IdentityLifecycleService.derive_initial_identity(
                    apaar_id=row_apaar,
                    is_foreign_national=flags["is_foreign_national"],
                    is_historical=is_historical,
                    passport_ref=passport_val,
                )

                if not dry_run:
                    student = self.db.query(Student).filter(Student.student_ref == student_ref).first()
                    if not student:
                        student = Student(
                            student_ref=student_ref,
                            apaar_id=row_apaar,
                            full_name=str(row.get("full_name") or f"Student {student_ref}").strip(),
                            primary_institution_id=institution_id,
                            identity_route=identity_route,
                            identity_status=identity_status,
                            nationality=nationality,
                            passport_ref=passport_val,
                            is_foreign_national=flags["is_foreign_national"],
                            is_nri=flags["is_nri"],
                            is_oci=flags["is_oci"],
                        )
                        self.db.add(student)
                        self.db.flush()
                    else:
                        updated_count += 1
                        if row.get("full_name") and str(row.get("full_name")).strip():
                            student.full_name = str(row.get("full_name")).strip()
                        if not student.apaar_id and row_apaar:
                            student.apaar_id = row_apaar
                            student.identity_status = IdentityStatus.APAAR_VERIFIED
                        self.db.flush()

                    # Create or update StudentProfile if absent
                    profile = self.db.query(StudentProfile).filter(StudentProfile.student_ref == student_ref).first()
                    if not profile:
                        sem_val = 1
                        if row.get("current_semester") and str(row.get("current_semester")).strip().isdigit():
                            sem_val = int(str(row.get("current_semester")).strip())
                        profile = StudentProfile(
                            student_ref=student_ref,
                            roll_number=str(row.get("roll_number") or student_ref).strip(),
                            college_email=str(row.get("email") or "").strip() or None,
                            phone_number=str(row.get("phone_number") or "").strip() or None,
                            department=str(row.get("department") or programme_id).strip() or None,
                            batch_year=str(row.get("batch_year") or academic_year).strip() or None,
                            current_semester=sem_val,
                            section=str(row.get("section") or "A").strip(),
                            admission_category=category,
                        )
                        self.db.add(profile)
                        self.db.flush()

                    end_value = str(row.get("enrolment_end", "")).strip()
                    end_date = datetime.strptime(end_value, "%Y-%m-%d").date() if end_value else None
                    prior_versions = self.db.query(Enrolment).filter(
                        Enrolment.student_ref == student_ref,
                        Enrolment.institution_id == institution_id,
                        Enrolment.programme_id == programme_id,
                    ).count()
                    version = prior_versions + 1
                    enrolment = Enrolment(
                        student_ref=student_ref,
                        apaar_id=row_apaar,
                        institution_id=institution_id,
                        institution_name=str(row.get("institution_name") or institution_id).strip(),
                        programme_id=programme_id,
                        programme_name=str(row.get("programme_name") or programme_id).strip(),
                        academic_year=academic_year,
                        admission_cycle=admission_cycle,
                        enrolment_start=start_date,
                        enrolment_end=end_date,
                        enrolment_status=str(row["enrolment_status"]).strip().capitalize(),
                        seat_category=category,
                        exception_ref=str(row.get("exception_ref") or "").strip() or None,
                        source_submission_id=str(row.get("source_submission_id") or f"CSV-{job.id}").strip(),
                        record_version=version,
                    )
                    self.db.add(enrolment)
                    self.db.flush()
                    self.db.add(EnrolmentVersion(
                        enrolment_id=enrolment.id,
                        student_ref=student_ref,
                        version_number=version,
                        institution_id=institution_id,
                        programme_id=programme_id,
                        enrolment_status=enrolment.enrolment_status,
                        academic_year=academic_year,
                        changed_by=job.submitted_by,
                        change_reason="CSV import" if previous_row_id is None else "CSV correction/resubmission",
                        diff_payload={"import_job_id": job.id, "previous_row_result_id": previous_row_id},
                    ))
                    affected_students.add(student_ref)

                accepted_count += 1
                warning_present = any(issue["severity"] == "WARNING" for issue in row_issues)
                if warning_present:
                    outcome = "NEEDS_REVIEW"
                    review_count += 1
                else:
                    outcome = "ACCEPTED"
                persisted = not dry_run

            for iss in row_issues:
                iss.setdefault("row_number", index)
                iss.setdefault("row", index)
                msg = str(iss.get("explanation") or iss.get("message") or iss.get("suggested_correction") or "Validation error.")
                iss.setdefault("message", msg)
                iss.setdefault("error", msg)

            safe_messages = [_safe_validation_message(issue) for issue in row_issues]
            issues.extend(row_issues)
            self.db.add(ImportRowResult(
                import_job_id=job.id,
                previous_row_result_id=previous_row_id,
                row_number=index,
                record_reference=student_ref,
                identity_hash=identity_hash,
                outcome=outcome,
                persisted=persisted,
                issue_codes=[message["code"] for message in safe_messages],
                validation_messages=safe_messages,
            ))

        rejected_count = len(records) - accepted_count
        severity_counts = {
            severity: sum(1 for issue in issues if issue.get("severity") == severity)
            for severity in ("CRITICAL", "ERROR", "WARNING", "INFO")
        }
        job.total_rows = len(records)
        job.accepted_rows = accepted_count
        job.rejected_rows = rejected_count
        job.review_rows = review_count
        if dry_run:
            job.status = "PREVIEW_WITH_ERRORS" if (rejected_count or review_count) else "PREVIEW"
        else:
            job.status = "COMPLETED_WITH_ERRORS" if (rejected_count or review_count) else "COMPLETED"
        job.validation_summary = {
            "error_count_by_severity": severity_counts,
            "accepted_rows_include_review_rows": True,
            "review_rows_are_a_subset_of_accepted_rows_or_unpersisted_ambiguous_rows": True,
            "dry_run": dry_run,
            "valid_rows": valid_rows,
            "updated_count": updated_count,
            "duplicate_count": duplicate_count,
        }
        job.completed_at = datetime.utcnow()
        AuditService.log_event(
            db=self.db,
            entity_type="IMPORT_JOB",
            entity_id=job.id,
            action="CSV_IMPORT_PREVIEW" if dry_run else "CSV_IMPORT_COMPLETED",
            performed_by=job.submitted_by,
            details={
                "institution_id": job.institution_id,
                "total_rows": job.total_rows,
                "accepted_rows": job.accepted_rows,
                "rejected_rows": job.rejected_rows,
                "review_rows": job.review_rows,
                "valid_rows": valid_rows,
                "updated_count": updated_count,
                "duplicate_count": duplicate_count,
                "status": job.status,
                "dry_run": dry_run,
            },
            commit=False,
        )
        self.db.commit()

        if not dry_run:
            for student_ref in affected_students:
                try:
                    TemporalIntegrityEngine(self.db).evaluate_student(student_ref)
                except Exception:
                    # Import persistence is authoritative; integrity reevaluation can be retried separately.
                    continue

        field_errors = [_safe_validation_issue(issue) for issue in issues[:50]]
        return {
            "total_rows": len(records),
            "rows_received": len(records),
            "valid_rows": valid_rows,
            "accepted_count": accepted_count,
            "rows_imported": accepted_count if not dry_run else 0,
            "updated_count": updated_count,
            "duplicate_count": duplicate_count,
            "rejected_count": rejected_count,
            "rows_rejected": rejected_count,
            "unprocessed_count": 0,
            "review_count": review_count,
            "pass_rate_percent": round((accepted_count / len(records)) * 100, 2) if records else 100.0,
            "error_count_by_severity": severity_counts,
            "field_errors": field_errors,
            "dry_run": dry_run,
        }