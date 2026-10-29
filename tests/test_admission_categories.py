import pytest

from app.admission_categories import (
    AdmissionCategory,
    REGULAR_CATEGORIES,
    SUPERNUMERARY_CATEGORIES,
    UNCONFIGURED_LIMIT_CATEGORIES,
    normalize_admission_category,
    student_flags_for_admission_category,
)
from app.schemas.enrolment import EnrolmentCreate
from app.services.validation_service import ValidationService


SUPPORTED_CATEGORIES = [category.value for category in AdmissionCategory]


@pytest.mark.parametrize("category", SUPPORTED_CATEGORIES)
def test_all_supported_categories_validate(category):
    errors = ValidationService.validate_record({"student_ref": "STU-CATEGORY", "seat_category": category})

    assert not any(error["rule_id"] == "VAL-CAT-001" for error in errors)
    assert EnrolmentCreate(
        student_ref="STU-CATEGORY",
        apaar_id="MASKED-ID",
        institution_id="INST-1",
        programme_id="PROG-1",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start="2025-08-01",
        enrolment_status="Active",
        seat_category=category,
    ).seat_category.value == category


@pytest.mark.parametrize("category", ["Foreign", "Supernumerary-MadeUp", "NRI-OCI", "", "unknown"])
def test_unsupported_categories_are_rejected(category):
    errors = ValidationService.validate_record({"student_ref": "STU-CATEGORY", "seat_category": category})

    assert any(error["rule_id"] == "VAL-CAT-001" for error in errors)
    with pytest.raises(ValueError):
        EnrolmentCreate(
            student_ref="STU-CATEGORY",
            apaar_id="MASKED-ID",
            institution_id="INST-1",
            programme_id="PROG-1",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start="2025-08-01",
            enrolment_status="Active",
            seat_category=category,
        )


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("General", AdmissionCategory.GENERAL.value),
        (" general ", AdmissionCategory.GENERAL.value),
        ("GENERAL", AdmissionCategory.GENERAL.value),
        ("Foreign-National", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("Foreign National", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("Foreign_National", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("foreign-national", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("FOREIGN NATIONAL", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("  foreign_national  ", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("Supernumerary-TFW", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("Supernumerary TFW", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("Supernumerary_TFW", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("supernumerary-tfw", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("SUPERNUMERARY-TFW", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("supernumerary tfw", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("supernumerary_tfw", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("SUPERNUMERARY_TFW", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("Supernumerary-Tfw", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("  supernumerary_tfw  ", AdmissionCategory.SUPERNUMERARY_TFW.value),
        (" supernumerary tfw ", AdmissionCategory.SUPERNUMERARY_TFW.value),
        ("FOREIGN_NATIONAL", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("foreign national", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("foreign_national", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("Foreign-national", AdmissionCategory.FOREIGN_NATIONAL.value),
        ("OBC", AdmissionCategory.OBC.value),
        ("obc", AdmissionCategory.OBC.value),
        ("Obc", AdmissionCategory.OBC.value),
        (" obc ", AdmissionCategory.OBC.value),
        ("SC", AdmissionCategory.SC.value),
        ("sc", AdmissionCategory.SC.value),
        ("Sc", AdmissionCategory.SC.value),
        (" sc ", AdmissionCategory.SC.value),
        ("ST", AdmissionCategory.ST.value),
        ("st", AdmissionCategory.ST.value),
        ("St", AdmissionCategory.ST.value),
        (" st ", AdmissionCategory.ST.value),
        ("EWS", AdmissionCategory.EWS.value),
        ("ews", AdmissionCategory.EWS.value),
        ("Ews", AdmissionCategory.EWS.value),
        (" ews ", AdmissionCategory.EWS.value),
        ("NRI", AdmissionCategory.NRI.value),
        ("nri", AdmissionCategory.NRI.value),
        ("Nri", AdmissionCategory.NRI.value),
        (" nri ", AdmissionCategory.NRI.value),
        ("OCI", AdmissionCategory.OCI.value),
        ("oci", AdmissionCategory.OCI.value),
        ("Oci", AdmissionCategory.OCI.value),
        (" oci ", AdmissionCategory.OCI.value),
    ],
)
def test_admission_category_normalizes_space_hyphen_underscore_and_case(raw, canonical):
    assert normalize_admission_category(raw) == canonical
    errors = ValidationService.validate_record({"student_ref": "STU-CATEGORY", "seat_category": raw})
    assert not any(error["rule_id"] == "VAL-CAT-001" for error in errors)
    assert EnrolmentCreate(
        student_ref="STU-CATEGORY",
        apaar_id="MASKED-ID",
        institution_id="INST-1",
        programme_id="PROG-1",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start="2025-08-01",
        enrolment_status="Active",
        seat_category=raw,
    ).seat_category.value == canonical


def test_category_classification_is_exact_and_groups_are_non_overlapping():
    assert normalize_admission_category(" general ") == AdmissionCategory.GENERAL.value
    assert normalize_admission_category("Foreign National") == AdmissionCategory.FOREIGN_NATIONAL.value
    assert AdmissionCategory.NRI.value not in REGULAR_CATEGORIES
    assert AdmissionCategory.NRI.value not in SUPERNUMERARY_CATEGORIES
    assert AdmissionCategory.SUPERNUMERARY_TFW.value in SUPERNUMERARY_CATEGORIES
    assert UNCONFIGURED_LIMIT_CATEGORIES == {"OCI", "Foreign-National"}
    assert student_flags_for_admission_category("NRI") == {
        "is_nri": True,
        "is_oci": False,
        "is_foreign_national": False,
    }
    assert student_flags_for_admission_category("Foreign-National")["is_foreign_national"] is True
    assert student_flags_for_admission_category("OCI") == {
        "is_nri": False,
        "is_oci": True,
        "is_foreign_national": False,
    }


def test_admission_category_conflicting_with_explicit_student_flag_is_rejected():
    errors = ValidationService.validate_record({
        "student_ref": "STU-CATEGORY",
        "seat_category": "NRI",
        "is_nri": False,
    })

    assert any(error["rule_id"] == "VAL-CAT-002" for error in errors)