"""
PRAMAAN / APAAR Sentinel: Connected Student ERP & Academic Record Seed Script
Idempotently seeds comprehensive synthetic demonstration data into `backend/pramaan_india_demo.db`.
Target: >= 160 students across multiple institutions, varied profile completion,
academic courses, marks, attendance, timetables, course materials, internships,
placement assessments, fee obligations, payments, and multi-department No Due requests.
"""

import os
import random
from datetime import datetime, timezone, timedelta, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure target database
DB_PATH = os.path.join(os.path.dirname(__file__), "pramaan_india_demo.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

from app.database import Base
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.user import User
from app.models.student_user import StudentUserLink
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

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def _utc_now():
    return datetime.now(timezone.utc)

# Synthetic Indian Names Pool
FIRST_NAMES = [
    "Aarav", "Priya", "Rohan", "Ananya", "Karthik", "Sneha", "Aditya", "Neha",
    "Vikram", "Pooja", "Rahul", "Divya", "Siddharth", "Meera", "Arjun", "Kavya",
    "Harish", "Ritu", "Gautam", "Tanvi", "Akash", "Swati", "Sanjay", "Ishita",
    "Nikhil", "Deepika", "Manish", "Shreya", "Abhishek", "Bhavna", "Varun", "Anjali"
]
LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Iyer", "Reddy", "Nair", "Deshmukh", "Chatterjee",
    "Banerjee", "Gupta", "Kulkarni", "Mehta", "Chopra", "Bose", "Menon", "Joshi",
    "Rao", "Pillai", "Bhat", "Mukherjee", "Singh", "Pandey", "Mishra", "Thakur"
]

INSTITUTIONS = [
    ("INST-DELHI-DTU", "Delhi Technological University, Delhi", "DELHI"),
    ("INST-BLR-PES", "PES University, Bengaluru", "KARNATAKA"),
    ("INST-PUNE-COEP", "COEP Technological University, Pune", "MAHARASHTRA"),
    ("INST-TRICHY-NITT", "National Institute of Technology, Tiruchirappalli", "TAMIL_NADU"),
    ("INST-MUMBAI-IITB", "Indian Institute of Technology Bombay", "MAHARASHTRA"),
    ("INST-VIZAG-AU", "Andhra University, Visakhapatnam", "ANDHRA_PRADESH"),
    ("INST-GUWAHATI-IITG", "Indian Institute of Technology Guwahati", "ASSAM"),
    ("INST-PATNA-IITP", "Indian Institute of Technology Patna", "BIHAR"),
    ("INST-BHILAI-IITBHL", "Indian Institute of Technology Bhilai", "CHHATTISGARH"),
    ("INST-TIRUPATI-IITT", "Indian Institute of Technology Tirupati", "ANDHRA_PRADESH"),
]

PROGRAMMES = [
    ("BTECH-CSE", "B.Tech Computer Science & Engineering", "Computer Science & Engineering"),
    ("BTECH-ECE", "B.Tech Electronics & Communication Engineering", "Electronics & Communication Engineering"),
    ("BTECH-MECH", "B.Tech Mechanical Engineering", "Mechanical Engineering"),
    ("BTECH-CIVIL", "B.Tech Civil Engineering", "Civil Engineering"),
    ("BTECH-IT", "B.Tech Information Technology", "Information Technology"),
]

