"""
PRAMAAN / APAAR Sentinel - Primary College Seed Script: St. Joseph's College of Engineering
Seeds >= 155 relationally consistent synthetic students into `backend/pramaan_india_demo.db`
under `INST-CHENNAI-SJCE` (St. Joseph's College of Engineering, Chennai, Tamil Nadu).

Includes:
1. Approved Intake Capacities for BTECH-CSE, BTECH-ECE, BTECH-IT, BTECH-MECH, BTECH-CIVIL
2. 155 Student records, APAAR IDs, active Enrolments, and detailed StudentProfiles
3. Academic records: Semester course registrations, internal/external marks, grades, attendance
4. Academic timetables and course materials
5. Student services: Internships, placement readiness, fee obligations, fee receipts, No Due forms
6. Digital academic credentials (issued certificates with Ed25519 signatures)
7. Inter-institutional transfers (with source/destination tracking and Bond Effect Certificates)
8. Deliberate demonstration review issues (attendance shortages, document verification pending,
   neutral data inconsistency alerts, intake flags)
9. sjce_registrar demo account and student_sjce account
"""

import os
import random
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "pramaan_india_demo.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

from app.database import Base
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.user import User
from app.models.student_user import StudentUserLink
from app.models.intake import ApprovedIntake
from app.models.alert import Alert
from app.models.certificate import Certificate
from app.models.transfer import TransferRequest, TransferStatus
from app.models.erp import (
    StudentProfile,
    StudentDocument,
    StudentCourseRecord,
    StudentSemesterRecord,
    StudentAttendanceRecord,
    TimetableSlot,
    CourseMaterial,
    CourseFeedback,
    StudentInternship,
    PlacementReadiness,
    StudentSkill,
    StudentFeeObligation,
    FeePayment,
    NoDueRequest,
    NoDueDepartmentClearance,
)
from app.services.auth_service import PasswordHasher

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

INST_ID = "INST-CHENNAI-SJCE"
INST_NAME = "St. Joseph's College of Engineering, Chennai"
STATE_CODE = "TAMIL_NADU"

FIRST_NAMES = [
    "Karthik", "Priya", "Aarav", "Ananya", "Rohan", "Sneha", "Aditya", "Neha",
    "Vikram", "Pooja", "Rahul", "Divya", "Siddharth", "Meera", "Arjun", "Kavya",
    "Harish", "Ritu", "Gautam", "Tanvi", "Akash", "Swati", "Sanjay", "Ishita",
    "Nikhil", "Deepika", "Manish", "Shreya", "Abhishek", "Bhavna", "Varun", "Anjali",
    "Saravanan", "Kavitha", "Murugan", "Lakshmi", "Venkatesh", "Deepa", "Suresh", "Geetha"
]

LAST_NAMES = [
    "Subramanian", "Iyer", "Rao", "Natarajan", "Sundaram", "Balaji", "Krishnan", "Raman",
    "Sharma", "Patel", "Verma", "Reddy", "Nair", "Deshmukh", "Pillai", "Bhat",
    "Menon", "Joshi", "Gupta", "Chatterjee", "Banerjee", "Mukherjee", "Singh"
]

PROGRAMMES = [
    ("BTECH-CSE", "B.Tech Computer Science & Engineering", "Computer Science & Engineering", 60),
    ("BTECH-ECE", "B.Tech Electronics & Communication Engineering", "Electronics & Communication Engineering", 40),
    ("BTECH-IT", "B.Tech Information Technology", "Information Technology", 30),
    ("BTECH-MECH", "B.Tech Mechanical Engineering", "Mechanical Engineering", 15),
    ("BTECH-CIVIL", "B.Tech Civil Engineering", "Civil Engineering", 10),
    ("PROG-DEMO-CSE", "B.E. Computer Science and Engineering", "Computer Science & Engineering", 0),
    ("PROG-DEMO-ECE", "B.E. Electronics and Communication Engineering", "Electronics & Communication Engineering", 0),
    ("PROG-DEMO-MECH", "B.E. Mechanical Engineering", "Mechanical Engineering", 0),
    ("PROG-DEMO-IT", "B.Tech Information Technology", "Information Technology", 0),
    ("PROG-DEMO-EEE", "B.E. Electrical and Electronics Engineering", "Electrical and Electronics Engineering", 0),
    ("PROG-DEMO-AIDS", "B.Tech Artificial Intelligence and Data Science", "Artificial Intelligence and Data Science", 0),
    ("PROG-DEMO-CIVIL", "B.E. Civil Engineering", "Civil Engineering", 0),
]

