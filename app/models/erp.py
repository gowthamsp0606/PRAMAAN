from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey, Index
from app.database import Base


def _utc_now():
    return datetime.now(timezone.utc)


class StudentProfile(Base):
    """
    Comprehensive institutional ERP profile for a student.
    Contains both student-editable contact/address fields and
    institution-controlled academic affiliation fields.
    """
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), unique=True, nullable=False, index=True)
    
    # Institution-Controlled Affiliation Fields
    roll_number = Column(String(64), nullable=True, index=True)
    date_of_birth = Column(String(32), nullable=True)
    gender = Column(String(16), nullable=True)
    blood_group = Column(String(8), nullable=True)
    college_email = Column(String(128), nullable=True)
    department = Column(String(128), nullable=True)
    batch_year = Column(String(32), nullable=True)
    current_year = Column(Integer, default=1)
    current_semester = Column(Integer, default=1)
    section = Column(String(16), default="A")
    admission_category = Column(String(64), default="State CET Merit")
    admission_date = Column(String(32), nullable=True)
    
    # Student-Editable Fields
    personal_email = Column(String(128), nullable=True)
    phone_number = Column(String(32), nullable=True)
    alternate_phone = Column(String(32), nullable=True)
    emergency_contact_name = Column(String(128), nullable=True)
    emergency_contact_phone = Column(String(32), nullable=True)
    current_address = Column(Text, nullable=True)
    current_city = Column(String(64), nullable=True)
    current_state = Column(String(64), nullable=True)
    current_pincode = Column(String(16), nullable=True)
    permanent_address = Column(Text, nullable=True)
    permanent_city = Column(String(64), nullable=True)
    permanent_state = Column(String(64), nullable=True)
    permanent_pincode = Column(String(16), nullable=True)

    # Verification & Submission Lifecycle
    profile_status = Column(String(32), default="DRAFT", nullable=False) # DRAFT, SUBMITTED, APPROVED, REVISION_REQUESTED
    profile_completion_pct = Column(Integer, default=0, nullable=False)
    review_remarks = Column(Text, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class StudentDocument(Base):
    """
    Mandatory and optional institutional documents uploaded by the student
    and verified by authorized college officials.
    """
    __tablename__ = "student_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    document_type = Column(String(64), nullable=False) # 10TH_MARKSHEET, 12TH_MARKSHEET, TRANSFER_CERTIFICATE, MIGRATION_CERTIFICATE, ENTRANCE_SCORECARD, IDENTITY_PROOF
    document_title = Column(String(128), nullable=False)
    file_name = Column(String(128), nullable=False)
    file_url = Column(String(256), nullable=False)
    file_size_kb = Column(Integer, default=256)
    status = Column(String(32), default="PENDING_REVIEW", nullable=False) # PENDING_REVIEW, VERIFIED, REJECTED
    verification_remarks = Column(Text, nullable=True)
    verified_by = Column(String(128), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    uploaded_at = Column(DateTime, default=_utc_now)


class StudentCourseRecord(Base):
    """
    Authoritative course registration, semester examination marks,
    grade points, and credit allocations.
    """
    __tablename__ = "student_course_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False, index=True)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(32), nullable=False)
    course_code = Column(String(32), nullable=False)
    course_name = Column(String(128), nullable=False)
    course_type = Column(String(32), default="Theory") # Theory, Lab, Elective
    credits = Column(Float, default=4.0)
    internal_marks = Column(Float, default=0.0)
    external_marks = Column(Float, default=0.0)
    total_marks = Column(Float, default=0.0)
    grade_point = Column(Float, default=0.0)
    letter_grade = Column(String(8), default="P")
    result_status = Column(String(16), default="PASS") # PASS, FAIL, IN_PROGRESS
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class StudentSemesterRecord(Base):
    """
    Semester summary containing credits earned, SGPA, and cumulative CGPA.
    """
    __tablename__ = "student_semester_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(32), nullable=False)
    total_credits_registered = Column(Float, default=20.0)
    total_credits_earned = Column(Float, default=20.0)
    sgpa = Column(Float, default=0.0)
    cgpa = Column(Float, default=0.0)
    semester_status = Column(String(32), default="COMPLETED") # COMPLETED, ONGOING
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class StudentAttendanceRecord(Base):
    """
    Course-wise and semester-wise verified class attendance metrics.
    """
    __tablename__ = "student_attendance_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(32), nullable=False)
    course_code = Column(String(32), nullable=False)
    course_name = Column(String(128), nullable=False)
    total_classes = Column(Integer, default=50)
    attended_classes = Column(Integer, default=45)
    percentage = Column(Float, default=90.0)
    last_updated = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class TimetableSlot(Base):
    """
    Institutional timetable slot mapping courses to timings, rooms, and faculty.
    """
    __tablename__ = "academic_timetables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    institution_id = Column(String(64), nullable=False, index=True)
    programme_id = Column(String(32), nullable=False)
    semester = Column(Integer, nullable=False)
    section = Column(String(16), default="A")
    day_of_week = Column(String(16), nullable=False) # Monday - Saturday
    start_time = Column(String(16), nullable=False)
    end_time = Column(String(16), nullable=False)
    course_code = Column(String(32), nullable=False)
    course_name = Column(String(128), nullable=False)
    faculty_name = Column(String(128), nullable=False)
    room_number = Column(String(32), nullable=False)


class CourseMaterial(Base):
    """
    Syllabus, lecture notes, assignments, and reference documents uploaded by faculty.
    """
    __tablename__ = "course_materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    institution_id = Column(String(64), nullable=False, index=True)
    programme_id = Column(String(32), nullable=False)
    semester = Column(Integer, nullable=False)
    course_code = Column(String(32), nullable=False)
    course_name = Column(String(128), nullable=False)
    title = Column(String(128), nullable=False)
    material_type = Column(String(32), default="Lecture Notes") # Lecture Notes, Syllabus, Assignment, Reference
    file_url = Column(String(256), nullable=False)
    uploaded_at = Column(DateTime, default=_utc_now)


class CourseFeedback(Base):
    """
    Student-submitted course and faculty pedagogical feedback.
    """
    __tablename__ = "course_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    course_code = Column(String(32), nullable=False)
    semester = Column(Integer, nullable=False)
    rating = Column(Integer, default=5) # 1 - 5
    comments = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=_utc_now)


class StudentInternship(Base):
    """
    Industrial training and internship records, approvals, milestones, and deliverables.
    """
    __tablename__ = "student_internships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False, index=True)
    company_name = Column(String(128), nullable=False)
    role_title = Column(String(128), nullable=False)
    location = Column(String(128), default="Bengaluru (Hybrid)")
    start_date = Column(String(32), nullable=False)
    end_date = Column(String(32), nullable=False)
    stipend_amount = Column(Float, default=0.0)
    mentor_name = Column(String(128), nullable=True)
    mentor_email = Column(String(128), nullable=True)
    status = Column(String(32), default="PENDING_APPROVAL", nullable=False) # DRAFT, PENDING_APPROVAL, APPROVED, COMPLETED, REJECTED
    offer_letter_url = Column(String(256), nullable=True)
    completion_cert_url = Column(String(256), nullable=True)
    review_feedback = Column(Text, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    milestone_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)


class PlacementReadiness(Base):
    """
    Employability assessments, skill benchmarks, and placement clearance.
    """
    __tablename__ = "placement_readiness"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), unique=True, nullable=False, index=True)
    readiness_band = Column(String(32), default="DEVELOPING") # PLACEMENT_READY, ADVANCED, DEVELOPING, EMERGING
    aptitude_score = Column(Float, default=75.0)
    technical_score = Column(Float, default=80.0)
    soft_skills_score = Column(Float, default=82.0)
    coding_rating = Column(Integer, default=1400)
    mock_interview_status = Column(String(32), default="CLEARED") # CLEARED, SCHEDULED, PENDING
    resume_score = Column(Float, default=85.0)
    assessed_at = Column(DateTime, default=_utc_now)


