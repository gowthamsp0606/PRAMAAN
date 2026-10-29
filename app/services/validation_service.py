import re
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from app.admission_categories import normalize_admission_category, student_flags_for_admission_category

ACADEMIC_YEAR_REGEX = re.compile(r"^20\d{2}-20\d{2}$")
VALID_STATUSES = {"Active", "Completed", "Withdrawn", "Suspended"}

class ValidationService:
    """
    Automated Validation Centre:
    Evaluates individual or bulk CSV rows for technical schema compliance, date integrity,
    and provenance before intake/enrolment operations.
    Keeps schema validation issues distinct from regulatory policy conflicts.
    """

    CANONICAL_FIELD_ALIASES: Dict[str, List[str]] = {
        "student_ref": [
            "student_ref", "studentref", "studentid", "student_id", "reg_no", "regno",
            "registration_number", "registrationnumber", "roll_no", "rollno",
            "roll_number", "rollnumber", "enrollment_number", "enrolment_no",
        ],
        "full_name": [
            "full_name", "fullname", "student_name", "studentname", "name",
            "candidate_name", "candidatename",
        ],
        "institution_id": [
            "institution_id", "institutionid", "college_id", "collegeid",
            "institution_code", "institutioncode", "college_code", "inst_id",
        ],
        "programme_id": [
            "programme_id", "programmeid", "program_id", "programid",
            "programme", "program", "course", "degree",
        ],
        "academic_year": [
            "academic_year", "academicyear", "acad_year", "acadyear", "session",
        ],
        "admission_cycle": [
            "admission_cycle", "admissioncycle", "cycle", "admission_type",
        ],
        "enrolment_start": [
            "enrolment_start", "enrolmentstart", "enrollment_start", "enrollmentstart",
            "admission_date", "admissiondate", "joining_date", "start_date",
        ],
        "enrolment_status": [
            "enrolment_status", "enrolmentstatus", "enrollment_status", "enrollmentstatus",
            "status", "academic_status", "academicstatus", "enrolment_state", "enrollment_state",
            "student_status", "studentstatus", "current_status", "currentstatus",
        ],
        "admission_cycle": [
            "admission_cycle", "admissioncycle", "cycle", "admission_type", "admissiontype",
            "intake_cycle", "intakecycle", "admission_session",
        ],
        "source_submission_id": [
            "source_submission_id", "source_submission", "sourcesubmissionid", "sourcesubmission",
            "submission_id", "submissionid", "batch_id", "batchid", "batch_submission_id",
            "batchsubmissionid", "provenance_id", "provenanceid", "batch_ref", "batchref",
        ],
        "email": [
            "email", "student_email", "college_email", "personal_email", "email_address",
            "contact_email", "contactemail", "mail",
        ],
        "phone_number": [
            "phone_number", "phonenumber", "phone", "mobile", "mobile_number", "contact_number",
            "contactnumber", "contact_no", "contactno", "contact_phone", "contactphone",
        ],
        "department": [
            "department", "dept", "branch", "discipline",
        ],
        "batch_year": [
            "batch_year", "batchyear", "batch",
        ],
        "current_year": [
            "current_year", "currentyear", "year",
        ],
        "current_semester": [
            "current_semester", "currentsemester", "semester", "sem",
        ],
        "section": [
            "section", "sec",
        ],
        "admission_category": [
            "admission_category", "admissioncategory", "category", "quota",
        ],
        "apaar_id": [
            "apaar_id", "apaarid", "apaar", "edu_id", "eduid",
            "aadhaar", "aadhaarid", "aadhaar_id",
            "aadhaaridentifier", "aadhaar_identifier",
            "identifier", "national_id", "nationalid",
            "uid", "aadhar", "aadharid", "aadharidentifier", "aadhar_identifier",
            "apaar_no", "apaarno", "apaar_number", "apaarnumber",
        ],
        "gender": [
            "gender", "sex",
        ],
        "date_of_birth": [
            "date_of_birth", "dateofbirth", "dob",
        ],
    }

    REQUIRED_COLUMNS = [
        "student_ref",
        "institution_id",
        "programme_id",
        "academic_year",
        "enrolment_start",
        "enrolment_status",
    ]

    @classmethod
    def normalize_header(cls, header: str) -> Optional[str]:
        if not isinstance(header, str):
            return None
        cleaned = re.sub(r"[^a-z0-9]", "", header.strip().lstrip("\ufeff").lower())
        for canonical, aliases in cls.CANONICAL_FIELD_ALIASES.items():
            if cleaned == re.sub(r"[^a-z0-9]", "", canonical.lower()):
                return canonical
            for alias in aliases:
                if cleaned == re.sub(r"[^a-z0-9]", "", alias.lower()):
                    return canonical
        return None

    @classmethod
    def map_csv_row(
        cls,
        row: Dict[str, Any],
        default_institution_id: Optional[str] = None,
        default_submission_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        mapped = {}
        for k, v in row.items():
            if not isinstance(k, str):
                continue
            canonical = cls.normalize_header(k)
            if canonical:
                mapped[canonical] = v
            else:
                cleaned_k = k.strip().lstrip("\ufeff")
                mapped[cleaned_k] = v

        if default_institution_id in ("INST-DEMO-01", "INST-CHENNAI-SJC"):
            default_institution_id = "INST-CHENNAI-SJCE"

        if not mapped.get("institution_id") and default_institution_id:
            mapped["institution_id"] = default_institution_id

        # Normalize institution aliases for St. Joseph's College of Engineering
        inst_val = str(mapped.get("institution_id", "")).strip()
        if inst_val in ("INST-DEMO-01", "INST-CHENNAI-SJC"):
            mapped["institution_id"] = "INST-CHENNAI-SJCE"
            inst_name = str(mapped.get("institution_name", ""))
            if not inst_name or "St. Joseph" in inst_name:
                mapped["institution_name"] = "St. Joseph's College of Engineering, Chennai"
        if not mapped.get("source_submission_id") and default_submission_id:
            mapped["source_submission_id"] = default_submission_id
        if not mapped.get("academic_year") and mapped.get("batch_year"):
            by = str(mapped["batch_year"]).strip()
            if re.match(r"^\d{4}$", by):
                mapped["academic_year"] = f"{by}-{int(by)+1}"
            else:
                mapped["academic_year"] = by
        if not mapped.get("programme_id") and mapped.get("department"):
            dept_raw = str(mapped["department"]).upper()
            if "COMP" in dept_raw or "CSE" in dept_raw:
                mapped["programme_id"] = "BTECH-CSE"
            elif "INFO" in dept_raw or "IT" in dept_raw:
                mapped["programme_id"] = "BTECH-IT"
            elif "ELEC" in dept_raw or "ECE" in dept_raw:
                mapped["programme_id"] = "BTECH-ECE"
            elif "MECH" in dept_raw:
                mapped["programme_id"] = "BTECH-MECH"
            elif "CIVIL" in dept_raw:
                mapped["programme_id"] = "BTECH-CIVIL"
            else:
                mapped["programme_id"] = f"BTECH-{re.sub(r'[^A-Z0-9]', '', dept_raw)[:4]}"
        elif not mapped.get("department") and mapped.get("programme_id"):
            pid = str(mapped["programme_id"]).upper()
            if "CSE" in pid:
                mapped["department"] = "Computer Science and Engineering"
            elif "ECE" in pid:
                mapped["department"] = "Electronics and Communication Engineering"
            elif "MECH" in pid:
                mapped["department"] = "Mechanical Engineering"
            elif "IT" in pid:
                mapped["department"] = "Information Technology"
            elif "EEE" in pid:
                mapped["department"] = "Electrical and Electronics Engineering"
            elif "AIDS" in pid or "AI" in pid:
                mapped["department"] = "Artificial Intelligence and Data Science"
            elif "CIVIL" in pid:
                mapped["department"] = "Civil Engineering"
        if not mapped.get("enrolment_start") and mapped.get("academic_year"):
            parts = str(mapped["academic_year"]).split("-")
            mapped["enrolment_start"] = f"{parts[0]}-08-01"
        if not mapped.get("roll_number") and mapped.get("student_ref"):
            mapped["roll_number"] = mapped["student_ref"]

        # Collect raw normalized header keys present in the input row
        raw_keys = {cls.normalize_header(k) or k.strip().lstrip("\ufeff").lower() for k in row.keys() if isinstance(k, str)}

        # If admission_cycle column was completely omitted from the upload (simplified human roster):
        if "admission_cycle" not in raw_keys and "admissioncycle" not in raw_keys and not mapped.get("admission_cycle"):
            acad_val = mapped.get("academic_year") or mapped.get("batch_year") or "2025"
            mapped["admission_cycle"] = f"Regular {str(acad_val)[:4]}"

        # If enrolment_status / status column was completely omitted from the upload:
        status_keys = {"enrolment_status", "enrolmentstatus", "status", "enrollment_status", "academic_status"}
        if not (raw_keys & status_keys) and not mapped.get("enrolment_status"):
            mapped["enrolment_status"] = "Active"

        return mapped

    @classmethod
    def validate_headers(cls, headers: List[str], allow_inferred_institution: bool = False) -> Tuple[bool, List[str]]:
        """
        Validates that all mandatory columns are present in the CSV header,
        handling arbitrary column ordering, capitalization, and documented aliases.
        Returns (is_valid, list_of_missing_columns).
        """
        canonical_present = set()
        for h in headers:
            if isinstance(h, str):
                canon = cls.normalize_header(h)
                if canon:
                    canonical_present.add(canon)
                else:
                    canonical_present.add(h.strip().lstrip("\ufeff").lower())

        if "batch_year" in canonical_present and "academic_year" not in canonical_present:
            canonical_present.add("academic_year")
        if "department" in canonical_present and "programme_id" not in canonical_present:
            canonical_present.add("programme_id")

        required = [
            "student_ref",
            "programme_id",
            "academic_year",
        ]
        if not allow_inferred_institution:
            required.append("institution_id")

        missing = [col for col in required if col not in canonical_present]
        return (len(missing) == 0, missing)

    @staticmethod
    def validate_record(record: Dict[str, Any], row_index: Optional[int] = None) -> List[Dict[str, Any]]:
        errors = []
        rec_ref = record.get("student_ref") or f"Row-{row_index or 'Unknown'}"

        # 1. Base mandatory fields
        base_required = [
            ("student_ref", "Student Reference"),
            ("institution_id", "Institution Code"),
            ("programme_id", "Programme Code"),
            ("academic_year", "Academic Year"),
            ("admission_cycle", "Admission Cycle"),
            ("enrolment_start", "Enrolment Start Date"),
            ("enrolment_status", "Enrolment Status")
        ]

        for field_name, label in base_required:
            val = record.get(field_name)
            if val is None or str(val).strip() == "":
                if field_name == "enrolment_status":
                    val = (
                        record.get("status")
                        or record.get("enrollment_status")
                        or record.get("academic_status")
                    )
                    if val is not None and str(val).strip() != "":
                        record["enrolment_status"] = val
                elif field_name == "student_ref":
                    val = record.get("roll_number") or record.get("registration_number")
                    if val is not None and str(val).strip() != "":
                        record["student_ref"] = val
                elif field_name == "institution_id":
                    val = record.get("college_id") or record.get("college_code")
                    if val is not None and str(val).strip() != "":
                        record["institution_id"] = val
                elif field_name == "programme_id":
                    val = record.get("program_id") or record.get("course") or record.get("degree")
                    if val is not None and str(val).strip() != "":
                        record["programme_id"] = val
                elif field_name == "academic_year":
                    val = record.get("batch_year") or record.get("acad_year")
                    if val is not None and str(val).strip() != "":
                        record["academic_year"] = val
                elif field_name == "enrolment_start":
                    val = record.get("start_date") or record.get("admission_date") or record.get("joining_date")
                    if val is not None and str(val).strip() != "":
                        record["enrolment_start"] = val
                elif field_name == "admission_cycle":
                    val = record.get("cycle") or record.get("admission_type")
                    if val is not None and str(val).strip() != "":
                        record["admission_cycle"] = val

            if val is None or str(val).strip() == "":
                errors.append({
                    "rule_id": "VAL-REQ-001",
                    "field": field_name,
                    "severity": "CRITICAL",
                    "record_reference": rec_ref,
                    "explanation": f"Missing mandatory field '{label}' ({field_name}).",
                    "suggested_correction": f"Provide a valid non-empty string for {field_name}."
                })

        # 1b. Contextual APAAR validation
        apaar_val = record.get("apaar_id")
        adm_cat = str(record.get("admission_category") or "").strip().lower().replace("-", " ").replace("_", " ")
        seat_cat_clean = str(record.get("seat_category") or "").strip().lower().replace("-", " ").replace("_", " ")
        is_fn = bool(record.get("is_foreign_national")) or (
            "foreign national" in adm_cat or "foreign national" in seat_cat_clean or adm_cat in ("fn", "international") or seat_cat_clean in ("fn", "international")
        )
        acad_year_str = str(record.get("academic_year") or "").strip()
        is_historical = bool(record.get("is_historical")) or (
            bool(acad_year_str) and any(acad_year_str.startswith(str(y)) for y in range(2000, 2024))
        )

        if apaar_val is None or str(apaar_val).strip() == "":
            if is_fn:
                errors.append({
                    "rule_id": "VAL-APAAR-EXEMPT",
                    "field": "apaar_id",
                    "severity": "INFO",
                    "record_reference": rec_ref,
                    "explanation": "Foreign national student is exempt from mandatory APAAR ID under MoE protocol.",
                    "suggested_correction": "Passport/visa details serve as primary cross-border identifier."
                })
            elif is_historical:
                errors.append({
                    "rule_id": "VAL-APAAR-HISTORICAL",
                    "field": "apaar_id",
                    "severity": "INFO",
                    "record_reference": rec_ref,
                    "explanation": f"Historical enrolment ({acad_year_str}) without APAAR ID. Record accepted under legacy provenance.",
                    "suggested_correction": "Verify legacy institutional records during audit reconciliation."
                })
            else:
                errors.append({
                    "rule_id": "VAL-REQ-001",
                    "field": "apaar_id",
                    "severity": "CRITICAL",
                    "record_reference": rec_ref,
                    "explanation": "Missing mandatory field 'APAAR ID' (apaar_id). Contemporary domestic admissions require an APAAR ID.",
                    "suggested_correction": "Provide a valid non-empty string for apaar_id."
                })
        else:
            clean_apaar = str(apaar_val).strip().replace("-", "").replace(" ", "")
            if not clean_apaar.isdigit() or len(clean_apaar) != 12:
                errors.append({
                    "rule_id": "VAL-APAAR-FMT-001",
                    "field": "apaar_id",
                    "severity": "WARNING",
                    "record_reference": rec_ref,
                    "explanation": f"APAAR ID '{apaar_val}' does not conform to standard 12-digit format.",
                    "suggested_correction": "Verify 12-digit APAAR identifier (e.g. 1234-5678-9012)."
                })

        if "seat_category" in record:
            seat_category = record.get("seat_category")
            normalized_category = normalize_admission_category(seat_category)
            if normalized_category is None:
                errors.append({
                    "rule_id": "VAL-CAT-001",
                    "field": "seat_category",
                    "severity": "ERROR",
                    "record_reference": rec_ref,
                    "explanation": (
                        f"Unsupported admission category '{seat_category}'. Supported values: "
                        "General, SC, ST, OBC, EWS, NRI, OCI, Foreign-National, Supernumerary-TFW."
                    ),
                    "suggested_correction": "Use one of the supported admission-category values exactly.",
                })
            else:
                expected_flags = student_flags_for_admission_category(normalized_category)
                for flag_name, expected in expected_flags.items():
                    provided = record.get(flag_name)
                    explicit_false = provided is False or (
                        isinstance(provided, str) and provided.strip().casefold() in {"false", "0", "no"}
                    )
                    if expected and explicit_false:
                        errors.append({
                            "rule_id": "VAL-CAT-002",
                            "field": flag_name,
                            "severity": "ERROR",
                            "record_reference": rec_ref,
                            "explanation": (
                                f"Admission category '{normalized_category}' conflicts with "
                                f"the explicit {flag_name}=false classification."
                            ),
                            "suggested_correction": "Correct either the admission category or the classification flag.",
                        })

        # 2. Date parsing and validation
        start_date = None
        start_val = record.get("enrolment_start")
        if start_val:
            try:
                if isinstance(start_val, (datetime, date)):
                    start_date = start_val if isinstance(start_val, date) else start_val.date()
                else:
                    start_date = datetime.strptime(str(start_val).strip(), "%Y-%m-%d").date()
            except ValueError:
                errors.append({
                    "rule_id": "VAL-DAT-001",
                    "field": "enrolment_start",
                    "severity": "ERROR",
                    "record_reference": rec_ref,
                    "explanation": f"Invalid start date format '{start_val}'. Required format: YYYY-MM-DD.",
                    "suggested_correction": "Format dates using standard ISO-8601 (e.g. 2025-08-01)."
                })

        end_date = None
        end_val = record.get("enrolment_end")
        if end_val and str(end_val).strip() != "":
            try:
                if isinstance(end_val, (datetime, date)):
                    end_date = end_val if isinstance(end_val, date) else end_val.date()
                else:
                    end_date = datetime.strptime(str(end_val).strip(), "%Y-%m-%d").date()
            except ValueError:
                errors.append({
                    "rule_id": "VAL-DAT-002",
                    "field": "enrolment_end",
                    "severity": "ERROR",
                    "record_reference": rec_ref,
                    "explanation": f"Invalid end date format '{end_val}'. Required format: YYYY-MM-DD.",
                    "suggested_correction": "Format dates using standard ISO-8601 (e.g. 2026-05-31)."
                })

        # 3. End date earlier than start date
        if start_date and end_date:
            if end_date < start_date:
                errors.append({
                    "rule_id": "VAL-DAT-003",
                    "field": "enrolment_end",
                    "severity": "CRITICAL",
                    "record_reference": rec_ref,
                    "explanation": f"End date ({end_date}) is chronologically earlier than start date ({start_date}).",
                    "suggested_correction": "Ensure completion or withdrawal date occurs on or after enrolment start date."
                })

        # 4. Enrolment status validation
        status_val = record.get("enrolment_status")
        if status_val and str(status_val).strip():
            capitalized_status = str(status_val).strip().capitalize()
            if capitalized_status not in VALID_STATUSES:
                errors.append({
                    "rule_id": "VAL-STA-001",
                    "field": "enrolment_status",
                    "severity": "ERROR",
                    "record_reference": rec_ref,
                    "explanation": f"Invalid enrolment status '{status_val}'. Permitted values: {', '.join(sorted(VALID_STATUSES))}.",
                    "suggested_correction": "Set status to one of: Active, Completed, Withdrawn, Suspended."
                })

        # 5. Academic Year format
        acad_val = record.get("academic_year")
        if acad_val and str(acad_val).strip():
            if not ACADEMIC_YEAR_REGEX.match(str(acad_val).strip()):
                errors.append({
                    "rule_id": "VAL-FMT-001",
                    "field": "academic_year",
                    "severity": "WARNING",
                    "record_reference": rec_ref,
                    "explanation": f"Academic year '{acad_val}' does not conform to YYYY-YYYY standard format (e.g. '2025-2026').",
                    "suggested_correction": "Use four-digit span format like 2025-2026."
                })

        # 6. Source provenance
        source_val = (
            record.get("source_submission_id")
            or record.get("submission_id")
            or record.get("batch_id")
            or record.get("batch_submission_id")
        )
        if not source_val or str(source_val).strip() == "":
            errors.append({
                "rule_id": "VAL-PRV-001",
                "field": "source_submission_id",
                "severity": "WARNING",
                "record_reference": rec_ref,
                "explanation": "Missing source batch submission ID or batch provenance tracking metadata.",
                "suggested_correction": "Include a submission identifier (e.g. BATCH-2026-AICTE-01) for audit traceability."
            })

        for err in errors:
            if row_index is not None:
                err["row_number"] = row_index
                err["row"] = row_index
            expl = err.get("explanation") or err.get("message") or "Validation error"
            err["message"] = expl
            err["error"] = expl

        return errors

    @classmethod
    def validate_dataset(cls, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validates a full dataset, tracking individual record errors, duplicate records within the batch,
        and computing overall pass rate.
        """
        all_errors = []
        accepted_count = 0
        rejected_count = 0
        seen_keys = {}

        for idx, rec in enumerate(records):
            rec_errors = cls.validate_record(rec, row_index=idx + 1)
            
            # Duplicate check within batch
            dedup_key = (
                str(rec.get("student_ref", "")).strip(),
                str(rec.get("institution_id", "")).strip(),
                str(rec.get("programme_id", "")).strip(),
                str(rec.get("enrolment_start", "")).strip()
            )
            if dedup_key in seen_keys:
                rec_errors.append({
                    "rule_id": "VAL-DUP-001",
                    "field": "student_ref",
                    "severity": "CRITICAL",
                    "record_reference": rec.get("student_ref", f"Row-{idx+1}"),
                    "explanation": f"Exact duplicate row in batch (identical to row {seen_keys[dedup_key]}).",
                    "suggested_correction": "Deduplicate import dataset before batch processing."
                })
            else:
                seen_keys[dedup_key] = idx + 1

            has_critical_or_error = any(e["severity"] in ("CRITICAL", "ERROR") for e in rec_errors)
            if has_critical_or_error:
                rejected_count += 1
            else:
                accepted_count += 1

            all_errors.extend(rec_errors)

        total = len(records)
        pass_rate = round((accepted_count / total * 100), 2) if total > 0 else 100.0

        return {
            "total_records": total,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "pass_rate_percent": pass_rate,
            "errors": all_errors,
            "error_count_by_severity": {
                "CRITICAL": sum(1 for e in all_errors if e["severity"] == "CRITICAL"),
                "ERROR": sum(1 for e in all_errors if e["severity"] == "ERROR"),
                "WARNING": sum(1 for e in all_errors if e["severity"] == "WARNING"),
                "INFO": sum(1 for e in all_errors if e["severity"] == "INFO")
            }
        }