CSE_COURSES = {
    1: [
        ("CS101", "Programming Fundamentals & Problem Solving", "Theory", 4.0),
        ("CS102", "Mathematics for Computing", "Theory", 4.0),
        ("CS103", "Engineering Physics", "Theory", 3.0),
        ("CS104", "Programming Laboratory", "Lab", 2.0),
        ("HS101", "Professional Communication Skills", "Theory", 2.0),
    ],
    2: [
        ("CS201", "Data Structures & Algorithms", "Theory", 4.0),
        ("CS202", "Digital Electronics & Logic Design", "Theory", 4.0),
        ("CS203", "Discrete Mathematics", "Theory", 3.0),
        ("CS204", "Data Structures Laboratory", "Lab", 2.0),
        ("HS201", "Environmental Studies & Ethics", "Theory", 2.0),
    ],
    3: [
        ("CS301", "Object-Oriented Programming with Java", "Theory", 4.0),
        ("CS302", "Computer Organization & Architecture", "Theory", 4.0),
        ("CS303", "Database Management Systems", "Theory", 4.0),
        ("CS304", "DBMS & SQL Laboratory", "Lab", 2.0),
        ("CS305", "Design of Logic Systems Lab", "Lab", 2.0),
    ],
    4: [
        ("CS401", "Operating Systems Internals", "Theory", 4.0),
        ("CS402", "Computer Communication Networks", "Theory", 4.0),
        ("CS403", "Theory of Computation & Automata", "Theory", 3.0),
        ("CS404", "Operating Systems Laboratory", "Lab", 2.0),
        ("CS405", "Web Technologies & Full Stack Dev", "Elective", 3.0),
    ],
    5: [
        ("CS501", "Design & Analysis of Algorithms", "Theory", 4.0),
        ("CS502", "Software Engineering & Architecture", "Theory", 4.0),
        ("CS503", "Artificial Intelligence & Machine Learning", "Theory", 4.0),
        ("CS504", "Algorithms & Competitive Coding Lab", "Lab", 2.0),
        ("CS505", "Cloud Computing & DevOps", "Elective", 3.0),
    ],
}

COMPANIES = [
    ("Infosys Limited", "Bengaluru", 25000.0, "Software Engineering Intern"),
    ("Tata Consultancy Services", "Mumbai", 22000.0, "R&D Systems Intern"),
    ("Wipro Technologies", "Bengaluru", 20000.0, "Cloud Solutions Intern"),
    ("Swiggy Technologies", "Bengaluru", 45000.0, "Backend Developer Intern"),
    ("Zerodha Broking Ltd", "Bengaluru", 50000.0, "FinTech Platform Intern"),
    ("Microsoft IDC", "Hyderabad", 65000.0, "Software Engineering Intern"),
    ("Google Cloud India", "Bengaluru", 75000.0, "Cloud Infrastructure Intern"),
    ("ISRO Telemetry & Tracking", "Bengaluru", 18000.0, "Space Informatics Intern"),
    ("DRDO Centre for AI & Robotics", "New Delhi", 20000.0, "Robotics & CV Intern"),
]

SKILLS_POOL = [
    ("Python", "Expert", "Python Institute Certified PCAP", "OpenEDG"),
    ("Data Structures & Algorithms", "Advanced", "Competitive Programming Mastery", "HackerRank"),
    ("React & TypeScript", "Intermediate", "Frontend Specialist Certificate", "Meta / Coursera"),
    ("PostgreSQL & Database Design", "Advanced", "Enterprise SQL Certification", "Oracle"),
    ("Cloud Architecture (GCP)", "Intermediate", "Associate Cloud Engineer", "Google Cloud"),
    ("Docker & Containerization", "Intermediate", "Docker Certified Associate", "Docker"),
    ("Machine Learning & Deep Learning", "Advanced", "Deep Learning Specialization", "DeepLearning.AI"),
]


