import sys, os, csv, io
sys.path.insert(0, os.path.abspath("backend"))
from app.database import engine, SessionLocal
from app.services.csv_import_service import StudentCsvImportService
from app.models.import_job import ImportJob

# Add the trigger to the connection
with engine.connect() as conn:
    cols = [c[1] for c in conn.exec_driver_sql("PRAGMA table_info(students)").fetchall()]
    col_str = ", ".join(cols)
    conn.exec_driver_sql(f"""
    CREATE TEMP TRIGGER IF NOT EXISTS students_insert_trig INSTEAD OF INSERT ON students
    BEGIN
        INSERT INTO main.students ({col_str})
        VALUES ({', '.join('NEW.' + c for c in cols)});
    END;
    """)

db = SessionLocal()
csv_text = """student_ref,apaar_id,full_name,institution_id,programme_id,academic_year,admission_cycle,enrolment_start,enrolment_status,seat_category,source_submission_id
STU-DISP-001,9876-5432-8888,Tanya Sen,INST-DELHI-DTU,BTECH-CSE,2025-2026,Regular 2025,2025-08-01,Active,General,BATCH-TEST-01
"""
reader = csv.DictReader(io.StringIO(csv_text))
records = list(reader)
job = ImportJob(id="test-job-debug-2", submitted_by="dtu_registrar", original_filename="test.csv", status="PROCESSING")
db.add(job)
db.commit()

try:
    svc = StudentCsvImportService(db)
    res = svc.process(job, records, None, dry_run=False)
    print("SUCCESS RESULT:", res)
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    db.rollback()
    from app.models.enrolment import Enrolment
    from app.models.student import Student
    db.query(Enrolment).filter(Enrolment.student_ref == "STU-DISP-001").delete()
    db.query(Student).filter(Student.student_ref == "STU-DISP-001").delete()
    db.query(ImportJob).filter(ImportJob.id == "test-job-debug-2").delete()
    db.commit()
