from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admission_categories import AdmissionCategory
from app.database import Base
from app.models.enrolment import Enrolment
from app.models.intake import ApprovedIntake
from app.services.intake_service import IntakeComplianceService


@pytest.fixture
def intake_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = sessions()
    yield db
    db.close()
    engine.dispose()


def add_rule(
    db,
    *,
    cycle="Regular 2025",
    approved=10,
    supernumerary=2,
    nri=3,
    rule_id="RULE-V1",
    configured=True,
    effective_date="2025-04-01",
):
    rule = ApprovedIntake(
        institution_id="INST-TEST",
        institution_name="Synthetic Test Institute",
        programme_id="PROG-TEST",
        programme_name="Synthetic Test Programme",
        academic_year="2025-2026",
        admission_cycle=cycle,
        approved_intake_seats=approved,
        supernumerary_quota=supernumerary,
        nri_quota=nri,
        rule_id=rule_id,
        rule_source="Verified test fixture source",
        effective_date=effective_date,
        rule_configured=configured,
    )
    db.add(rule)
    db.flush()
    return rule


def add_enrolment(
    db,
    ref,
    category=AdmissionCategory.GENERAL.value,
    *,
    cycle="Regular 2025",
    year="2025-2026",
    status="Active",
    institution="INST-TEST",
    programme="PROG-TEST",
):
    db.add(Enrolment(
        student_ref=ref,
        apaar_id=f"MASK-{ref}",
        institution_id=institution,
        programme_id=programme,
        academic_year=year,
        admission_cycle=cycle,
        enrolment_start=date(2025, 8, 1),
        enrolment_status=status,
        seat_category=category,
    ))
    db.flush()


def evaluate(db, cycle="Regular 2025"):
    return IntakeComplianceService(db).evaluate_programme_intake(
        "INST-TEST", "PROG-TEST", "2025-2026", cycle
    )


@pytest.mark.parametrize(
    "regular_count,expected",
    [(9, "COMPLIANT"), (10, "COMPLIANT"), (11, "NON_COMPLIANT_OVER_ADMISSION")],
)
def test_regular_intake_below_equal_and_over_limit(intake_db, regular_count, expected):
    add_rule(intake_db, approved=10)
    for index in range(regular_count):
        add_enrolment(intake_db, f"REG-{regular_count}-{index}")

    result = evaluate(intake_db)

    assert result["regular_admitted"] == regular_count
    assert result["compliance_status"] == expected


@pytest.mark.parametrize(
    "category,limit_field,limit,counts_field",
    [
        (AdmissionCategory.NRI.value, "nri", 2, "nri_admitted"),
        (AdmissionCategory.SUPERNUMERARY_TFW.value, "supernumerary", 2, "supernumerary_admitted"),
    ],
)
@pytest.mark.parametrize("count,expected", [(2, "COMPLIANT"), (3, "QUOTA_DISCREPANCY")])
def test_category_limit_exact_and_exceeded(
    intake_db, category, limit_field, limit, counts_field, count, expected
):
    add_rule(intake_db, approved=1, **{limit_field: limit})
    for index in range(count):
        add_enrolment(intake_db, f"{category}-{count}-{index}", category)

    result = evaluate(intake_db)

    assert result[counts_field] == count
    assert result["compliance_status"] == expected


def test_category_quotas_are_compared_separately_without_adding_them(intake_db):
    add_rule(intake_db, approved=1, supernumerary=1, nri=1)
    add_enrolment(intake_db, "REG-1", AdmissionCategory.GENERAL.value)
    add_enrolment(intake_db, "NRI-1", AdmissionCategory.NRI.value)
    add_enrolment(intake_db, "TFW-1", AdmissionCategory.SUPERNUMERARY_TFW.value)

    result = evaluate(intake_db)

    assert result["new_admissions_count"] == 3
    assert result["regular_admitted"] == 1
    assert result["nri_admitted"] == 1
    assert result["supernumerary_admitted"] == 1
    assert result["quota_limits_compared_independently"] is True
    assert result["compliance_status"] == "COMPLIANT"


@pytest.mark.parametrize("category", [AdmissionCategory.OCI.value, AdmissionCategory.FOREIGN_NATIONAL.value])
def test_categories_without_configured_limits_require_review(intake_db, category):
    add_rule(intake_db)
    add_enrolment(intake_db, f"UNCONFIGURED-{category}", category)

    result = evaluate(intake_db)

    assert result["compliance_status"] == "NEEDS_REVIEW"
    assert result["new_admissions_count"] == 1
    assert category in result["category_breakdown"]
    assert "limits are not represented" in result["explanation"]