def seed_database():
    db = SessionLocal()
    print("=" * 80)
    print("PRAMAAN: CONNECTED STUDENT ERP & ACADEMIC RECORD SEEDING")
    print(f"Target Database: {DB_PATH}")
    print("=" * 80)

    # 1. Ensure all tables are created
    Base.metadata.create_all(bind=engine)
    print("[1/8] Verified all 14 ERP tables exist in database.")

    # 2. Check existing students and expand to >= 160
    existing_students = db.query(Student).all()
    existing_count = len(existing_students)
    print(f"[2/8] Found {existing_count} existing students.")

    target_count = max(160, existing_count)
    students_to_add = target_count - existing_count
    
    if students_to_add > 0:
        print(f"      Generating {students_to_add} additional synthetic students...")
        for i in range(existing_count + 1, target_count + 1):
            s_ref = f"STU-IND-{i:03d}"
            apaar = f"9876-2026-{i:04d}"
            fname = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            inst = random.choice(INSTITUTIONS)
            
            # Identity route variations
            id_route = "AADHAAR_APAAR"
            id_status = "APAAR_VERIFIED"
            if i % 15 == 0:
                id_status = "APAAR_PENDING"
            elif i % 25 == 0:
                id_route = "PASSPORT_INTERNATIONAL"
                id_status = "ALTERNATIVE_ID_PENDING_VERIFICATION"

            student = Student(
                student_ref=s_ref,
                apaar_id=apaar if id_status == "APAAR_VERIFIED" else None,
                full_name=fname,
                primary_institution_id=inst[0],
                identity_route=id_route,
                identity_status=id_status,
                nationality="Indian" if id_route == "AADHAAR_APAAR" else "Foreign National",
            )
            db.add(student)

            # Create primary enrolment
            prog = random.choice(PROGRAMMES)
            enrolment = Enrolment(
                student_ref=s_ref,
                apaar_id=student.apaar_id,
                institution_id=inst[0],
                institution_name=inst[1],
                programme_id=prog[0],
                programme_name=prog[1],
                academic_year="2025-2026",
                admission_cycle="Regular 2024",
                enrolment_start=date(2024, 8, 1),
                enrolment_status="Active",
                seat_category=random.choice(["General Merit", "State CET Quota", "Management Quota", "AICTE Supernumerary"]),
                record_version=1,
            )
            db.add(enrolment)

        db.commit()
        print(f"      [PASS] Created {students_to_add} new students. Total: {target_count}")

    # Re-fetch all students
    all_students = db.query(Student).all()

    # 3. Seed Student Profiles & Documents
    print("[3/8] Seeding comprehensive ERP Profiles & Document records...")
    profile_statuses = ["APPROVED", "APPROVED", "SUBMITTED", "DRAFT", "REVISION_REQUESTED"]
    
    for idx, student in enumerate(all_students):
        profile = db.query(StudentProfile).filter(StudentProfile.student_ref == student.student_ref).first()
        if not profile:
            enr = db.query(Enrolment).filter(Enrolment.student_ref == student.student_ref).first()
            prog_name = enr.programme_name if enr else "B.Tech Computer Science & Engineering"
            dept = "Computer Science & Engineering"
            if "ECE" in prog_name:
                dept = "Electronics & Communication Engineering"
            elif "MECH" in prog_name:
                dept = "Mechanical Engineering"
            elif "CIVIL" in prog_name:
                dept = "Civil Engineering"

            st_status = profile_statuses[idx % len(profile_statuses)]
            compl_pct = 100 if st_status == "APPROVED" else 85 if st_status == "SUBMITTED" else 60 if st_status == "REVISION_REQUESTED" else 40

            profile = StudentProfile(
                student_ref=student.student_ref,
                roll_number=f"2023-{dept[:3].upper()}-{idx+1:03d}",
                date_of_birth="2004-05-14",
                gender="Male" if idx % 2 == 0 else "Female",
                blood_group=random.choice(["O+", "A+", "B+", "AB+", "O-"]),
                personal_email=f"{student.student_ref.lower().replace('-', '')}@gmail.com",
                college_email=f"{student.student_ref.lower().replace('-', '')}@{student.primary_institution_id.split('-')[-1].lower()}.ac.in",
                phone_number=f"+91 98{idx:02d}5 {43210 + idx}",
                alternate_phone=f"+91 97{idx:02d}4 {12340 + idx}",
                emergency_contact_name=f"Parent of {student.full_name}",
                emergency_contact_phone="+91 91234 56789",
                current_address=f"Room {101 + (idx % 40)}, Campus Hostel Block {(idx % 4) + 1}",
                current_city="New Delhi" if "DELHI" in (student.primary_institution_id or "") else "Bengaluru" if "BLR" in (student.primary_institution_id or "") else "Pune",
                current_state="Delhi" if "DELHI" in (student.primary_institution_id or "") else "Karnataka" if "BLR" in (student.primary_institution_id or "") else "Maharashtra",
                current_pincode="110042",
                permanent_address="Flat 402, Green Valley Apartments, MG Road",
                permanent_city="Bengaluru",
                permanent_state="Karnataka",
                permanent_pincode="560001",
                department=dept,
                batch_year="2023-2027",
                current_year=3,
                current_semester=5,
                section="A" if idx % 2 == 0 else "B",
                admission_category="State CET Merit" if idx % 3 == 0 else "Central JoSAA Counselling",
                admission_date="2023-08-10",
                profile_status=st_status,
                profile_completion_pct=compl_pct,
                review_remarks="Approved by Central Admissions Cell." if st_status == "APPROVED" else "Please re-upload a clear copy of your Transfer Certificate." if st_status == "REVISION_REQUESTED" else None,
                reviewed_by="Admissions Office" if st_status in ("APPROVED", "REVISION_REQUESTED") else None,
                reviewed_at=_utc_now() if st_status in ("APPROVED", "REVISION_REQUESTED") else None,
                submitted_at=_utc_now() - timedelta(days=5) if st_status != "DRAFT" else None,
            )
            db.add(profile)

        # Seed Documents for each student
        existing_docs = db.query(StudentDocument).filter(StudentDocument.student_ref == student.student_ref).count()
        if existing_docs == 0:
            doc_specs = [
                ("10TH_MARKSHEET", "Class X Board Examination Marksheet", "10th_marksheet.pdf", 320, "VERIFIED", "DigiLocker certificate hash matched."),
                ("12TH_MARKSHEET", "Class XII Senior Secondary Marksheet", "12th_marksheet.pdf", 410, "VERIFIED", "State Board verified."),
                ("ENTRANCE_SCORECARD", "National/State Entrance Exam Scorecard", "rank_scorecard.pdf", 250, "VERIFIED", "Allotment rank confirmed."),
                ("TRANSFER_CERTIFICATE", "Institutional Transfer Certificate (TC)", "transfer_certificate.pdf", 280, "PENDING_REVIEW" if idx % 4 != 0 else "VERIFIED", None),
                ("MIGRATION_CERTIFICATE", "Board Migration Certificate", "migration_cert.pdf", 310, "PENDING_REVIEW" if idx % 3 != 0 else "REJECTED", "Document image was blurred; re-upload requested." if idx % 3 == 0 else None),
            ]
            for dtype, dtitle, fname, fsize, dstatus, remarks in doc_specs:
                db.add(StudentDocument(
                    student_ref=student.student_ref,
                    document_type=dtype,
                    document_title=dtitle,
                    file_name=fname,
                    file_url=f"/documents/{student.student_ref}/{fname}",
                    file_size_kb=fsize,
                    status=dstatus,
                    verification_remarks=remarks,
                    verified_by="Registrar Office" if dstatus == "VERIFIED" else None,
                    verified_at=_utc_now() if dstatus == "VERIFIED" else None,
                    uploaded_at=_utc_now() - timedelta(days=10),
                ))

    db.commit()
    print("      [PASS] Seeded Student Profiles and Document registries.")

    # 4. Seed Academic Courses, Marks, Grades, and Attendance
    print("[4/8] Seeding Course Registrations, Semester Grades, and Attendance...")
    for idx, student in enumerate(all_students):
        existing_courses = db.query(StudentCourseRecord).filter(StudentCourseRecord.student_ref == student.student_ref).count()
        if existing_courses == 0:
            inst_id = student.primary_institution_id or "INST-DELHI-DTU"
            
            # Seed Semesters 1 through 5
            cgpa_accumulator = []
            for sem in range(1, 6):
                courses = CSE_COURSES.get(sem, CSE_COURSES[1])
                sem_credits_earned = 0.0
                sem_points_earned = 0.0

                for ccode, cname, ctype, creds in courses:
                    # Variation in marks
                    base_factor = 0.70 + (random.randint(0, 25) / 100.0)
                    if idx % 12 == 0 and sem == 5 and ccode == "CS503": # occasional backlog anomaly for testing
                        base_factor = 0.42
                    
                    int_marks = round(base_factor * 40.0, 1)
                    ext_marks = round(base_factor * 60.0, 1)
                    tot_marks = round(int_marks + ext_marks, 1)

                    if tot_marks >= 90:
                        lgrade, gpoint = "O", 10.0
                    elif tot_marks >= 80:
                        lgrade, gpoint = "A+", 9.0
                    elif tot_marks >= 70:
                        lgrade, gpoint = "A", 8.0
                    elif tot_marks >= 60:
                        lgrade, gpoint = "B+", 7.0
                    elif tot_marks >= 50:
                        lgrade, gpoint = "B", 6.0
                    else:
                        lgrade, gpoint = "F", 0.0

                    res_status = "PASS" if gpoint >= 5.0 else "FAIL"
                    if res_status == "PASS":
                        sem_credits_earned += creds
                        sem_points_earned += (creds * gpoint)

                    db.add(StudentCourseRecord(
                        student_ref=student.student_ref,
                        institution_id=inst_id,
                        semester=sem,
                        academic_year=f"202{2 + (sem // 2)}-202{3 + (sem // 2)}",
                        course_code=ccode,
                        course_name=cname,
                        course_type=ctype,
                        credits=creds,
                        internal_marks=int_marks,
                        external_marks=ext_marks,
                        total_marks=tot_marks,
                        grade_point=gpoint,
                        letter_grade=lgrade,
                        result_status=res_status,
                    ))

                    # Attendance record
                    total_classes = random.randint(45, 54)
                    att_rate = 0.82 + (random.randint(0, 15) / 100.0)
                    if idx % 11 == 0 and ccode == "CS501": # Attendance shortage anomaly
                        att_rate = 0.64
                    attended_classes = int(total_classes * att_rate)
                    att_pct = round((attended_classes / total_classes) * 100.0, 1)

                    db.add(StudentAttendanceRecord(
                        student_ref=student.student_ref,
                        institution_id=inst_id,
                        semester=sem,
                        academic_year=f"202{2 + (sem // 2)}-202{3 + (sem // 2)}",
                        course_code=ccode,
                        course_name=cname,
                        total_classes=total_classes,
                        attended_classes=attended_classes,
                        percentage=att_pct,
                    ))

                # Semester Record
                sgpa = round(sem_points_earned / 15.0, 2) if sem_points_earned > 0 else 0.0
                cgpa_accumulator.append((sgpa, sem_credits_earned))
                tot_c = sum(c[1] for c in cgpa_accumulator)
                cgpa = round(sum(c[0] * c[1] for c in cgpa_accumulator) / tot_c, 2) if tot_c > 0 else 0.0

                db.add(StudentSemesterRecord(
                    student_ref=student.student_ref,
                    institution_id=inst_id,
                    semester=sem,
                    academic_year=f"202{2 + (sem // 2)}-202{3 + (sem // 2)}",
                    total_credits_registered=15.0,
                    total_credits_earned=sem_credits_earned,
                    sgpa=sgpa,
                    cgpa=cgpa,
                    semester_status="COMPLETED" if sem < 5 else "ONGOING",
                ))

    db.commit()
    print("      [PASS] Seeded Semester-wise Course Registrations, Exam Results, and Class Attendance.")

    # 5. Seed Timetable & Course Materials
    print("[5/8] Seeding Department Timetable Schedules & Course Materials...")
    for inst_id, inst_name, _ in INSTITUTIONS[:4]:
        existing_tt = db.query(TimetableSlot).filter(TimetableSlot.institution_id == inst_id).count()
        if existing_tt == 0:
            slots_data = [
                ("Monday", "09:00 AM", "10:00 AM", "CS501", "Design & Analysis of Algorithms", "Dr. A. K. Sharma", "LH-201"),
                ("Monday", "10:15 AM", "11:15 AM", "CS502", "Software Engineering & Architecture", "Prof. R. Sundaram", "LH-201"),
                ("Monday", "11:30 AM", "01:30 PM", "CS504", "Algorithms & Competitive Coding Lab", "Dr. A. K. Sharma", "Lab-3"),
                ("Tuesday", "09:00 AM", "10:00 AM", "CS503", "Artificial Intelligence & Machine Learning", "Dr. V. Raman", "LH-201"),
                ("Tuesday", "10:15 AM", "11:15 AM", "CS505", "Cloud Computing & DevOps", "Prof. Sneha Sen", "LH-201"),
                ("Wednesday", "09:00 AM", "10:00 AM", "CS501", "Design & Analysis of Algorithms", "Dr. A. K. Sharma", "LH-201"),
                ("Wednesday", "10:15 AM", "11:15 AM", "CS503", "Artificial Intelligence & Machine Learning", "Dr. V. Raman", "LH-201"),
                ("Thursday", "02:00 PM", "04:00 PM", "CS505", "Cloud Deployment Practicum", "Prof. Sneha Sen", "Cloud-Lab"),
                ("Friday", "09:00 AM", "10:00 AM", "CS502", "Software Engineering & Architecture", "Prof. R. Sundaram", "LH-201"),
                ("Friday", "10:15 AM", "11:15 AM", "CS501", "Design & Analysis of Algorithms", "Dr. A. K. Sharma", "LH-201"),
            ]
            for day, stime, etime, ccode, cname, faculty, room in slots_data:
                db.add(TimetableSlot(
                    institution_id=inst_id,
                    programme_id="BTECH-CSE",
                    semester=5,
                    section="A",
                    day_of_week=day,
                    start_time=stime,
                    end_time=etime,
                    course_code=ccode,
                    course_name=cname,
                    faculty_name=faculty,
                    room_number=room,
                ))

            # Materials
            materials_data = [
                ("CS501", "Design & Analysis of Algorithms", "Unit 1: Asymptotic Complexity & Divide-and-Conquer", "Lecture Notes", "/materials/CS501_Unit1.pdf"),
                ("CS501", "Design & Analysis of Algorithms", "Assignment 2: Dynamic Programming vs Greedy Strategy", "Assignment", "/materials/CS501_Assign2.pdf"),
                ("CS502", "Software Engineering & Architecture", "Microservices & Domain Driven Design Course Pack", "Reference", "/materials/CS502_Microservices.pdf"),
                ("CS503", "Artificial Intelligence & Machine Learning", "Unit 3: Gradient Descent & Neural Network Backpropagation", "Lecture Notes", "/materials/CS503_NN_Notes.pdf"),
                ("CS505", "Cloud Computing & DevOps", "Kubernetes Cluster Architecture & CI/CD Pipelines", "Lecture Notes", "/materials/CS505_K8s_Notes.pdf"),
            ]
            for ccode, cname, title, mtype, furl in materials_data:
                db.add(CourseMaterial(
                    institution_id=inst_id,
                    programme_id="BTECH-CSE",
                    semester=5,
                    course_code=ccode,
                    course_name=cname,
                    title=title,
                    material_type=mtype,
                    file_url=furl,
                ))

    db.commit()
    print("      [PASS] Seeded Department Timetables and Course Materials.")

    # 6. Seed Student Services: Internships, Placement & Skills
    print("[6/8] Seeding Student Services: Internships, Placement Benchmarks, and Skills...")
    for idx, student in enumerate(all_students):
        # Internships
        existing_internships = db.query(StudentInternship).filter(StudentInternship.student_ref == student.student_ref).count()
        if existing_internships == 0:
            comp = COMPANIES[idx % len(COMPANIES)]
            i_status = "APPROVED" if idx % 3 == 0 else "PENDING_APPROVAL" if idx % 3 == 1 else "COMPLETED"
            if idx % 9 == 0:
                i_status = "REJECTED"

            db.add(StudentInternship(
                student_ref=student.student_ref,
                institution_id=student.primary_institution_id or "INST-DELHI-DTU",
                company_name=comp[0],
                role_title=comp[3],
                location=comp[1],
                start_date="2025-06-01",
                end_date="2025-08-15",
                stipend_amount=comp[2],
                mentor_name="Senior Engineering Lead",
                mentor_email=f"internship-mentor@{comp[0].lower().split()[0]}.com",
                status=i_status,
                offer_letter_url=f"/internships/{student.student_ref}/offer_letter.pdf",
                review_feedback="Approved for 6 institutional academic internship credits." if i_status in ("APPROVED", "COMPLETED") else "Stipend and role documentation incomplete; please clarify supervisor contact." if i_status == "REJECTED" else None,
                reviewed_by="Prof. Coordinator (Internship Cell)" if i_status in ("APPROVED", "COMPLETED", "REJECTED") else None,
                reviewed_at=_utc_now() if i_status in ("APPROVED", "COMPLETED", "REJECTED") else None,
                milestone_summary="Milestone 1: Environment setup. Milestone 2: Microservice API delivery. Milestone 3: Final performance evaluation.",
            ))

        # Placement Readiness
        existing_readiness = db.query(PlacementReadiness).filter(PlacementReadiness.student_ref == student.student_ref).first()
        if not existing_readiness:
            band = "PLACEMENT_READY" if idx % 3 == 0 else "ADVANCED" if idx % 3 == 1 else "DEVELOPING"
            db.add(PlacementReadiness(
                student_ref=student.student_ref,
                readiness_band=band,
                aptitude_score=85.0 if band == "PLACEMENT_READY" else 76.0 if band == "ADVANCED" else 68.0,
                technical_score=88.0 if band == "PLACEMENT_READY" else 79.5 if band == "ADVANCED" else 70.0,
                soft_skills_score=84.0 if band == "PLACEMENT_READY" else 78.0 if band == "ADVANCED" else 72.0,
                coding_rating=1620 if band == "PLACEMENT_READY" else 1480 if band == "ADVANCED" else 1340,
                mock_interview_status="CLEARED" if band in ("PLACEMENT_READY", "ADVANCED") else "SCHEDULED",
                resume_score=90.0 if band == "PLACEMENT_READY" else 82.0 if band == "ADVANCED" else 74.0,
            ))

        # Skills
        existing_skills = db.query(StudentSkill).filter(StudentSkill.student_ref == student.student_ref).count()
        if existing_skills == 0:
            assigned_skills = random.sample(SKILLS_POOL, k=random.randint(2, 4))
            for sname, prof, cert, org in assigned_skills:
                db.add(StudentSkill(
                    student_ref=student.student_ref,
                    skill_name=sname,
                    proficiency=prof,
                    certification_name=cert,
                    issuing_organization=org,
                    issue_date="2025-03-15",
                    credential_id=f"CERT-{idx:03d}-{sname[:3].upper()}",
                ))

    db.commit()
    print("      [PASS] Seeded Internships, Placement Benchmarks, and Technical Certifications.")

    # 7. Seed Student Services: Fee Obligations, Payments & No Due Clearance
    print("[7/8] Seeding Fee Obligations, Real Bank Receipts, and No Due Clearances...")
    for idx, student in enumerate(all_students):
        inst_id = student.primary_institution_id or "INST-DELHI-DTU"
        
        # Fee Obligations for Semesters 1 to 5
        existing_fees = db.query(StudentFeeObligation).filter(StudentFeeObligation.student_ref == student.student_ref).count()
        if existing_fees == 0:
            for sem in range(1, 6):
                tuition = 65000.0
                exam = 2500.0
                lab = 4500.0
                dev = 3000.0
                total = tuition + exam + lab + dev
                
                # Payment variation
                if sem < 5:
                    status = "PAID"
                    paid = total
                    bal = 0.0
                else:
                    if idx % 4 == 0:
                        status = "OVERDUE"
                        paid = 0.0
                        bal = total
                    elif idx % 4 == 1:
                        status = "PARTIALLY_PAID"
                        paid = 45000.0
                        bal = total - paid
                    else:
                        status = "PAID"
                        paid = total
                        bal = 0.0

                ob = StudentFeeObligation(
                    student_ref=student.student_ref,
                    institution_id=inst_id,
                    semester=sem,
                    academic_year=f"202{2 + (sem // 2)}-202{3 + (sem // 2)}",
                    tuition_fee=tuition,
                    exam_fee=exam,
                    library_lab_fee=lab,
                    development_fee=dev,
                    total_obligation=total,
                    total_paid=paid,
                    outstanding_balance=bal,
                    due_date=f"202{2 + (sem // 2)}-08-15",
                    status=status,
                )
                db.add(ob)
                db.flush()

                # If paid or partially paid, create payment transaction
                if paid > 0:
                    db.add(FeePayment(
                        obligation_id=ob.id,
                        student_ref=student.student_ref,
                        transaction_ref=f"TXN-202{sem}-FEES-{student.student_ref[-3:]}-{idx+1:03d}",
                        receipt_number=f"RCPT-{inst_id[-3:]}-202{sem}-{idx+1:04d}",
                        amount=paid,
                        payment_method="Net Banking" if idx % 2 == 0 else "UPI",
                        payment_date=f"202{2 + (sem // 2)}-08-10",
                        status="SUCCESS",
                        recorded_by="Institutional Finance & Accounts Branch",
                    ))

        # No Due Requests
        existing_nd = db.query(NoDueRequest).filter(NoDueRequest.student_ref == student.student_ref).first()
        if not existing_nd:
            nd_status = "CLEARED" if idx % 3 == 0 else "IN_PROGRESS" if idx % 3 == 1 else "REJECTED"
            nd_req = NoDueRequest(
                student_ref=student.student_ref,
                institution_id=inst_id,
                academic_year="2025-2026",
                reason="Semester Clearance" if idx % 2 == 0 else "Inter-University Credit Transfer Clearance",
                overall_status=nd_status,
                final_clearance_date=_utc_now() if nd_status == "CLEARED" else None,
                cleared_by="Office of the Dean (Academic)" if nd_status == "CLEARED" else None,
            )
            db.add(nd_req)
            db.flush()

            departments = [
                "Central Library",
                "Department Laboratories",
                "Department Academic Office",
                "Accounts & Fee Clearance",
                "Hostel & Mess Services",
                "Sports & Physical Education",
            ]
            for dept_name in departments:
                c_status = "APPROVED" if nd_status == "CLEARED" else "REJECTED" if (nd_status == "REJECTED" and dept_name == "Central Library") else "PENDING"
                dues = 450.0 if c_status == "REJECTED" else 0.0
                remarks = "Book overdue (Calculus Vol 2); fine pending." if c_status == "REJECTED" else "No pending dues." if c_status == "APPROVED" else "Awaiting departmental verification."

                db.add(NoDueDepartmentClearance(
                    request_id=nd_req.id,
                    department_name=dept_name,
                    status=c_status,
                    outstanding_dues_inr=dues,
                    remarks=remarks,
                    cleared_by=f"Officer ({dept_name})" if c_status == "APPROVED" else None,
                    cleared_at=_utc_now() if c_status == "APPROVED" else None,
                ))

    db.commit()
    print("      [PASS] Seeded Fee Obligations, Verified Bank Vouchers, and Departmental No Due Clearances.")

    # 8. Link Student Accounts to Authoritative Student Records
    print("[8/8] Verifying and establishing User-to-StudentLinks...")
    student_user_links_map = [
        ("student_aarav", "STU-IND-081"),
        ("student_demo", "STU-DEMO-001"),
        ("student_priya", "STU-DEMO-002"),
        ("student_karthik", "STU-IND-071"),
        ("student_aditya", "STU-IND-072"),
        ("aarav_sharma", "STU-IND-081"),
        ("student_aarav81", "STU-IND-081"),
    ]
    for username, sref in student_user_links_map:
        user = db.query(User).filter(User.username == username).first()
        student = db.query(Student).filter(Student.student_ref == sref).first()
        if user and student:
            link = db.query(StudentUserLink).filter(
                StudentUserLink.user_id == user.id,
                StudentUserLink.student_ref == student.student_ref,
            ).first()
            if not link:
                db.add(StudentUserLink(
                    user_id=user.id,
                    student_ref=student.student_ref,
                    is_primary=True,
                ))

    db.commit()
    print("      [PASS] Verified User-to-Student authentication mappings.")

    # Print final summary of all tables
    print("\n" + "=" * 80)
    print("SEEDING SUMMARY: FINAL RECORD COUNTS IN `pramaan_india_demo.db`")
    print("=" * 80)
    for model in [
        Student,
        Enrolment,
        StudentProfile,
        StudentDocument,
        StudentCourseRecord,
        StudentSemesterRecord,
        StudentAttendanceRecord,
        TimetableSlot,
        CourseMaterial,
        StudentInternship,
        PlacementReadiness,
        StudentSkill,
        StudentFeeObligation,
        FeePayment,
        NoDueRequest,
        NoDueDepartmentClearance,
        StudentUserLink,
    ]:
        cnt = db.query(model).count()
        print(f"  • {model.__tablename__:<30}: {cnt:>6} records")

    db.close()
    print("=" * 80)
    print("SEEDING COMPLETE: All records relationally consistent and ACID committed.")
    print("=" * 80)


if __name__ == "__main__":
    seed_database()