class StudentSkill(Base):
    """
    Self-reported and verified technical certifications and competencies.
    """
    __tablename__ = "student_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    skill_name = Column(String(64), nullable=False)
    proficiency = Column(String(32), default="Intermediate") # Beginner, Intermediate, Advanced, Expert
    certification_name = Column(String(128), nullable=True)
    issuing_organization = Column(String(128), nullable=True)
    issue_date = Column(String(32), nullable=True)
    credential_id = Column(String(64), nullable=True)


class StudentFeeObligation(Base):
    """
    Semester fee breakdown, statutory dues, and outstanding balances.
    """
    __tablename__ = "student_fee_obligations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False, index=True)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(32), nullable=False)
    tuition_fee = Column(Float, default=65000.0)
    exam_fee = Column(Float, default=2500.0)
    library_lab_fee = Column(Float, default=4500.0)
    development_fee = Column(Float, default=3000.0)
    total_obligation = Column(Float, default=75000.0)
    total_paid = Column(Float, default=75000.0)
    outstanding_balance = Column(Float, default=0.0)
    due_date = Column(String(32), default="2025-08-15")
    status = Column(String(32), default="PAID", nullable=False) # PAID, PARTIALLY_PAID, OVERDUE, PENDING


class FeePayment(Base):
    """
    Verified fee transactions, bank receipts, and institutional finance vouchers.
    """
    __tablename__ = "fee_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    obligation_id = Column(Integer, nullable=False, index=True)
    student_ref = Column(String(64), nullable=False, index=True)
    transaction_ref = Column(String(64), unique=True, nullable=False)
    receipt_number = Column(String(64), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(32), default="UPI") # UPI, Net Banking, NEFT/RTGS, Bank Challan
    payment_date = Column(String(32), nullable=False)
    status = Column(String(32), default="SUCCESS", nullable=False) # SUCCESS, PENDING, FAILED
    recorded_by = Column(String(128), default="Finance Office")


class NoDueRequest(Base):
    """
    Departmental clearance application for semester completion, migration, or graduation.
    """
    __tablename__ = "no_due_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(64), nullable=False, index=True)
    academic_year = Column(String(32), nullable=False)
    reason = Column(String(128), default="Semester Clearance") # Semester Clearance, Transfer / Migration, Graduation
    overall_status = Column(String(32), default="IN_PROGRESS", nullable=False) # INITIATED, IN_PROGRESS, CLEARED, REJECTED
    final_clearance_date = Column(DateTime, nullable=True)
    cleared_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=_utc_now)


class NoDueDepartmentClearance(Base):
    """
    Individual departmental sign-off status for a No Due Request.
    """
    __tablename__ = "no_due_department_clearances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, nullable=False, index=True)
    department_name = Column(String(64), nullable=False) # Library, Laboratory, Department Office, Accounts & Fees, Hostel & Mess, Sports Complex
    status = Column(String(32), default="PENDING", nullable=False) # PENDING, APPROVED, REJECTED
    outstanding_dues_inr = Column(Float, default=0.0)
    remarks = Column(Text, nullable=True)
    cleared_by = Column(String(128), nullable=True)
    cleared_at = Column(DateTime, nullable=True)
