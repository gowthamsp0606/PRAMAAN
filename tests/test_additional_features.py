def test_foreign_national_identity_route(client):
    """
    Verifies higher-ed foreign national passport route without requiring Aadhaar.
    """
    res = client.get("/api/v1/students/STU-DEMO-011")
    assert res.status_code == 200
    data = res.json()["student"]
    assert data["is_foreign_national"] is True
    assert data["identity_route"] == "PASSPORT_INTERNATIONAL"
    assert "PASS-FRA" in data["passport_ref"]

def test_student_version_history(client):
    """
    Verifies that version history preserves previous states.
    """
    res = client.get("/api/v1/students/STU-DEMO-001/versions")
    assert res.status_code == 200
    data = res.json()
    assert data["total_versions"] >= 1
    assert data["versions"][0]["version_number"] >= 1

def test_consent_module_and_employer_verification(client):
    """
    1. STU-DEMO-001 has active consent -> Verifier gets MATCH_VERIFIED with purpose-limited data.
    2. STU-DEMO-002 has WITHDRAWN consent -> Verifier gets CONSENT_WITHHELD (stops sharing).
    """
    # 1. Active consent check
    res_active = client.post("/api/v1/verifier/verify-credential", json={
        "verifier_org_id": "ORG-TCS-BGV",
        "student_ref": "STU-DEMO-001"
    })
    assert res_active.status_code == 200
    data_active = res_active.json()
    assert data_active["verified"] is True
    assert data_active["outcome"] == "MATCH_VERIFIED"
    assert data_active["student_name"] == "Aarav Sharma"
    assert data_active["purpose_scope"] == "EMPLOYMENT_BACKGROUND_CHECK_ONLY"

    # 2. Withdrawn consent check
    res_withdrawn = client.post("/api/v1/verifier/verify-credential", json={
        "verifier_org_id": "ORG-TCS-BGV",
        "student_ref": "STU-DEMO-002"
    })
    assert res_withdrawn.status_code == 200
    data_withdrawn = res_withdrawn.json()
    assert data_withdrawn["verified"] is False
    assert data_withdrawn["outcome"] == "CONSENT_WITHHELD"
    assert "withdrawn sharing consent" in data_withdrawn["message"]

def test_anomaly_dismissal_workflow(client):
    """
    Verifies reviewer can dismiss a legitimate anomaly and record the reason.
    """
    # Get anomaly list
    res_list = client.get("/api/v1/analytics/anomalies")
    assert res_list.status_code == 200
    anomalies = res_list.json()["items"]
    assert len(anomalies) > 0
    anomaly_id = anomalies[0]["id"]

    # Dismiss anomaly
    res_dismiss = client.patch(f"/api/v1/analytics/anomalies/{anomaly_id}/dismiss", json={
        "reason": "AICTE approved expansion under National AI Skilling Mission 2026.",
        "dismissed_by": "Senior Regional Director (AICTE-RO-102)"
    })
    assert res_dismiss.status_code == 200
    assert res_dismiss.json()["dismissed"] is True

def test_executive_reports(client):
    """
    Verifies generation of pendency, excess-intake, duplicates, and regional reports.
    """
    res = client.get("/api/v1/reports/executive-summary")
    assert res.status_code == 200
    data = res.json()
    assert "pendency_by_severity" in data
    assert "excess_intake_colleges" in data
    assert "duplicate_enrolment_cases" in data
    assert "region_wise_enrolments" in data

def test_institution_and_aicte_dashboard_endpoints(client):
    """
    Verifies both dedicated dashboards return live backend values.
    """
    res_inst = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-DELHI-DTU")
    assert res_inst.status_code == 200
    assert "overall_capacity_utilization" in res_inst.json()
    assert "total_sanctioned_intake" in res_inst.json()

    res_aicte = client.get("/api/v1/aicte/dashboard-summary")
    assert res_aicte.status_code == 200
    assert "total_institutions" in res_aicte.json()
    assert "critical_temporal_conflicts" in res_aicte.json()
