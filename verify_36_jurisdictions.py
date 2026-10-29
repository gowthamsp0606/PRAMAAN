"""
Audit Script for All 36 Indian Jurisdictions
Verifies for each jurisdiction:
- Institution records exist in ApprovedIntake
- Student records exist in Student
- Enrolment records exist in Enrolment
- State filtering API (/api/v1/students?state=...) returns correctly scoped results
- Status is PASS only when all criteria are satisfied
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///./pramaan_india_demo.db"

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.intake import ApprovedIntake
from app.services.state_service import KNOWN_INSTITUTION_STATES, STATE_NAMES
from app.services.auth_service import TokenManager

client = TestClient(app)

with SessionLocal() as db:
    admin_u = db.query(User).filter(User.username == "admin").first()
    admin_tok, _, _ = TokenManager.create_access_token(admin_u)

headers = {"Authorization": f"Bearer {admin_tok}"}

# Group institutions by state
state_to_insts = {}
for inst_id, st in KNOWN_INSTITUTION_STATES.items():
    state_to_insts.setdefault(st, []).append(inst_id)

table_rows = []
with SessionLocal() as db:
    for st_code in sorted(state_to_insts.keys()):
        inst_ids = state_to_insts[st_code]
        inst_cnt = len(set(r[0] for r in db.query(ApprovedIntake.institution_id).filter(ApprovedIntake.institution_id.in_(inst_ids)).all()))
        stu_cnt = db.query(Student).filter(Student.primary_institution_id.in_(inst_ids)).count()
        enr_cnt = db.query(Enrolment).filter(Enrolment.institution_id.in_(inst_ids)).count()
        
        # Test API filtering
        api_res = client.get(f"/api/v1/students?state={st_code}", headers=headers)
        api_total = api_res.json().get("total", 0) if api_res.status_code == 200 else -1
        
        status = "PASS" if inst_cnt > 0 and stu_cnt > 0 and enr_cnt > 0 and api_total == stu_cnt else "FAIL"
        st_name = STATE_NAMES.get(st_code, st_code)
        table_rows.append((st_code, st_name, inst_cnt, stu_cnt, enr_cnt, api_total, status))

header_fmt = "| {:<24} | {:<38} | {:<12} | {:<8} | {:<10} | {:<17} | {:<6} |"
divider = "|--------------------------|----------------------------------------|--------------|----------|------------|-------------------|--------|"
print(header_fmt.format("Jurisdiction Code", "State / UT Name", "Institutions", "Students", "Enrolments", "API filter result", "Status"))
print(divider)
for r in table_rows:
    print(header_fmt.format(r[0], r[1], r[2], r[3], r[4], f"{r[5]} students", r[6]))

# Assert all 36 passed
assert len(table_rows) == 36, f"Expected 36 jurisdictions, found {len(table_rows)}"
assert all(r[6] == "PASS" for r in table_rows), "One or more jurisdictions failed!"
print("\n[SUCCESS] All 36 Indian Jurisdictions Verified with 100% PASS Status!")