@pytest.mark.parametrize(
    "category,quota_field",
    [
        (AdmissionCategory.NRI.value, "nri"),
        (AdmissionCategory.SUPERNUMERARY_TFW.value, "supernumerary"),
    ],
)
def test_missing_category_limit_requires_review(intake_db, category, quota_field):
    add_rule(intake_db, **{quota_field: None})
    add_enrolment(intake_db, f"MISSING-LIMIT-{category}", category)

    result = evaluate(intake_db)

    assert result["compliance_status"] == "NEEDS_REVIEW"
    assert "missing explicit limits" in result["explanation"]


def test_invalid_legacy_category_and_conflicting_duplicate_categories_need_review(intake_db):
    add_rule(intake_db)
    add_enrolment(intake_db, "INVALID-CAT", "Legacy-Unclassified")
    add_enrolment(intake_db, "MULTI-CAT", AdmissionCategory.GENERAL.value)
    add_enrolment(intake_db, "MULTI-CAT", AdmissionCategory.NRI.value)

    result = evaluate(intake_db)

    assert result["compliance_status"] == "NEEDS_REVIEW"
    assert result["new_admissions_count"] == 2
    assert result["invalid_stored_categories"] == ["Legacy-Unclassified"]
    assert result["ambiguous_student_category_refs"] == ["MULTI-CAT"]


def test_duplicate_records_count_student_once_and_require_review(intake_db):
    add_rule(intake_db)
    add_enrolment(intake_db, "DUP-1", AdmissionCategory.GENERAL.value)
    add_enrolment(intake_db, "DUP-1", AdmissionCategory.GENERAL.value)

    result = evaluate(intake_db)

    assert result["new_admission_record_count"] == 2
    assert result["new_admissions_count"] == 1
    assert result["category_breakdown"][AdmissionCategory.GENERAL.value] == 1
    assert result["duplicate_student_refs"] == ["DUP-1"]
    assert result["compliance_status"] == "NEEDS_REVIEW"


def test_cycles_are_isolated_and_omitted_cycle_is_ambiguous(intake_db):
    add_rule(intake_db, cycle="Regular 2025", approved=1, rule_id="REGULAR")
    add_rule(intake_db, cycle="Lateral 2025", approved=5, rule_id="LATERAL")
    add_enrolment(intake_db, "REG-CYCLE", cycle="Regular 2025")
    for index in range(3):
        add_enrolment(intake_db, f"LAT-CYCLE-{index}", cycle="Lateral 2025")

    regular = evaluate(intake_db, "Regular 2025")
    lateral = evaluate(intake_db, "Lateral 2025")
    all_cycles = IntakeComplianceService(intake_db).evaluate_programme_intake(
        "INST-TEST", "PROG-TEST", "2025-2026", None
    )

    assert regular["approved_intake"] == 1
    assert regular["new_admissions_count"] == 1
    assert lateral["approved_intake"] == 5
    assert lateral["new_admissions_count"] == 3
    assert all_cycles["compliance_status"] == "AMBIGUOUS_RULE"


def test_missing_unconfigured_and_ambiguous_rules_fail_closed(intake_db):
    assert evaluate(intake_db)["compliance_status"] == "RULE_NOT_CONFIGURED"
    add_rule(intake_db, configured=False)
    assert evaluate(intake_db)["compliance_status"] == "NEEDS_REVIEW"
    add_rule(intake_db, rule_id="RULE-V2", configured=True)
    add_rule(intake_db, rule_id="RULE-V3", configured=True)
    assert evaluate(intake_db)["compliance_status"] == "AMBIGUOUS_RULE"


def test_future_effective_rule_is_not_used(intake_db):
    add_rule(intake_db, effective_date="2999-01-01")

    assert evaluate(intake_db)["compliance_status"] == "RULE_NOT_YET_EFFECTIVE"


def test_rule_without_explicit_configured_state_is_not_authoritative(intake_db):
    rule = ApprovedIntake(
        institution_id="INST-TEST",
        institution_name="Synthetic Test Institute",
        programme_id="PROG-TEST",
        programme_name="Synthetic Test Programme",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        approved_intake_seats=10,
        rule_id="UNVERIFIED",
        rule_source="Pending verification",
        effective_date="2025-04-01",
    )
    intake_db.add(rule)
    intake_db.flush()

    assert rule.rule_configured is False
    assert evaluate(intake_db)["compliance_status"] == "NEEDS_REVIEW"


