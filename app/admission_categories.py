from enum import Enum
from typing import Optional


class AdmissionCategory(str, Enum):
    GENERAL = "General"
    SC = "SC"
    ST = "ST"
    OBC = "OBC"
    EWS = "EWS"
    NRI = "NRI"
    OCI = "OCI"
    FOREIGN_NATIONAL = "Foreign-National"
    SUPERNUMERARY_TFW = "Supernumerary-TFW"


REGULAR_CATEGORIES = frozenset({
    AdmissionCategory.GENERAL.value,
    AdmissionCategory.SC.value,
    AdmissionCategory.ST.value,
    AdmissionCategory.OBC.value,
    AdmissionCategory.EWS.value,
})
SUPERNUMERARY_CATEGORIES = frozenset({AdmissionCategory.SUPERNUMERARY_TFW.value})
UNCONFIGURED_LIMIT_CATEGORIES = frozenset({
    AdmissionCategory.OCI.value,
    AdmissionCategory.FOREIGN_NATIONAL.value,
})

# Primary lookup: canonical hyphenated key (e.g. "foreign-national")
_CATEGORY_BY_CASEFOLD = {category.value.casefold(): category for category in AdmissionCategory}

# Secondary lookup: with spaces instead of hyphens (e.g. "foreign national", "supernumerary tfw")
_CATEGORY_BY_SPACE = {key.replace("-", " "): cat for key, cat in _CATEGORY_BY_CASEFOLD.items()}

# Tertiary lookup: with underscores (e.g. "foreign_national")
_CATEGORY_BY_UNDERSCORE = {key.replace("-", "_"): cat for key, cat in _CATEGORY_BY_CASEFOLD.items()}


def normalize_admission_category(value: object) -> Optional[str]:
    """Return the canonical AdmissionCategory value string for *value*, or None.

    Accepts the canonical hyphenated form ("Foreign-National"), space-separated
    ("Foreign National"), and underscore-separated ("Foreign_National"),
    all case-insensitively.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    casefolded = stripped.casefold()
    category = (
        _CATEGORY_BY_CASEFOLD.get(casefolded)
        or _CATEGORY_BY_SPACE.get(casefolded)
        or _CATEGORY_BY_UNDERSCORE.get(casefolded)
    )
    return category.value if category else None


def student_flags_for_admission_category(category: Optional[str]) -> dict[str, bool]:
    """Map only explicit matching categories; do not infer legal status from text."""
    return {
        "is_nri": category == AdmissionCategory.NRI.value,
        "is_oci": category == AdmissionCategory.OCI.value,
        "is_foreign_national": category == AdmissionCategory.FOREIGN_NATIONAL.value,
    }
