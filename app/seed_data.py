from datetime import date
from app.database import SessionLocal, engine, Base
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.intake import ApprovedIntake, HistoricalIntake
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.models.versioning import EnrolmentVersion
from app.services.integrity_engine import TemporalIntegrityEngine
from app.services.certificate_service import CertificateService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

def init_db_and_seed():
    print("Initialising database tables...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    seeded_models = (
        Student,
        Enrolment,
        Alert,
        AuditLog,
        EnrolmentVersion,
        StudentConsent,
        VerifierOrganization,
        VerificationRequestLog,
        ApprovedIntake,
        HistoricalIntake,
        Certificate,
    )
    if any(db.query(model).first() is not None for model in seeded_models):
        print("Database already contains records; leaving existing data unchanged.")
        AuthService.seed_demo_users(db)
        db.close()
        return

    print("Seeding students and enrolments...")
    # 1. Student STU-DEMO-001: Scenario A — Legitimate Transfer
    s1 = Student(
        student_ref="STU-DEMO-001",
        apaar_id="9876-5432-1001",
        full_name="Aarav Sharma",
        primary_institution_id="INST-DELHI-DTU",
        nationality="Indian",
        identity_route="AADHAAR_APAAR"
    )
    e1_1 = Enrolment(
        student_ref="STU-DEMO-001",
        apaar_id="9876-5432-1001",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=date(2026, 5, 31),
        enrolment_status="Completed",
        seat_category="General",
        source_submission_id="SUB-DTU-2025-01",
        record_version=1
    )
    e1_2 = Enrolment(
        student_ref="STU-DEMO-001",
        apaar_id="9876-5432-1001",
        institution_id="INST-DELHI-NSUT",
        institution_name="Netaji Subhas University of Technology (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2026-2027",
        admission_cycle="Lateral/Transfer 2026",
        enrolment_start=date(2026, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-NSUT-2026-02",
        record_version=1
    )

    # 2. Student STU-DEMO-002: Scenario B — Potential Overlapping Active Enrolment
    s2 = Student(
        student_ref="STU-DEMO-002",
        apaar_id="9876-5432-1002",
        full_name="Priya Patel",
        primary_institution_id="INST-DELHI-IIITD",
        nationality="Indian",
        identity_route="AADHAAR_APAAR"
    )
    e2_1 = Enrolment(
        student_ref="STU-DEMO-002",
        apaar_id="9876-5432-1002",
        institution_id="INST-DELHI-IIITD",
        institution_name="Indraprastha Institute of IT Delhi (Demo)",
        programme_id="BTECH-AIDS",
        programme_name="B.Tech Artificial Intelligence & Data Science",
        academic_year="2026-2027",
        admission_cycle="Regular 2026",
        enrolment_start=date(2026, 7, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-IIITD-2026-01",
        record_version=1
    )
    e2_2 = Enrolment(
        student_ref="STU-DEMO-002",
        apaar_id="9876-5432-1002",
        institution_id="INST-PUNE-COEP",
        institution_name="COEP Technological University (Demo)",
        programme_id="BTECH-ECE",
        programme_name="B.Tech Electronics & Communication",
        academic_year="2026-2027",
        admission_cycle="Regular 2026",
        enrolment_start=date(2026, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="OBC",
        source_submission_id="SUB-COEP-2026-04",
        record_version=1
    )

    # 3. Student STU-DEMO-003: Scenario C — Documented Permitted Exception
    s3 = Student(
        student_ref="STU-DEMO-003",
        apaar_id="9876-5432-1003",
        full_name="Rohan Verma",
        primary_institution_id="INST-PUNE-COEP",
        nationality="Indian",
        identity_route="AADHAAR_APAAR"
    )
    e3_1 = Enrolment(
        student_ref="STU-DEMO-003",
        apaar_id="9876-5432-1003",
        institution_id="INST-PUNE-COEP",
        institution_name="COEP Technological University (Demo)",
        programme_id="BTECH-MECH",
        programme_name="B.Tech Mechanical Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-COEP-2025-09",
        record_version=1
    )
    e3_2 = Enrolment(
        student_ref="STU-DEMO-003",
        apaar_id="9876-5432-1003",
        institution_id="INST-MUMBAI-IITB",
        institution_name="IIT Bombay External Extension (Demo)",
        programme_id="DUAL-AI-MIN",
        programme_name="Minor in Artificial Intelligence & Robotics",
        academic_year="2025-2026",
        admission_cycle="Joint Credit 2025",
        enrolment_start=date(2025, 10, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        exception_ref="AICTE-EXC-2025-DUAL-04",
        source_submission_id="SUB-IITB-2025-EXC",
        record_version=1
    )

    # 4. Student STU-DEMO-004: Duplicate Submission
    s4 = Student(
        student_ref="STU-DEMO-004",
        apaar_id="9876-5432-1004",
        full_name="Ananya Iyer",
        primary_institution_id="INST-DELHI-DTU"
    )
    e4_1 = Enrolment(
        student_ref="STU-DEMO-004",
        apaar_id="9876-5432-1004",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-DTU-2025-BATCH-A",
        record_version=1
    )
    e4_2 = Enrolment(
        student_ref="STU-DEMO-004",
        apaar_id="9876-5432-1004",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-DTU-2025-BATCH-B",
        record_version=2
    )

    # 5. Student STU-DEMO-005: Withdrawn record followed by new enrolment
    s5 = Student(
        student_ref="STU-DEMO-005",
        apaar_id="9876-5432-1005",
        full_name="Kavya Nair",
        primary_institution_id="INST-TRICHY-NITT"
    )
    e5_1 = Enrolment(
        student_ref="STU-DEMO-005",
        apaar_id="9876-5432-1005",
        institution_id="INST-TRICHY-NITT",
        institution_name="National Institute of Technology Trichy (Demo)",
        programme_id="BTECH-CIVIL",
        programme_name="B.Tech Civil Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=date(2025, 11, 15),
        enrolment_status="Withdrawn",
        seat_category="General",
        source_submission_id="SUB-NITT-2025-W1",
        record_version=1
    )
    e5_2 = Enrolment(
        student_ref="STU-DEMO-005",
        apaar_id="9876-5432-1005",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-IT",
        programme_name="B.Tech Information Technology",
        academic_year="2025-2026",
        admission_cycle="Special Round 2025",
        enrolment_start=date(2025, 12, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="General",
        source_submission_id="SUB-DTU-2025-SR",
        record_version=1
    )

    # 6. Student STU-DEMO-011: Foreign National via Passport Identity Route (Ministry of Education Higher Ed Protocol)
    s11 = Student(
        student_ref="STU-DEMO-011",
        apaar_id="9876-5432-1011",
        full_name="Jean-Luc Picard",
        primary_institution_id="INST-DELHI-DTU",
        identity_route="PASSPORT_INTERNATIONAL",
        passport_ref="PASS-FRA-88219",
        nationality="French",
        is_foreign_national=True
    )
    e11 = Enrolment(
        student_ref="STU-DEMO-011",
        apaar_id="9876-5432-1011",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="International 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_end=None,
        enrolment_status="Active",
        seat_category="Foreign-National",
        source_submission_id="SUB-DTU-INTL-2025",
        record_version=1
    )

    # Additional standard active student records
    more_students = [
        Student(student_ref="STU-DEMO-006", apaar_id="9876-5432-1006", full_name="Vikramaditya Rao", primary_institution_id="INST-DELHI-DTU", is_nri=True),
        Student(student_ref="STU-DEMO-007", apaar_id="9876-5432-1007", full_name="Meera Sen", primary_institution_id="INST-DELHI-IIITD"),
        Student(student_ref="STU-DEMO-008", apaar_id="9876-5432-1008", full_name="Farhan Siddiqui", primary_institution_id="INST-DELHI-NSUT"),
        Student(student_ref="STU-DEMO-009", apaar_id="9876-5432-1009", full_name="Tanvi Deshmukh", primary_institution_id="INST-PUNE-COEP"),
        Student(student_ref="STU-DEMO-010", apaar_id="9876-5432-1010", full_name="Deepak Chawla", primary_institution_id="INST-TRICHY-NITT")
    ]
    more_enrolments = [
        Enrolment(student_ref="STU-DEMO-006", apaar_id="9876-5432-1006", institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2025-2026", admission_cycle="Regular 2025", enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active", seat_category="NRI", source_submission_id="SUB-DTU-2025-01", record_version=1),
        Enrolment(student_ref="STU-DEMO-007", apaar_id="9876-5432-1007", institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2025-2026", admission_cycle="Regular 2025", enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active", seat_category="Supernumerary-TFW", source_submission_id="SUB-IIITD-2025-01", record_version=1),
        Enrolment(student_ref="STU-DEMO-008", apaar_id="9876-5432-1008", institution_id="INST-DELHI-NSUT", institution_name="Netaji Subhas University of Technology (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2025-2026", admission_cycle="Regular 2025", enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active", seat_category="SC", source_submission_id="SUB-NSUT-2025-01", record_version=1),
        Enrolment(student_ref="STU-DEMO-009", apaar_id="9876-5432-1009", institution_id="INST-PUNE-COEP", institution_name="COEP Technological University (Demo)", programme_id="BTECH-ECE", programme_name="B.Tech Electronics & Communication", academic_year="2025-2026", admission_cycle="Regular 2025", enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active", seat_category="EWS", source_submission_id="SUB-COEP-2025-01", record_version=1),
        Enrolment(student_ref="STU-DEMO-010", apaar_id="9876-5432-1010", institution_id="INST-TRICHY-NITT", institution_name="National Institute of Technology Trichy (Demo)", programme_id="BTECH-CIVIL", programme_name="B.Tech Civil Engineering", academic_year="2025-2026", admission_cycle="Regular 2025", enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active", seat_category="ST", source_submission_id="SUB-NITT-2025-01", record_version=1)
    ]

    all_students = [s1, s2, s3, s4, s5, s11] + more_students
    all_enrolments = [e1_1, e1_2, e2_1, e2_2, e3_1, e3_2, e4_1, e4_2, e5_1, e5_2, e11] + more_enrolments
    db.add_all(all_students)
    db.flush()
    db.add_all(all_enrolments)
    db.commit()

    print("Seeding Initial Enrolment Version Logs...")
    for e in all_enrolments:
        v = EnrolmentVersion(
            enrolment_id=e.id,
            student_ref=e.student_ref,
            version_number=e.record_version,
            institution_id=e.institution_id,
            programme_id=e.programme_id,
            enrolment_status=e.enrolment_status,
            academic_year=e.academic_year,
            changed_by="Initial State Seed",
            change_reason="Baseline ingestion",
            diff_payload={"status": e.enrolment_status, "category": e.seat_category}
        )
        db.add(v)
    db.commit()

    print("Seeding Approved Intake Rules...")
    intakes = [
        ApprovedIntake(
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University (Demo)",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=120,
            supernumerary_quota=6,
            nri_quota=18,
            rule_id="AICTE-APH-2025-CH4-DTU",
            rule_source="AICTE Approval Process Handbook 2025-26",
            effective_date="2025-04-01",
            rule_configured=True
        ),
        ApprovedIntake(
            institution_id="INST-DELHI-IIITD",
            institution_name="Indraprastha Institute of IT Delhi (Demo)",
            programme_id="BTECH-AIDS",
            programme_name="B.Tech Artificial Intelligence & Data Science",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=60,
            supernumerary_quota=3,
            nri_quota=9,
            rule_id="AICTE-APH-2025-CH4-IIITD",
            rule_source="AICTE Approval Process Handbook 2025-26",
            effective_date="2025-04-01",
            rule_configured=True
        ),
        ApprovedIntake(
            institution_id="INST-PUNE-COEP",
            institution_name="COEP Technological University (Demo)",
            programme_id="BTECH-ECE",
            programme_name="B.Tech Electronics & Communication",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=75,
            supernumerary_quota=4,
            nri_quota=10,
            rule_id="AICTE-APH-2025-CH4-COEP",
            rule_source="AICTE Approval Process Handbook 2025-26",
            effective_date="2025-04-01",
            rule_configured=True
        ),
        ApprovedIntake(
            institution_id="INST-DELHI-NSUT",
            institution_name="Netaji Subhas University of Technology (Demo)",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=120,
            supernumerary_quota=6,
            nri_quota=18,
            rule_id="AICTE-APH-2025-CH4-NSUT",
            rule_source="Pending Verification - State Quota",
            effective_date="2025-04-01",
            rule_configured=False
        )
    ]
    db.add_all(intakes)
    db.commit()

    print("Seeding Historical Intakes and Synthetic Anomalies...")
    hist_dtu = [
        HistoricalIntake(institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2021-2022", admitted_count=120, approved_intake=120, z_score=0.1, pct_change=0.0, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2022-2023", admitted_count=118, approved_intake=120, z_score=-0.8, pct_change=-1.7, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2023-2024", admitted_count=122, approved_intake=120, z_score=0.9, pct_change=3.4, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2024-2025", admitted_count=119, approved_intake=120, z_score=-0.3, pct_change=-2.5, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-DTU", institution_name="Delhi Technological University (Demo)", programme_id="BTECH-CSE", programme_name="B.Tech Computer Science & Engineering", academic_year="2025-2026", admitted_count=120, approved_intake=120, z_score=0.1, pct_change=0.8, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL")
    ]
    hist_iiitd = [
        HistoricalIntake(institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2021-2022", admitted_count=60, approved_intake=60, z_score=-0.4, pct_change=0.0, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2022-2023", admitted_count=59, approved_intake=60, z_score=-0.5, pct_change=-1.7, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2023-2024", admitted_count=62, approved_intake=60, z_score=-0.2, pct_change=5.1, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2024-2025", admitted_count=60, approved_intake=60, z_score=-0.4, pct_change=-3.2, is_anomaly=False, iqr_status="WITHIN_IQR", ground_truth="NORMAL"),
        HistoricalIntake(institution_id="INST-DELHI-IIITD", institution_name="Indraprastha Institute of IT Delhi (Demo)", programme_id="BTECH-AIDS", programme_name="B.Tech Artificial Intelligence & Data Science", academic_year="2025-2026", admitted_count=112, approved_intake=60, z_score=3.85, pct_change=86.7, is_anomaly=True, iqr_status="OUTLIER_HIGH", peer_group_iqr_diff=48.0, ground_truth="ANOMALY", anomaly_explanation="Seeded synthetic anomaly: +86.7% admission surge (Z=3.85) significantly exceeding approved intake cap of 60 seats and peer IQR Q3 of 64 seats.")
    ]
    db.add_all(hist_dtu + hist_iiitd)
    db.commit()

    print("Generating Temporal Integrity Alerts...")
    engine_svc = TemporalIntegrityEngine(db)
    engine_svc.evaluate_all()

    print("Seeding Sample Cryptographic Certificates...")
    payload_valid = {
        "certificate_id": "CERT-APAAR-2026-001",
        "student_ref": "STU-DEMO-001",
        "apaar_id": "9876-5432-1001",
        "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_name": "B.Tech Computer Science & Engineering",
        "completion_date": "2026-05-31",
        "issue_date": "2026-06-15"
    }
    sig_valid = CertificateService.compute_signature(payload_valid)
    cert1 = Certificate(
        certificate_id="CERT-APAAR-2026-001",
        student_ref="STU-DEMO-001",
        apaar_id="9876-5432-1001",
        student_name="Aarav Sharma",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        issue_date="2026-06-15",
        completion_date="2026-05-31",
        status="VALID",
        signature_algorithm="HMAC-SHA256",
        signature_hex=sig_valid,
        public_key_id="SENTINEL-TEST-ROOT-2026",
        payload_json=payload_valid
    )

    payload_revoked = {
        "certificate_id": "CERT-APAAR-2026-002",
        "student_ref": "STU-DEMO-005",
        "apaar_id": "9876-5432-1005",
        "student_name": "Kavya Nair",
        "institution_id": "INST-TRICHY-NITT",
        "institution_name": "National Institute of Technology Trichy (Demo)",
        "programme_name": "B.Tech Civil Engineering",
        "completion_date": "2025-11-15",
        "issue_date": "2025-11-20"
    }
    sig_revoked = CertificateService.compute_signature(payload_revoked)
    cert2 = Certificate(
        certificate_id="CERT-APAAR-2026-002",
        student_ref="STU-DEMO-005",
        apaar_id="9876-5432-1005",
        student_name="Kavya Nair",
        institution_id="INST-TRICHY-NITT",
        institution_name="National Institute of Technology Trichy (Demo)",
        programme_id="BTECH-CIVIL",
        programme_name="B.Tech Civil Engineering",
        issue_date="2025-11-20",
        completion_date="2025-11-15",
        status="REVOKED",
        revocation_reason="Student initiated withdrawal on 2025-11-15; credential invalidated.",
        signature_algorithm="HMAC-SHA256",
        signature_hex=sig_revoked,
        public_key_id="SENTINEL-TEST-ROOT-2026",
        payload_json=payload_revoked
    )
    db.add_all([cert1, cert2])
    db.commit()

    print("Seeding Student Consent Records (DPDP Module)...")
    consents = [
        StudentConsent(student_ref="STU-DEMO-001", apaar_id="9876-5432-1001", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE"),
        StudentConsent(student_ref="STU-DEMO-002", apaar_id="9876-5432-1002", purpose="EMPLOYMENT_VERIFICATION", consent_granted=False, status="WITHDRAWN"),  # Demonstrates consent withdrawal!
        StudentConsent(student_ref="STU-DEMO-003", apaar_id="9876-5432-1003", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE"),
        StudentConsent(student_ref="STU-DEMO-004", apaar_id="9876-5432-1004", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE"),
        StudentConsent(student_ref="STU-DEMO-005", apaar_id="9876-5432-1005", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE"),
        StudentConsent(student_ref="STU-DEMO-011", apaar_id="9876-5432-1011", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE")
    ]
    db.add_all(consents)
    db.commit()

    print("Seeding Approved Verifier Organizations...")
    verifiers = [
        VerifierOrganization(id="ORG-TCS-BGV", org_name="Tata Consultancy Services (BGV Team)", org_type="EMPLOYER", is_approved=True, contact_email="bgv@tcs.com"),
        VerifierOrganization(id="ORG-INFOSYS-VERIFY", org_name="Infosys Ltd Credential Verification", org_type="EMPLOYER", is_approved=True, contact_email="verify@infosys.com"),
        VerifierOrganization(id="ORG-UPSC-REGULATOR", org_name="UPSC Examination Verification Cell", org_type="REGULATOR", is_approved=True, contact_email="director@upsc.gov.in")
    ]
    db.add_all(verifiers)
    db.commit()

    AuditService.log_event(
        db=db,
        entity_type="SYSTEM",
        entity_id="SEED-INIT",
        action="DATABASE_SEEDED",
        performed_by="System Initializer",
        details={"synthetic_records": 11, "consents": 6, "verifiers": 3, "intakes_configured": 4}
    )

    AuthService.seed_demo_users(db)

    try:
        from seed_sjce_population import seed_sjce
        seed_sjce(db)
    except Exception as e:
        print(f"Notice during seed_sjce: {e}")

    print("Seed complete successfully!")
    db.close()

if __name__ == "__main__":
    init_db_and_seed()
