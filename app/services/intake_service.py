from typing import List, Dict, Any, Optional
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.admission_categories import (
    REGULAR_CATEGORIES,
    SUPERNUMERARY_CATEGORIES,
    UNCONFIGURED_LIMIT_CATEGORIES,
    normalize_admission_category,
)
from app.models.enrolment import Enrolment
from app.models.intake import ApprovedIntake

class IntakeComplianceService:
    """
    Evaluates institutional intake compliance according to structured, versioned AICTE rules.
    CRITICAL ARCHITECTURAL CONSTRAINTS:
    1. Distinguishes 'New Admissions' (single batch/cycle) from 'Total Active Enrolment' (across all cohorts).
    2. Never compares multi-batch active enrolment with single-year approved intake limits.
    3. Handles non-mutually exclusive seat categories (e.g., NRI and Supernumerary TFW quotas) cleanly.
    4. Marks unverified rules as 'Needs review' / 'Rule not configured'.
    """

    def __init__(self, db: Session):
        self.db = db

    def evaluate_programme_intake(
        self,
        institution_id: str,
        programme_id: str,
        academic_year: str,
        admission_cycle: Optional[str] = None
    ) -> Dict[str, Any]:
        # Match the complete compliance scope; never substitute another admission cycle.
        rule_query = self.db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id == institution_id,
            ApprovedIntake.programme_id == programme_id,
            ApprovedIntake.academic_year == academic_year
        )
        if admission_cycle is not None:
            rule_query = rule_query.filter(ApprovedIntake.admission_cycle == admission_cycle)
        scoped_rules = rule_query.order_by(ApprovedIntake.id.asc()).all()
        configured_rules = [rule for rule in scoped_rules if rule.rule_configured]

        if not configured_rules:
            status = "RULE_NOT_CONFIGURED" if not scoped_rules else "NEEDS_REVIEW"
            return {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "academic_year": academic_year,
                "admission_cycle": admission_cycle,
                "compliance_status": status,
                "summary": "No active configured rule exists for this exact institution/programme/year/cycle scope.",
                "approved_intake": None,
                "new_admissions_count": None,
                "new_admissions": None,
                "total_active_all_cohorts": None,
                "details": "No other cycle or default quota was substituted.",
                "rule_versions_found": len(scoped_rules),
            }

        if len(configured_rules) > 1:
            return {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "academic_year": academic_year,
                "admission_cycle": admission_cycle,
                "compliance_status": "AMBIGUOUS_RULE",
                "summary": "Multiple active intake rules match this exact scope; compliance cannot be determined.",
                "approved_intake": None,
                "new_admissions_count": None,
                "new_admissions": None,
                "total_active_all_cohorts": None,
                "rule_ids": [rule.rule_id for rule in configured_rules],
                "details": "Deactivate superseded rule versions or resolve the scope before evaluating compliance.",
            }

        rule = configured_rules[0]
        effective_date = None
        try:
            effective_date = date.fromisoformat(rule.effective_date)
        except (TypeError, ValueError):
            return {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "academic_year": academic_year,
                "admission_cycle": rule.admission_cycle,
                "compliance_status": "NEEDS_REVIEW",
                "summary": "The configured rule has an invalid effective date.",
                "approved_intake": None,
                "new_admissions_count": None,
                "new_admissions": None,
                "total_active_all_cohorts": None,
                "rule_id": rule.rule_id,
                "rule_source": rule.rule_source,
                "effective_date": rule.effective_date,
                "details": "Rule dates must be ISO YYYY-MM-DD before compliance can be evaluated.",
            }
        if effective_date > date.today():
            return {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "academic_year": academic_year,
                "admission_cycle": rule.admission_cycle,
                "compliance_status": "RULE_NOT_YET_EFFECTIVE",
                "summary": "The matching intake rule is not effective yet.",
                "approved_intake": None,
                "new_admissions_count": None,
                "new_admissions": None,
                "total_active_all_cohorts": None,
                "rule_id": rule.rule_id,
                "rule_source": rule.rule_source,
                "effective_date": rule.effective_date,
            }

        selected_cycle = rule.admission_cycle

        # 2. Measure A: New Admissions for this specific academic year and admission cycle
        new_admissions_query = self.db.query(Enrolment).filter(
            Enrolment.institution_id == institution_id,
            Enrolment.programme_id == programme_id,
            Enrolment.academic_year == academic_year,
            Enrolment.admission_cycle == selected_cycle,
        )
        new_admissions_records = new_admissions_query.all()
        student_categories: Dict[str, set[str]] = {}
        invalid_categories = set()
        for r in new_admissions_records:
            category = normalize_admission_category(r.seat_category)
            if category is None:
                invalid_categories.add(r.seat_category)
                continue
            student_categories.setdefault(r.student_ref, set()).add(category)

        duplicate_student_refs = sorted(
            student_ref for student_ref in student_categories
            if sum(1 for record in new_admissions_records if record.student_ref == student_ref) > 1
        )
        ambiguous_student_categories = sorted(
            student_ref for student_ref, categories_for_student in student_categories.items()
            if len(categories_for_student) > 1
        )
        category_breakdown: Dict[str, int] = {}
        for categories_for_student in student_categories.values():
            if len(categories_for_student) != 1:
                continue
            category = next(iter(categories_for_student))
            category_breakdown[category] = category_breakdown.get(category, 0) + 1

        new_admissions_count = len({record.student_ref for record in new_admissions_records})
        regular_admitted = sum(category_breakdown.get(category, 0) for category in REGULAR_CATEGORIES)
        supernumerary_admitted = sum(
            category_breakdown.get(category, 0) for category in SUPERNUMERARY_CATEGORIES
        )
        nri_admitted = category_breakdown.get("NRI", 0)
        oci_admitted = category_breakdown.get("OCI", 0)
        foreign_national_admitted = category_breakdown.get("Foreign-National", 0)

        # 3. Measure B: Total Active Enrolment across ALL cohorts currently in the programme
        total_active_all_cohorts = self.db.query(func.count(func.distinct(Enrolment.student_ref))).filter(
            Enrolment.institution_id == institution_id,
            Enrolment.programme_id == programme_id,
            Enrolment.enrolment_status == "Active"
        ).scalar() or 0
        total_active_record_count = self.db.query(func.count(Enrolment.id)).filter(
            Enrolment.institution_id == institution_id,
            Enrolment.programme_id == programme_id,
            Enrolment.enrolment_status == "Active",
        ).scalar() or 0

        # Compare each configured limit independently; do not add category quotas together.
        is_regular_over = regular_admitted > rule.approved_intake_seats
        regular_variance = regular_admitted - rule.approved_intake_seats
        is_supernumerary_over = (
            rule.supernumerary_quota is not None
            and supernumerary_admitted > rule.supernumerary_quota
        )
        is_nri_over = rule.nri_quota is not None and nri_admitted > rule.nri_quota
        missing_quota_limits = []
        if supernumerary_admitted and rule.supernumerary_quota is None:
            missing_quota_limits.append("supernumerary")
        if nri_admitted and rule.nri_quota is None:
            missing_quota_limits.append("NRI")
        needs_review_reasons = []
        if invalid_categories:
            needs_review_reasons.append("unsupported stored categories: " + ", ".join(sorted(invalid_categories)))
        if duplicate_student_refs:
            needs_review_reasons.append("duplicate admission records for student references")
        if ambiguous_student_categories:
            needs_review_reasons.append("students have multiple categories in this admission cycle")
        if oci_admitted or foreign_national_admitted:
            needs_review_reasons.append("OCI/Foreign-National limits are not represented by this rule schema")
        if missing_quota_limits:
            needs_review_reasons.append("missing explicit limits for " + ", ".join(missing_quota_limits))

        if is_regular_over:
            compliance_status = "NON_COMPLIANT_OVER_ADMISSION"
            explanation = (
                f"New admissions for {academic_year} ({regular_admitted} regular seats) exceed "
                f"the AICTE approved intake limit of {rule.approved_intake_seats} by {regular_variance} seats."
            )
        elif needs_review_reasons:
            compliance_status = "NEEDS_REVIEW"
            explanation = "Compliance cannot be determined reliably: " + "; ".join(needs_review_reasons) + "."
        elif is_supernumerary_over or is_nri_over:
            compliance_status = "QUOTA_DISCREPANCY"
            explanation = (
                "Regular intake is within its configured limit, but one or more separately configured "
                "category limits were exceeded. No category limits were added together."
            )
        else:
            compliance_status = "COMPLIANT"
            explanation = (
                f"Admitted intake ({new_admissions_count} total, {regular_admitted} regular) is strictly "
                f"within the sanctioned capacity of {rule.approved_intake_seats} seats for {academic_year}."
            )

        return {
            "institution_id": institution_id,
            "institution_name": rule.institution_name,
            "programme_id": programme_id,
            "programme_name": rule.programme_name,
            "academic_year": academic_year,
            "admission_cycle": selected_cycle,
            "rule_id": rule.rule_id,
            "rule_source": rule.rule_source,
            "effective_date": rule.effective_date,
            "compliance_status": compliance_status,
            "approved_intake": rule.approved_intake_seats,
            "supernumerary_quota": rule.supernumerary_quota,
            "nri_quota": rule.nri_quota,
            "new_admissions_count": new_admissions_count,
            "new_admission_record_count": len(new_admissions_records),
            "regular_admitted": regular_admitted,
            "supernumerary_admitted": supernumerary_admitted,
            "nri_admitted": nri_admitted,
            "oci_admitted": oci_admitted,
            "foreign_national_admitted": foreign_national_admitted,
            "total_active_all_cohorts": total_active_all_cohorts,
            "total_active_record_count": total_active_record_count,
            "utilization_pct": round((regular_admitted / rule.approved_intake_seats * 100), 1) if rule.approved_intake_seats else 0,
            "utilization_defined": bool(rule.approved_intake_seats),
            "category_breakdown": category_breakdown,
            "duplicate_student_refs": duplicate_student_refs,
            "ambiguous_student_category_refs": ambiguous_student_categories,
            "invalid_stored_categories": sorted(invalid_categories),
            "quota_limits_compared_independently": True,
            "rule_expiration_tracked": False,
            "rule_expiration_status": "NOT_TRACKED_IN_CURRENT_SCHEMA",
            "explanation": explanation
        }

    def get_all_compliance_reports(self) -> List[Dict[str, Any]]:
        rules = self.db.query(
            ApprovedIntake.institution_id,
            ApprovedIntake.programme_id,
            ApprovedIntake.academic_year,
            ApprovedIntake.admission_cycle,
        ).distinct().all()
        results = []
        for institution_id, programme_id, academic_year, admission_cycle in rules:
            report = self.evaluate_programme_intake(
                institution_id, programme_id, academic_year, admission_cycle
            )
            results.append(report)
        return results