def test_zero_intake_has_undefined_utilization_and_excess_is_detected(intake_db):
    add_rule(intake_db, approved=0)
    no_admissions = evaluate(intake_db)
    assert no_admissions["compliance_status"] == "COMPLIANT"
    assert no_admissions["utilization_pct"] == 0
    assert no_admissions["utilization_defined"] is False

    add_enrolment(intake_db, "ZERO-OVER", AdmissionCategory.GENERAL.value)
    over = evaluate(intake_db)
    assert over["compliance_status"] == "NON_COMPLIANT_OVER_ADMISSION"
    assert over["regular_admitted"] == 1


def test_withdrawn_admissions_and_historical_active_cohorts_are_distinct(intake_db):
    add_rule(intake_db, approved=2)
    add_enrolment(intake_db, "WITHDRAWN-1", status="Withdrawn")
    add_enrolment(intake_db, "ACTIVE-1", status="Active")
    add_enrolment(intake_db, "HIST-1", year="2024-2025", cycle="Regular 2024", status="Active")

    result = evaluate(intake_db)

    assert result["new_admissions_count"] == 2
    assert result["total_active_all_cohorts"] == 2
    assert result["total_active_record_count"] == 2


def test_rule_configuration_appends_a_version_and_preserves_previous_values():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from app.database import get_db
    from app.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        db.add(ApprovedIntake(
            institution_id="INST-TEST", institution_name="Synthetic Test Institute",
            programme_id="PROG-TEST", programme_name="Synthetic Test Programme",
            academic_year="2025-2026", admission_cycle="Regular 2025",
            approved_intake_seats=10, supernumerary_quota=2, nri_quota=3,
            rule_id="RULE-V1", rule_source="Verified source v1", effective_date="2025-04-01",
            rule_configured=True,
        ))
        db.commit()

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            incomplete_response = client.post("/api/v1/intake-compliance/rules", json={
                "institution_id": "INST-TEST",
                "programme_id": "PROG-TEST",
                "academic_year": "2025-2026",
                "approved_intake_seats": 12,
            })
            response = client.post("/api/v1/intake-compliance/rules", json={
                "institution_id": "INST-TEST",
                "institution_name": "Synthetic Test Institute",
                "programme_id": "PROG-TEST",
                "programme_name": "Synthetic Test Programme",
                "academic_year": "2025-2026",
                "admission_cycle": "Regular 2025",
                "approved_intake_seats": 12,
                "supernumerary_quota": 2,
                "nri_quota": 3,
                "rule_id": "RULE-V2",
                "rule_source": "Verified source v2",
                "effective_date": "2025-05-01",
                "rule_configured": True,
            })
            draft_response = client.post("/api/v1/intake-compliance/rules", json={
                "institution_id": "INST-TEST",
                "institution_name": "Synthetic Test Institute",
                "programme_id": "PROG-TEST",
                "programme_name": "Synthetic Test Programme",
                "academic_year": "2025-2026",
                "admission_cycle": "Regular 2025",
                "approved_intake_seats": 12,
                "rule_id": "RULE-V3-DRAFT",
                "rule_source": "Pending verification",
                "effective_date": "2025-06-01",
                "rule_configured": False,
            })
            history_response = client.get(
                "/api/v1/intake-compliance/INST-TEST/PROG-TEST/rule-history",
                params={"academic_year": "2025-2026", "admission_cycle": "Regular 2025"},
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 201
    assert incomplete_response.status_code == 422
    assert response.json()["history_preserved"] is True
    assert draft_response.status_code == 201
    assert "active rule remains unchanged" in draft_response.json()["message"]
    assert history_response.status_code == 200
    assert [item["rule_id"] for item in history_response.json()["versions"]] == [
        "RULE-V1", "RULE-V2", "RULE-V3-DRAFT"
    ]
    assert history_response.json()["versions"][0]["approved_intake_seats"] == 10
    with sessions() as db:
        versions = db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id == "INST-TEST",
            ApprovedIntake.programme_id == "PROG-TEST",
            ApprovedIntake.admission_cycle == "Regular 2025",
        ).order_by(ApprovedIntake.id.asc()).all()
        assert len(versions) == 3
        assert versions[0].approved_intake_seats == 10
        assert versions[0].rule_configured is False
        assert versions[1].approved_intake_seats == 12
        assert versions[1].rule_configured is True
        assert versions[2].rule_id == "RULE-V3-DRAFT"
        assert versions[2].rule_configured is False
    engine.dispose()