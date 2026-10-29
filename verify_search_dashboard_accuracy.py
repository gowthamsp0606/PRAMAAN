"""
Comprehensive Search, Filtering, Pagination, and Dashboard Aggregates Verification
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///./pramaan_india_demo.db"

from fastapi.testclient import TestClient
from sqlalchemy import func
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.intake import ApprovedIntake
from app.models.transfer import TransferRequest
from app.models.certificate import Certificate
from app.services.auth_service import TokenManager

client = TestClient(app)

with SessionLocal() as db:
    admin_u = db.query(User).filter(User.username == "admin").first()
    admin_tok, _, _ = TokenManager.create_access_token(admin_u)

headers = {"Authorization": f"Bearer {admin_tok}"}

def run_accuracy_verification():
    print("=" * 80)
    print("RUNNING END-TO-END SEARCH, FILTERING, PAGINATION & DASHBOARD ACCURACY AUDIT")
    print("=" * 80)

    # 1. Search Tests
    # Student by name
    res = client.get("/api/v1/search?q=Sourav", headers=headers)
    assert res.status_code == 200
    s_data = res.json()
    assert s_data["total"] >= 1
    assert any("Sourav" in s["title"] for s in s_data["categories"]["students"])
    print("[PASS] Student search by name ('Sourav'): Match verified.")

    # Student by reference
    res = client.get("/api/v1/search?q=STU-IND-054", headers=headers)
    assert res.status_code == 200
    assert any(s["id"] == "STU-IND-054" for s in res.json()["categories"]["students"])
    print("[PASS] Student search by reference ('STU-IND-054'): Match verified.")

    # Institution by name
    res = client.get("/api/v1/search?q=Technology", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["categories"]["institutions"]) >= 1
    print(f"[PASS] Institution search by name ('Technology'): {len(res.json()['categories']['institutions'])} matches found.")

    # Transfer search
    res = client.get("/api/v1/search?q=TRF-IND", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["categories"]["transfers"]) >= 1
    print(f"[PASS] Transfer search by keyword ('TRF-IND'): {len(res.json()['categories']['transfers'])} matches found.")

    # Alert search
    res = client.get("/api/v1/search?q=ALT-IND", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["categories"]["alerts"]) >= 1
    print(f"[PASS] Alert search by keyword ('ALT-IND'): {len(res.json()['categories']['alerts'])} matches found.")

    # Credential search
    res = client.get("/api/v1/search?q=CERT-IND", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["categories"]["credentials"]) >= 1
    print(f"[PASS] Credential search by keyword ('CERT-IND'): {len(res.json()['categories']['credentials'])} matches found.")

    # Empty search
    res = client.get("/api/v1/search?q=NONEXISTENT_QUERY_TERM_ABC_XYZ_000", headers=headers)
    assert res.status_code == 200
    assert res.json()["total"] == 0
    print("[PASS] Empty search results properly returns total 0 without error.")

    # 2. Student Detail Retrieval
    res = client.get("/api/v1/students/STU-IND-054", headers=headers)
    assert res.status_code == 200
    stu_det = res.json()
    assert stu_det["student"]["student_ref"] == "STU-IND-054"
    assert stu_det["student"]["full_name"] == "Karthik Subramanian"
    assert len(stu_det["enrolments"]) >= 1
    print(f"[PASS] Student detail retrieval verified: {stu_det['student']['full_name']} ({stu_det['student']['student_ref']})")

    # 3. Transfer State Filtering (Source and Destination)
    res_src = client.get("/api/v1/transfers?source_state=DELHI", headers=headers)
    assert res_src.status_code == 200
    src_items = res_src.json()["items"]
    assert all(t["source_state"] == "DELHI" for t in src_items)
    print(f"[PASS] Transfer filtering by source_state (DELHI): {len(src_items)} transfers verified.")

    res_dst = client.get("/api/v1/transfers?destination_state=MAHARASHTRA", headers=headers)
    assert res_dst.status_code == 200
    dst_items = res_dst.json()["items"]
    assert all(t["destination_state"] == "MAHARASHTRA" for t in dst_items)
    print(f"[PASS] Transfer filtering by destination_state (MAHARASHTRA): {len(dst_items)} transfers verified.")

    # 4. Pagination Verification
    res_p1 = client.get("/api/v1/institution/list?page=1&limit=10", headers=headers)
    res_p2 = client.get("/api/v1/institution/list?page=2&limit=10", headers=headers)
    assert res_p1.status_code == 200 and res_p2.status_code == 200
    p1_items = res_p1.json()["items"]
    p2_items = res_p2.json()["items"]
    assert res_p1.json()["total"] == 73
    assert len(p1_items) == 10 and len(p2_items) == 10
    p1_ids = {i["institution_id"] for i in p1_items}
    p2_ids = {i["institution_id"] for i in p2_items}
    assert p1_ids.isdisjoint(p2_ids), "Pagination sets must be mutually exclusive!"
    print(f"[PASS] Pagination verified: Page 1 (10 items) and Page 2 (10 items) are mutually exclusive with total=73.")

    # 5. Direct Database Aggregates Comparison
    res_dash = client.get("/api/v1/dashboard/summary", headers=headers)
    assert res_dash.status_code == 200
    dash_json = res_dash.json()

    with SessionLocal() as db:
        sql_students = db.query(func.count(Student.student_ref)).scalar()
        sql_institutions = db.query(ApprovedIntake.institution_id).distinct().count()
        sql_open_alerts = db.query(Alert).filter(Alert.status.in_(["OPEN", "UNDER_REVIEW"])).count()
        sql_conflicts = db.query(Alert).filter(Alert.alert_type == "TEMPORAL_OVERLAP_CONFLICT").count()

    print(f"\nDashboard Metric Comparison:")
    print(f"Total Students:        API={dash_json['total_students']}, SQL={sql_students}")
    print(f"Total Institutions:    API={dash_json['total_institutions']}, SQL={sql_institutions}")
    print(f"Open Alerts:           API={dash_json['open_alerts']}, SQL={sql_open_alerts}")
    print(f"Potential Conflicts:   API={dash_json['potential_conflicts_count']}, SQL={sql_conflicts}")

    assert dash_json["total_students"] == sql_students
    assert dash_json["total_institutions"] == sql_institutions
    assert dash_json["open_alerts"] == sql_open_alerts
    assert dash_json["potential_conflicts_count"] == sql_conflicts
    print("[PASS] 100% of National Dashboard aggregates match direct SQL query calculations with zero discrepancy.")

    print("\n" + "=" * 80)
    print("ALL SEARCH, FILTERING, PAGINATION & DASHBOARD ACCURACY AUDITS PASSED!")
    print("=" * 80)

if __name__ == "__main__":
    run_accuracy_verification()
