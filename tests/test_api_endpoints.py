def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "APAAR Sentinel" in data["service"]

def test_dashboard_summary(client):
    res = client.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    data = res.json()
    assert "total_students" in data
    assert "open_alerts" in data
    assert "validation_pass_rate" in data

def test_students_api(client):
    res = client.get("/api/v1/students")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert len(data["items"]) > 0

    # Test detail
    s_ref = data["items"][0]["student_ref"]
    res_detail = client.get(f"/api/v1/students/{s_ref}")
    assert res_detail.status_code == 200
    assert "integrity_status" in res_detail.json()

def test_alerts_api(client):
    res = client.get("/api/v1/alerts")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1

    # Review endpoint
    first_alert = next(
        (alert for alert in data["items"] if alert["status"] != "RESOLVED"),
        data["items"][0],
    )
    res_rev = client.patch(
        f"/api/v1/alerts/{first_alert['id']}/review",
        json={"decision": "CONFIRMED_CONFLICT", "note": "Review completed in automated test."}
    )
    if first_alert["status"] == "RESOLVED":
        assert res_rev.status_code == 409
    else:
        assert res_rev.status_code == 200
        assert res_rev.json()["decision"] == "CONFIRMED_CONFLICT"

def test_certificate_verification(client):
    res = client.get("/api/v1/certificates/CERT-APAAR-2026-001/verify")
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "VALID"
    assert data["is_authentic"] is True