INTAKE_LIMITS = {
    "BTECH-CSE": (180, 27, 9),
    "BTECH-ECE": (120, 18, 6),
    "BTECH-IT": (120, 18, 6),
    "BTECH-MECH": (60, 9, 3),
    "BTECH-CIVIL": (60, 9, 3),
    "PROG-DEMO-CSE": (180, 27, 9),
    "PROG-DEMO-ECE": (120, 18, 6),
    "PROG-DEMO-MECH": (120, 18, 6),
    "PROG-DEMO-IT": (120, 18, 6),
    "PROG-DEMO-EEE": (120, 18, 6),
    "PROG-DEMO-AIDS": (120, 18, 6),
    "PROG-DEMO-CIVIL": (60, 9, 3),
}

COURSES_CSE = [
    ("CS501", "Design & Analysis of Algorithms", "Theory", 4.0),
    ("CS502", "Software Engineering & Architecture", "Theory", 4.0),
    ("CS503", "Artificial Intelligence & Machine Learning", "Theory", 4.0),
    ("CS504", "Algorithms & Competitive Coding Lab", "Lab", 2.0),
    ("CS505", "Cloud Computing & DevOps", "Elective", 3.0),
]


def seed_sjce(db=None):
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    print("=" * 80)
    print(f"SEEDING PRIMARY COLLEGE: {INST_NAME} ({INST_ID})")
    print(f"Target Database: {DB_PATH}")
    print("=" * 80)

    # 1. Approved Intakes
    print("[1/8] Configuring Approved Intake capacities for St. Joseph's College of Engineering...")
    for prog_id, prog_name, dept, _ in PROGRAMMES:
        existing_intake = db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id == INST_ID,
            ApprovedIntake.programme_id == prog_id,
            ApprovedIntake.academic_year == "2025-2026",
        ).first()
        seats, supernum, nri = INTAKE_LIMITS[prog_id]
        if not existing_intake:
            intake = ApprovedIntake(
                institution_id=INST_ID,
                institution_name=INST_NAME,
                programme_id=prog_id,
                programme_name=prog_name,
                academic_year="2025-2026",
                admission_cycle="Regular 2025",
                approved_intake_seats=seats,
                supernumerary_quota=supernum,
                nri_quota=nri,
                rule_id=f"AICTE-APH-2025-TN-{prog_id.replace('-', '')}",
                rule_source="AICTE Approval Process Handbook (Tamil Nadu Technical Directorate)",
                effective_date="2025-04-01",
                rule_configured=True,
            )
            db.add(intake)

    DEMO_INTAKE_PROGRAMMES = [
        ("PROG-DEMO-CSE", "B.E. Computer Science and Engineering", 180, 27, 9),
        ("PROG-DEMO-ECE", "B.E. Electronics and Communication Engineering", 120, 18, 6),
        ("PROG-DEMO-MECH", "B.E. Mechanical Engineering", 120, 18, 6),
        ("PROG-DEMO-IT", "B.Tech Information Technology", 120, 18, 6),
        ("PROG-DEMO-EEE", "B.E. Electrical and Electronics Engineering", 120, 18, 6),
        ("PROG-DEMO-AIDS", "B.Tech Artificial Intelligence and Data Science", 120, 18, 6),
        ("PROG-DEMO-CIVIL", "B.E. Civil Engineering", 60, 9, 3),
    ]
    for prog_id, prog_name, seats, supernum, nri in DEMO_INTAKE_PROGRAMMES:
        existing_demo = db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id == "INST-DEMO-01",
            ApprovedIntake.programme_id == prog_id,
            ApprovedIntake.academic_year == "2025-2026",
        ).first()
        if not existing_demo:
            intake_demo = ApprovedIntake(
                institution_id="INST-DEMO-01",
                institution_name="St. Joseph's College of Engineering",
                programme_id=prog_id,
                programme_name=prog_name,
                academic_year="2025-2026",
                admission_cycle="Regular 2025",
                approved_intake_seats=seats,
                supernumerary_quota=supernum,
                nri_quota=nri,
                rule_id=f"AICTE-APH-2025-TN-{prog_id.replace('-', '')}",
                rule_source="AICTE Approval Process Handbook (Tamil Nadu Technical Directorate)",
                effective_date="2025-04-01",
                rule_configured=True,
            )
            db.add(intake_demo)
    db.commit()
    print("      [PASS] Approved intake limits registered for 5 programmes.")

    # 2. Seed / ensure demo accounts
    print("[2/8] Ensuring College & Student demo accounts...")
    reg_user = db.query(User).filter(User.username == "sjce_registrar").first()
    pwd_hash = PasswordHasher.hash_password("SjceRegistrar@2026!")
    if not reg_user:
        reg_user = User(
            username="sjce_registrar",
            email="registrar@stjosephs.ac.in",
            password_hash=pwd_hash,
            full_name="Registrar, St. Joseph's College of Engineering",
            role="institution_officer",
            role_category="INSTITUTION_REGISTRAR",
            institution_id=INST_ID,
            is_active=True,
        )
        db.add(reg_user)
        db.commit()
        print("      [PASS] Created sjce_registrar account.")
    else:
        reg_user.institution_id = INST_ID
        reg_user.password_hash = pwd_hash
        db.commit()

    # Student demo user: student_sjce and student_karthik
    stu_user = db.query(User).filter(User.username == "student_karthik").first()
    stu_pwd_hash = PasswordHasher.hash_password("StudentKarthik@2026!")
    if not stu_user:
        stu_user = User(
            username="student_karthik",
            email="karthik.subramanian@stjosephs.ac.in",
            password_hash=stu_pwd_hash,
            full_name="Karthik Subramanian",
            role="student",
            role_category="STUDENT",
            institution_id=INST_ID,
            is_active=True,
        )
        db.add(stu_user)
        db.commit()
    else:
        stu_user.institution_id = INST_ID
        db.commit()

    # 3. Seed 155 synthetic students for St. Joseph's College of Engineering
    print("[3/8] Seeding 155 synthetic students for St. Joseph's College of Engineering...")
    student_counter = 1
    generated_students = []

    for prog_id, prog_name, dept, count in PROGRAMMES:
        for _ in range(count):
            s_ref = f"STU-SJCE-{student_counter:03d}"
            apaar = f"9876-2026-{1000 + student_counter:04d}"
            fname = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            roll_no = f"2023-{dept[:3].upper()}-{student_counter:03d}"

            # Deliberate demonstration anomaly variations
            # Student 1-135: Clean, fully compliant records
            # Student 136-139: Missing documents (pending verification)
            # Student 140-143: Attendance shortages (< 75%)
            # Student 144-147: Inconsistent dates / identity verification review
            # Student 148-151: Duplicate test identifiers
            # Student 152-155: Transfer initiated / credit mobility
            is_attendance_anomaly = (140 <= student_counter <= 143)
            is_doc_missing = (136 <= student_counter <= 139)

            existing_stu = db.query(Student).filter(Student.student_ref == s_ref).first()
            if not existing_stu:
                stu = Student(
                    student_ref=s_ref,
                    apaar_id=apaar,
                    full_name=fname,
                    primary_institution_id=INST_ID,
                    identity_route="AADHAAR_APAAR",
                    identity_status="VERIFIED" if not (144 <= student_counter <= 147) else "PENDING_VERIFICATION",
                    nationality="Indian",
                )
                db.add(stu)
                db.flush()
            else:
                stu = existing_stu
                stu.primary_institution_id = INST_ID

            generated_students.append((stu, roll_no, prog_id, prog_name, dept, student_counter))

            # Enrolment
            existing_enr = db.query(Enrolment).filter(
                Enrolment.student_ref == s_ref,
                Enrolment.institution_id == INST_ID,
            ).first()
            if not existing_enr:
                enr = Enrolment(
                    student_ref=s_ref,
                    apaar_id=stu.apaar_id,
                    institution_id=INST_ID,
                    institution_name=INST_NAME,
                    programme_id=prog_id,
                    programme_name=prog_name,
                    academic_year="2025-2026",
                    admission_cycle="Regular 2024",
                    enrolment_start=date(2024, 8, 1),
                    enrolment_status="Active",
                    seat_category=random.choice(["State TNEA Counselling", "Management Quota", "AICTE Supernumerary"]),
                    record_version=1,
                )
                db.add(enr)

            # Profile
            existing_prof = db.query(StudentProfile).filter(StudentProfile.student_ref == s_ref).first()
            if not existing_prof:
                prof_status = "PENDING_REVIEW" if is_doc_missing else "APPROVED"
                compl_pct = 70 if is_doc_missing else 100
                prof = StudentProfile(
                    student_ref=s_ref,
                    roll_number=roll_no,
                    date_of_birth=f"2004-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
                    gender="Male" if student_counter % 2 == 0 else "Female",
                    blood_group=random.choice(["O+", "A+", "B+", "AB+"]),
                    college_email=f"{s_ref.lower().replace('-', '')}@stjosephs.ac.in",
                    personal_email=f"{s_ref.lower().replace('-', '')}@gmail.com",
                    phone_number=f"+91 98{random.randint(10000000, 99999999)}",
                    department=dept,
                    batch_year="2023-2027",
                    current_year=3,
                    current_semester=5,
                    section=random.choice(["A", "B", "C"]),
                    admission_category="TNEA Government Quota" if student_counter % 3 != 0 else "Management Merit",
                    admission_date=date(2023, 8, 14),
                    profile_status=prof_status,
                    profile_completion_pct=compl_pct,
                    review_remarks="Institutional verification approved by Admissions Dean." if not is_doc_missing else "Missing 12th Standard Original Marksheet proof.",
                    reviewed_by="Registrar Office (SJCE)",
                    reviewed_at=datetime.now(timezone.utc) - timedelta(days=20),
                    submitted_at=datetime.now(timezone.utc) - timedelta(days=25),
                )
                db.add(prof)

            # Documents
            doc_types = ["10th Marksheet", "12th Marksheet", "Aadhaar Card", "Transfer Certificate"]
            for d_idx, d_name in enumerate(doc_types):
                existing_doc = db.query(StudentDocument).filter(
                    StudentDocument.student_ref == s_ref,
                    StudentDocument.document_title == d_name,
                ).first()
                if not existing_doc:
                    doc_status = "PENDING" if (is_doc_missing and d_idx == 1) else "VERIFIED"
                    doc = StudentDocument(
                        student_ref=s_ref,
                        document_type="ACADEMIC_RECORD" if "Marksheet" in d_name else "IDENTITY_PROOF",
                        document_title=d_name,
                        file_name=f"{s_ref.lower()}_{d_name.lower().replace(' ', '_')}.pdf",
                        file_url=f"/documents/{s_ref}/{d_name.lower().replace(' ', '_')}.pdf",
                        file_size_kb=random.randint(180, 520),
                        status=doc_status,
                        verification_remarks="Document verified against Anna University board registry." if doc_status == "VERIFIED" else "Pending original verification in registrar cell.",
                        verified_by="Registrar Office (SJCE)" if doc_status == "VERIFIED" else None,
                        verified_at=datetime.now(timezone.utc) if doc_status == "VERIFIED" else None,
                    )
                    db.add(doc)

            # Academic course records & attendance (Semester 5)
            for c_code, c_name, c_type, credits in COURSES_CSE:
                existing_cr = db.query(StudentCourseRecord).filter(
                    StudentCourseRecord.student_ref == s_ref,
                    StudentCourseRecord.course_code == c_code,
                    StudentCourseRecord.semester == 5,
                ).first()
                if not existing_cr:
                    int_marks = random.randint(30, 39)
                    ext_marks = random.randint(45, 58)
                    tot_marks = int_marks + ext_marks
                    cr = StudentCourseRecord(
                        student_ref=s_ref,
                        institution_id=INST_ID,
                        semester=5,
                        academic_year="2025-2026",
                        course_code=c_code,
                        course_name=c_name,
                        course_type=c_type,
                        credits=credits,
                        internal_marks=float(int_marks),
                        external_marks=float(ext_marks),
                        total_marks=float(tot_marks),
                        grade_point=10.0 if tot_marks >= 90 else 9.0 if tot_marks >= 80 else 8.0,
                        letter_grade="O" if tot_marks >= 90 else "A+" if tot_marks >= 80 else "A",
                        result_status="PASS",
                    )
                    db.add(cr)

                # Attendance
                existing_att = db.query(StudentAttendanceRecord).filter(
                    StudentAttendanceRecord.student_ref == s_ref,
                    StudentAttendanceRecord.course_code == c_code,
                    StudentAttendanceRecord.semester == 5,
                ).first()
                if not existing_att:
                    tot_classes = 45
                    pres = random.randint(28, 32) if is_attendance_anomaly else random.randint(38, 44)
                    att_pct = round((pres / tot_classes) * 100, 1)
                    att = StudentAttendanceRecord(
                        student_ref=s_ref,
                        institution_id=INST_ID,
                        semester=5,
                        academic_year="2025-2026",
                        course_code=c_code,
                        course_name=c_name,
                        total_classes=tot_classes,
                        attended_classes=pres,
                        percentage=att_pct,
                    )
                    db.add(att)

            # Semester record
            existing_sr = db.query(StudentSemesterRecord).filter(
                StudentSemesterRecord.student_ref == s_ref,
                StudentSemesterRecord.semester == 5,
            ).first()
            if not existing_sr:
                sr = StudentSemesterRecord(
                    student_ref=s_ref,
                    institution_id=INST_ID,
                    semester=5,
                    academic_year="2025-2026",
                    total_credits_registered=17.0,
                    total_credits_earned=17.0,
                    sgpa=round(random.uniform(8.1, 9.6), 2),
                    cgpa=round(random.uniform(8.0, 9.4), 2),
                    semester_status="COMPLETED",
                )
                db.add(sr)

            # Student Services: Fee Obligations & Payments
            existing_fee = db.query(StudentFeeObligation).filter(
                StudentFeeObligation.student_ref == s_ref,
                StudentFeeObligation.semester == 5,
            ).first()
            if not existing_fee:
                tuition = 65000.0
                fee_ob = StudentFeeObligation(
                    student_ref=s_ref,
                    institution_id=INST_ID,
                    semester=5,
                    academic_year="2025-2026",
                    tuition_fee=tuition,
                    exam_fee=2500.0,
                    library_lab_fee=4500.0,
                    development_fee=3000.0,
                    total_obligation=75000.0,
                    total_paid=75000.0,
                    outstanding_balance=0.0,
                    due_date="2025-08-30",
                    status="PAID",
                )
                db.add(fee_ob)
                db.flush()

                payment = FeePayment(
                    obligation_id=fee_ob.id,
                    student_ref=s_ref,
                    transaction_ref=f"TXN-SJCE-{student_counter:05d}",
                    receipt_number=f"REC/SJCE/2025/{student_counter:04d}",
                    amount=75000.0,
                    payment_method="Net Banking",
                    payment_date="2025-08-20",
                    status="SUCCESS",
                    recorded_by="Finance Office",
                )
                db.add(payment)

            # No Due Request
            existing_nd = db.query(NoDueRequest).filter(NoDueRequest.student_ref == s_ref).first()
            if not existing_nd:
                nd = NoDueRequest(
                    student_ref=s_ref,
                    institution_id=INST_ID,
                    academic_year="2025-2026",
                    reason="Semester Clearance & Examination Hall Ticket",
                    overall_status="CLEARED",
                    final_clearance_date=datetime.now(timezone.utc) - timedelta(days=35),
                    cleared_by="Dean of Student Affairs",
                )
                db.add(nd)
                db.flush()

                depts = ["Library", "Laboratory", "Department Office", "Accounts & Fees", "Hostel & Mess"]
                for d in depts:
                    db.add(NoDueDepartmentClearance(
                        request_id=nd.id,
                        department_name=d,
                        status="APPROVED",
                        outstanding_dues_inr=0.0,
                        remarks="Zero outstanding liability.",
                        cleared_by="Department In-charge",
                        cleared_at=datetime.now(timezone.utc) - timedelta(days=36),
                    ))

            # Internships
            if student_counter % 2 == 0:
                existing_intern = db.query(StudentInternship).filter(StudentInternship.student_ref == s_ref).first()
                if not existing_intern:
                    db.add(StudentInternship(
                        student_ref=s_ref,
                        institution_id=INST_ID,
                        company_name="Tata Consultancy Services" if student_counter % 4 == 0 else "Zoho Corporation",
                        role_title="Software Engineering Intern",
                        location="Chennai",
                        start_date=date(2025, 6, 1),
                        end_date=date(2025, 7, 31),
                        stipend_amount=25000.0,
                        mentor_name="Sundar R, Principal Architect",
                        mentor_email="sundar.r@tcs.com",
                        status="APPROVED",
                        review_feedback="Excellent performance during summer industrial internship.",
                        reviewed_by="Dean of Industry Relations (SJCE)",
                        reviewed_at=datetime.now(timezone.utc) - timedelta(days=50),
                    ))

            # Certificates
            existing_cert = db.query(Certificate).filter(Certificate.student_ref == s_ref).first()
            if not existing_cert:
                cert = Certificate(
                    certificate_id=f"CERT-SJCE-2026-{student_counter:03d}",
                    student_ref=s_ref,
                    apaar_id=stu.apaar_id,
                    student_name=fname,
                    institution_id=INST_ID,
                    institution_name=INST_NAME,
                    programme_id=prog_id,
                    programme_name=prog_name,
                    completion_date="2026-05-30",
                    issue_date="2026-06-15",
                    status="ACTIVE",
                    signature_algorithm="Ed25519",
                    public_key_id="SENTINEL-ED25519-KEY-01",
                    signature_hex="9b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a",
                    payload_json={
                        "student_ref": s_ref,
                        "student_name": fname,
                        "institution_id": INST_ID,
                        "programme_name": prog_name,
                        "degree_classification": "First Class with Distinction",
                    },
                )
                db.add(cert)

            student_counter += 1

    db.commit()
    print(f"      [PASS] Seeded {student_counter - 1} students under St. Joseph's College of Engineering.")

    # 4. Link primary demo student to student_karthik
    first_stu = db.query(Student).filter(Student.student_ref == "STU-SJCE-001").first()
    if first_stu:
        link = db.query(StudentUserLink).filter(StudentUserLink.user_id == stu_user.id).first()
        if not link:
            link = StudentUserLink(
                user_id=stu_user.id,
                student_ref=first_stu.student_ref,
                is_primary=True,
            )
            db.add(link)
        else:
            link.student_ref = first_stu.student_ref
        db.commit()
        print(f"      [PASS] Linked student_karthik to {first_stu.student_ref} ({first_stu.full_name}).")

    # 5. Seed Demonstration Transfers involving St. Joseph's College of Engineering
    print("[5/8] Seeding inter-institutional transfers...")
    sample_transfers = [
        ("TR-SJCE-001", "STU-SJCE-152", "INST-CHENNAI-SJCE", "INST-DELHI-DTU", "RELEASED", "NOC/SJCE/2026/012"),
        ("TR-SJCE-002", "STU-SJCE-153", "INST-CHENNAI-SJCE", "INST-TRICHY-NITT", "PENDING_RELEASE", None),
        ("TR-SJCE-003", "STU-SJCE-154", "INST-BLR-PES", "INST-CHENNAI-SJCE", "ADMITTED", "NOC/PES/2026/044"),
        ("TR-SJCE-004", "STU-SJCE-155", "INST-DELHI-DTU", "INST-CHENNAI-SJCE", "RELEASED", "NOC/DTU/2026/091"),
    ]
    for tr_id, st_ref, src_inst, dest_inst, st_status, noc_ref in sample_transfers:
        ex_tr = db.query(TransferRequest).filter(TransferRequest.id == tr_id).first()
        stu_obj = db.query(Student).filter(Student.student_ref == st_ref).first()
        if not ex_tr:
            tr = TransferRequest(
                id=tr_id,
                student_ref=st_ref,
                apaar_id=stu_obj.apaar_id if stu_obj else None,
                source_institution_id=src_inst,
                source_institution_name="St. Joseph's College of Engineering, Chennai" if "SJCE" in src_inst else src_inst,
                destination_institution_id=dest_inst,
                destination_institution_name="St. Joseph's College of Engineering, Chennai" if "SJCE" in dest_inst else dest_inst,
                source_state="TAMIL_NADU" if "SJCE" in src_inst else "OTHER",
                destination_state="TAMIL_NADU" if "SJCE" in dest_inst else "OTHER",
                programme_id="BTECH-CSE",
                programme_name="B.Tech Computer Science & Engineering",
                academic_year="2025-2026",
                initiation_date=date(2026, 1, 10),
                requested_effective_date=date(2026, 2, 1),
                status=st_status,
                noc_certificate_ref=noc_ref,
                created_by="Student / Registrar Portal",
            )
            db.add(tr)
    db.commit()
    print("      [PASS] Seeded inter-state and intra-state transfer requests.")

    # 6. Seed deliberate, neutral investigation cases flagged for review
    print("[6/8] Seeding neutral investigation cases / integrity review items...")
    neutral_cases = [
        ("ALT-SJCE-001", "STU-SJCE-136", "MISSING_INFORMATION", "MEDIUM", "OPEN",
         "Missing 12th Standard Original Marksheet", "Mandatory secondary school leaving marksheet copy awaiting physical verification in admissions wing."),
        ("ALT-SJCE-002", "STU-SJCE-140", "ACADEMIC_DATA_INCONSISTENCY", "HIGH", "UNDER_REVIEW",
         "Semester 5 Attendance Shortage Flag", "Student attendance registered below 75% statutory threshold in CS501 and CS502 (64.2%). Medical condonation review pending."),
        ("ALT-SJCE-003", "STU-SJCE-144", "IDENTITY_MISMATCH", "MEDIUM", "AWAITING_INFORMATION",
         "Aadhaar e-KYC Demographic Mismatch", "Spelling variation detected between secondary certificate name and Aadhaar repository. Awaiting student clarification document."),
        ("ALT-SJCE-004", "STU-SJCE-148", "DUPLICATE_IDENTIFIERS", "HIGH", "OPEN",
         "Duplicate Entrance Roll Number in External Callset", "Joint State CET counselling rank recorded under multiple candidate applications. Cross-state registry audit required."),
        ("ALT-SJCE-005", "STU-SJCE-152", "CONFLICTING_ENROLMENT", "LOW", "RESOLVED",
         "Inter-State Mobility Transition Enrolment", "Transient overlap during transfer NOC issuance. Source institution successfully released; resolved upon matriculation."),
    ]
    for a_id, st_ref, c_type, sev, stat, title, expl in neutral_cases:
        ex_alt = db.query(Alert).filter(Alert.id == a_id).first()
        stu_obj = db.query(Student).filter(Student.student_ref == st_ref).first()
        if not ex_alt:
            alt = Alert(
                id=a_id,
                student_ref=st_ref,
                apaar_id=stu_obj.apaar_id if stu_obj else "9876-2026-0000",
                alert_type=c_type,
                severity=sev,
                status=stat,
                title=title,
                explanation=expl,
                confidence_score=0.92,
                reviewer_decision="Pending documentation" if stat != "RESOLVED" else "Exception accepted and resolved",
            )
            db.add(alt)
    db.commit()
    print("      [PASS] Seeded neutral investigation cases with non-pejorative classifications.")

    # 7. Timetables & Materials
    print("[7/8] Seeding Timetable and Course Syllabus for St. Joseph's College of Engineering...")
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    periods = [
        ("09:00", "10:00", "CS501", "Design & Analysis of Algorithms", "Dr. S. Ramanathan", "LH-301"),
        ("10:00", "11:00", "CS502", "Software Engineering & Architecture", "Prof. M. Geetha", "LH-301"),
        ("11:15", "12:15", "CS503", "Artificial Intelligence & ML", "Dr. K. Venkatesh", "LH-301"),
        ("13:15", "14:15", "CS505", "Cloud Computing & DevOps", "Prof. A. Balaji", "LH-301"),
        ("14:15", "16:15", "CS504", "Algorithms Lab", "Dr. S. Ramanathan", "Lab-4"),
    ]
    for day in days:
        for s_time, e_time, c_code, c_name, faculty, room in periods:
            ex_slot = db.query(TimetableSlot).filter(
                TimetableSlot.institution_id == INST_ID,
                TimetableSlot.day_of_week == day,
                TimetableSlot.start_time == s_time,
                TimetableSlot.semester == 5,
            ).first()
            if not ex_slot:
                db.add(TimetableSlot(
                    institution_id=INST_ID,
                    programme_id="BTECH-CSE",
                    semester=5,
                    section="A",
                    day_of_week=day,
                    start_time=s_time,
                    end_time=e_time,
                    course_code=c_code,
                    course_name=c_name,
                    faculty_name=faculty,
                    room_number=room,
                ))

    # Course Materials
    for c_code, c_name, _, _ in COURSES_CSE:
        ex_mat = db.query(CourseMaterial).filter(
            CourseMaterial.institution_id == INST_ID,
            CourseMaterial.course_code == c_code,
        ).first()
        if not ex_mat:
            db.add(CourseMaterial(
                institution_id=INST_ID,
                programme_id="BTECH-CSE",
                semester=5,
                course_code=c_code,
                course_name=c_name,
                title=f"{c_name} - Foundation & Unit 1 Lecture Notes",
                material_type="Lecture Notes",
                file_url=f"/materials/{INST_ID}/{c_code.lower()}_unit1.pdf",
            ))
    db.commit()
    print("      [PASS] Timetables and course materials seeded.")

    print("[8/8] Complete! Primary College data successfully populated.")
    print("=" * 80)
    if should_close:
        db.close()


if __name__ == "__main__":
    seed_sjce()
