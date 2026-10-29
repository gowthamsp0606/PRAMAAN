"""
PRAMAAN / APAAR Sentinel — India-Wide Synthetic Demonstration Dataset Generator
Generates realistic, interconnected, fictional academic records across all 28 Indian States and 8 Union Territories.

ENVIRONMENT: INDIA — SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL GOVERNMENT DATA
PROTECTION RULE: Strictly refuses to execute against protected database 'apaar_sentinel.db'.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.versioning import EnrolmentVersion
from app.models.alert import Alert
from app.models.review_event import AlertReviewEvent
from app.models.transfer import TransferRequest, TransferStatus
from app.models.intake import ApprovedIntake, HistoricalIntake
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.models.import_job import ImportJob, ImportRowResult
from app.models.audit import AuditLog
from app.models.user import User
from app.models.student_user import StudentUserLink
from app.services.auth_service import AuthService, PasswordHasher
from app.services.certificate_service import CertificateService, ACTIVE_KEY_ID


DEFAULT_TARGET_DB = "pramaan_india_demo.db"


def seed_synthetic_india_data(db_path: str = DEFAULT_TARGET_DB, reseed: bool = False) -> Dict[str, Any]:
    # 1. Mandatory Safety Assertion
    if "apaar_sentinel.db" in str(db_path).lower():
        raise RuntimeError(
            "SAFETY VIOLATION REFUSAL: Synthetic India-wide data generator strictly refuses "
            f"to execute against protected database: '{db_path}'. Target must be a separate demo database."
        )

    db_file = Path(db_path)
    engine_url = f"sqlite:///{db_path}"
    engine = create_engine(engine_url, connect_args={"check_same_thread": False})
    
    # Reseed support: reset demo database schema cleanly
    if reseed and db_file.exists():
        print(f"Reseed requested: dropping and recreating tables in demo database '{db_path}'...")
        Base.metadata.drop_all(bind=engine)

    # Initialize all database tables
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        # Check if already seeded to prevent duplication
        if not reseed and db.query(Student).count() >= 75:
            print(f"Database '{db_path}' already contains full synthetic demonstration dataset.")
            return {
                "status": "ALREADY_SEEDED",
                "database_path": str(db_file.resolve()),
                "students": db.query(Student).count(),
                "institutions": len(set(s[0] for s in db.query(Student.primary_institution_id).distinct() if s[0])),
                "enrolments": db.query(Enrolment).count(),
                "transfers": db.query(TransferRequest).count(),
                "alerts": db.query(Alert).count(),
            }

        print("Generating India-Wide Synthetic Demonstration Dataset (36 States & UTs)...")

        # ---------------------------------------------------------
        # 1. Comprehensive Institutions Catalog (58 Premier Institutions across 36 States/UTs)
        # ---------------------------------------------------------
        institutions_master = [
            # 28 States
            # 1. Andhra Pradesh
            {"id": "INST-TIRUPATI-IITT", "name": "Indian Institute of Technology Tirupati", "state": "ANDHRA_PRADESH", "district": "Tirupati", "type": "Institute of National Importance"},
            {"id": "INST-VIZAG-AU", "name": "Andhra University, Visakhapatnam", "state": "ANDHRA_PRADESH", "district": "Visakhapatnam", "type": "State University"},
            # 2. Arunachal Pradesh
            {"id": "INST-NIRJULI-NERIST", "name": "North Eastern Regional Institute of Science and Technology", "state": "ARUNACHAL_PRADESH", "district": "Papum Pare", "type": "Deemed University"},
            {"id": "INST-YUPIA-NITAP", "name": "National Institute of Technology Arunachal Pradesh", "state": "ARUNACHAL_PRADESH", "district": "Papum Pare", "type": "Institute of National Importance"},
            # 3. Assam
            {"id": "INST-GUWAHATI-IITG", "name": "Indian Institute of Technology Guwahati", "state": "ASSAM", "district": "Kamrup", "type": "Institute of National Importance"},
            {"id": "INST-SILCHAR-NITS", "name": "National Institute of Technology Silchar", "state": "ASSAM", "district": "Cachar", "type": "Institute of National Importance"},
            # 4. Bihar
            {"id": "INST-PATNA-IITP", "name": "Indian Institute of Technology Patna", "state": "BIHAR", "district": "Patna", "type": "Institute of National Importance"},
            {"id": "INST-PATNA-NITP", "name": "National Institute of Technology Patna", "state": "BIHAR", "district": "Patna", "type": "Institute of National Importance"},
            # 5. Chhattisgarh
            {"id": "INST-BHILAI-IITBHL", "name": "Indian Institute of Technology Bhilai", "state": "CHHATTISGARH", "district": "Durg", "type": "Institute of National Importance"},
            {"id": "INST-RAIPUR-NITRR", "name": "National Institute of Technology Raipur", "state": "CHHATTISGARH", "district": "Raipur", "type": "Institute of National Importance"},
            # 6. Goa
            {"id": "INST-GOA-IITGOA", "name": "Indian Institute of Technology Goa", "state": "GOA", "district": "South Goa", "type": "Institute of National Importance"},
            {"id": "INST-PONDA-NITGOA", "name": "National Institute of Technology Goa", "state": "GOA", "district": "Ponda", "type": "Institute of National Importance"},
            # 7. Gujarat
            {"id": "INST-GNAGAR-IITGN", "name": "Indian Institute of Technology Gandhinagar", "state": "GUJARAT", "district": "Gandhinagar", "type": "Institute of National Importance"},
            {"id": "INST-SURAT-SVNIT", "name": "Sardar Vallabhbhai National Institute of Technology, Surat", "state": "GUJARAT", "district": "Surat", "type": "Institute of National Importance"},
            # 8. Haryana
            {"id": "INST-KURUKSHETRA-NITKKR", "name": "National Institute of Technology Kurukshetra", "state": "HARYANA", "district": "Kurukshetra", "type": "Institute of National Importance"},
            {"id": "INST-SONIPAT-IIIT", "name": "Indian Institute of Information Technology Sonipat", "state": "HARYANA", "district": "Sonipat", "type": "Institute of National Importance"},
            # 9. Himachal Pradesh
            {"id": "INST-MANDI-IITMANDI", "name": "Indian Institute of Technology Mandi", "state": "HIMACHAL_PRADESH", "district": "Mandi", "type": "Institute of National Importance"},
            {"id": "INST-HAMIRPUR-NITH", "name": "National Institute of Technology Hamirpur", "state": "HIMACHAL_PRADESH", "district": "Hamirpur", "type": "Institute of National Importance"},
            # 10. Jharkhand
            {"id": "INST-DHANBAD-IITISM", "name": "Indian Institute of Technology (ISM) Dhanbad", "state": "JHARKHAND", "district": "Dhanbad", "type": "Institute of National Importance"},
            {"id": "INST-JAMSHEDPUR-NITJSR", "name": "National Institute of Technology Jamshedpur", "state": "JHARKHAND", "district": "East Singhbhum", "type": "Institute of National Importance"},
            # 11. Karnataka
            {"id": "INST-BLR-IISC", "name": "Indian Institute of Science, Bengaluru", "state": "KARNATAKA", "district": "Bengaluru Urban", "type": "Deemed University / INI"},
            {"id": "INST-BLR-PES", "name": "PES University, Bengaluru", "state": "KARNATAKA", "district": "Bengaluru South", "type": "State Private University"},
            {"id": "INST-DHARWAD-IIT", "name": "Indian Institute of Technology Dharwad", "state": "KARNATAKA", "district": "Dharwad", "type": "Institute of National Importance"},
            # 12. Kerala
            {"id": "INST-CALICUT-NITC", "name": "National Institute of Technology Calicut", "state": "KERALA", "district": "Kozhikode", "type": "Institute of National Importance"},
            {"id": "INST-KOCHI-CUSAT", "name": "Cochin University of Science and Technology", "state": "KERALA", "district": "Ernakulam", "type": "State University"},
            # 13. Madhya Pradesh
            {"id": "INST-INDORE-IITI", "name": "Indian Institute of Technology Indore", "state": "MADHYA_PRADESH", "district": "Indore", "type": "Institute of National Importance"},
            {"id": "INST-BHOPAL-MANIT", "name": "Maulana Azad National Institute of Technology, Bhopal", "state": "MADHYA_PRADESH", "district": "Bhopal", "type": "Institute of National Importance"},
            # 14. Maharashtra
            {"id": "INST-PUNE-COEP", "name": "COEP Technological University, Pune", "state": "MAHARASHTRA", "district": "Pune", "type": "State University"},
            {"id": "INST-MUMBAI-IITB", "name": "Indian Institute of Technology Bombay", "state": "MAHARASHTRA", "district": "Mumbai Suburban", "type": "Institute of National Importance"},
            {"id": "INST-MUMBAI-VJTI", "name": "Veermata Jijabai Technological Institute", "state": "MAHARASHTRA", "district": "Mumbai City", "type": "Autonomous College"},
            # 15. Manipur
            {"id": "INST-IMPHAL-NITMN", "name": "National Institute of Technology Manipur", "state": "MANIPUR", "district": "Imphal West", "type": "Institute of National Importance"},
            {"id": "INST-IMPHAL-IIITM", "name": "Indian Institute of Information Technology Manipur", "state": "MANIPUR", "district": "Imphal East", "type": "Institute of National Importance"},
            # 16. Meghalaya
            {"id": "INST-SHILLONG-NITMG", "name": "National Institute of Technology Meghalaya", "state": "MEGHALAYA", "district": "East Khasi Hills", "type": "Institute of National Importance"},
            {"id": "INST-SHILLONG-NEHU", "name": "North-Eastern Hill University, Shillong", "state": "MEGHALAYA", "district": "East Khasi Hills", "type": "Central University"},
            # 17. Mizoram
            {"id": "INST-AIZAWL-NITMZ", "name": "National Institute of Technology Mizoram", "state": "MIZORAM", "district": "Aizawl", "type": "Institute of National Importance"},
            {"id": "INST-AIZAWL-MZU", "name": "Mizoram University, Aizawl", "state": "MIZORAM", "district": "Aizawl", "type": "Central University"},
            # 18. Nagaland
            {"id": "INST-CHUMU-NITNL", "name": "National Institute of Technology Nagaland", "state": "NAGALAND", "district": "Chümoukedima", "type": "Institute of National Importance"},
            {"id": "INST-KOHIMA-NU", "name": "Nagaland University, Kohima", "state": "NAGALAND", "district": "Kohima", "type": "Central University"},
            # 19. Odisha
            {"id": "INST-BHUB-IITBBS", "name": "Indian Institute of Technology Bhubaneswar", "state": "ODISHA", "district": "Khurda", "type": "Institute of National Importance"},
            {"id": "INST-ROURKELA-NITR", "name": "National Institute of Technology Rourkela", "state": "ODISHA", "district": "Sundargarh", "type": "Institute of National Importance"},
            # 20. Punjab
            {"id": "INST-ROPAR-IITRPR", "name": "Indian Institute of Technology Ropar", "state": "PUNJAB", "district": "Rupnagar", "type": "Institute of National Importance"},
            {"id": "INST-JALANDHAR-NITJ", "name": "Dr. B.R. Ambedkar National Institute of Technology Jalandhar", "state": "PUNJAB", "district": "Jalandhar", "type": "Institute of National Importance"},
            # 21. Rajasthan
            {"id": "INST-JAIPUR-MNIT", "name": "Malaviya National Institute of Technology, Jaipur", "state": "RAJASTHAN", "district": "Jaipur", "type": "Institute of National Importance"},
            {"id": "INST-JODHPUR-IITJ", "name": "Indian Institute of Technology Jodhpur", "state": "RAJASTHAN", "district": "Jodhpur", "type": "Institute of National Importance"},
            {"id": "INST-PILANI-BITS", "name": "BITS Pilani, Pilani Campus", "state": "RAJASTHAN", "district": "Jhunjhunu", "type": "Deemed University"},
            # 22. Sikkim
            {"id": "INST-RAVANGLA-NITS", "name": "National Institute of Technology Sikkim", "state": "SIKKIM", "district": "South Sikkim", "type": "Institute of National Importance"},
            {"id": "INST-MAJITAR-SMIT", "name": "Sikkim Manipal Institute of Technology", "state": "SIKKIM", "district": "East Sikkim", "type": "Private University"},
            # 23. Tamil Nadu
            {"id": "INST-TRICHY-NITT", "name": "National Institute of Technology, Tiruchirappalli", "state": "TAMIL_NADU", "district": "Tiruchirappalli", "type": "Institute of National Importance"},
            {"id": "INST-CHENNAI-IITM", "name": "Indian Institute of Technology Madras", "state": "TAMIL_NADU", "district": "Chennai", "type": "Institute of National Importance"},
            {"id": "INST-CHENNAI-ANNA", "name": "Anna University, Chennai", "state": "TAMIL_NADU", "district": "Chennai", "type": "State University"},
            # 24. Telangana
            {"id": "INST-HYD-IITH", "name": "Indian Institute of Technology Hyderabad", "state": "TELANGANA", "district": "Sangareddy", "type": "Institute of National Importance"},
            {"id": "INST-HYD-JNTU", "name": "Jawaharlal Nehru Technological University, Hyderabad", "state": "TELANGANA", "district": "Hyderabad", "type": "State University"},
            # 25. Tripura
            {"id": "INST-AGARTALA-NITA", "name": "National Institute of Technology Agartala", "state": "TRIPURA", "district": "West Tripura", "type": "Institute of National Importance"},
            {"id": "INST-AGARTALA-IIITT", "name": "Indian Institute of Information Technology Tripura", "state": "TRIPURA", "district": "West Tripura", "type": "Institute of National Importance"},
            # 26. Uttar Pradesh
            {"id": "INST-KANPUR-IITK", "name": "Indian Institute of Technology Kanpur", "state": "UTTAR_PRADESH", "district": "Kanpur Nagar", "type": "Institute of National Importance"},
            {"id": "INST-VARANASI-BHU", "name": "Indian Institute of Technology (BHU) Varanasi", "state": "UTTAR_PRADESH", "district": "Varanasi", "type": "Central University / INI"},
            # 27. Uttarakhand
            {"id": "INST-ROORKEE-IITR", "name": "Indian Institute of Technology Roorkee", "state": "UTTARAKHAND", "district": "Haridwar", "type": "Institute of National Importance"},
            {"id": "INST-SRINAGAR-NITUK", "name": "National Institute of Technology Uttarakhand", "state": "UTTARAKHAND", "district": "Pauri Garhwal", "type": "Institute of National Importance"},
            # 28. West Bengal
            {"id": "INST-KGP-IITKGP", "name": "Indian Institute of Technology Kharagpur", "state": "WEST_BENGAL", "district": "Paschim Medinipur", "type": "Institute of National Importance"},
            {"id": "INST-KOLKATA-JU", "name": "Jadavpur University, Kolkata", "state": "WEST_BENGAL", "district": "Kolkata", "type": "State University"},

            # 8 Union Territories
            # 1. Andaman and Nicobar Islands
            {"id": "INST-PORTBLAIR-DBRAIT", "name": "Dr. B. R. Ambedkar Institute of Technology", "state": "ANDAMAN_AND_NICOBAR", "district": "South Andaman", "type": "Government Autonomous College"},
            # 2. Chandigarh
            {"id": "INST-CHANDIGARH-PEC", "name": "Punjab Engineering College (Deemed to be University)", "state": "CHANDIGARH", "district": "Chandigarh", "type": "Deemed University"},
            # 3. Dadra and Nagar Haveli and Daman and Diu
            {"id": "INST-SILVASSA-GEC", "name": "Government Engineering College, Silvassa", "state": "DADRA_NAGAR_DAMAN_DIU", "district": "Dadra and Nagar Haveli", "type": "Government College"},
            # 4. Delhi
            {"id": "INST-DELHI-DTU", "name": "Delhi Technological University", "state": "DELHI", "district": "North West Delhi", "type": "State University"},
            {"id": "INST-DELHI-IIITD", "name": "Indraprastha Institute of Information Technology Delhi", "state": "DELHI", "district": "South East Delhi", "type": "State University"},
            {"id": "INST-DELHI-NSUT", "name": "Netaji Subhas University of Technology", "state": "DELHI", "district": "South West Delhi", "type": "State University"},
            {"id": "INST-DELHI-IITD", "name": "Indian Institute of Technology Delhi", "state": "DELHI", "district": "South Delhi", "type": "Institute of National Importance"},
            # 5. Jammu and Kashmir
            {"id": "INST-SRINAGAR-NITSRI", "name": "National Institute of Technology Srinagar", "state": "JAMMU_AND_KASHMIR", "district": "Srinagar", "type": "Institute of National Importance"},
            {"id": "INST-JAMMU-IITJMU", "name": "Indian Institute of Technology Jammu", "state": "JAMMU_AND_KASHMIR", "district": "Jammu", "type": "Institute of National Importance"},
            # 6. Ladakh
            {"id": "INST-LEH-UOL", "name": "University of Ladakh", "state": "LADAKH", "district": "Leh", "type": "State University"},
            # 7. Lakshadweep
            {"id": "INST-KAVARATTI-GPC", "name": "Government Polytechnic College, Kavaratti", "state": "LAKSHADWEEP", "district": "Kavaratti", "type": "Government Polytechnic"},
            # 8. Puducherry
            {"id": "INST-KARAIDIKAL-NITPY", "name": "National Institute of Technology Puducherry", "state": "PUDUCHERRY", "district": "Karaikal", "type": "Institute of National Importance"},
            {"id": "INST-PUDUCHERRY-PEC", "name": "Pondicherry Engineering College", "state": "PUDUCHERRY", "district": "Puducherry", "type": "State University"},
        ]

        # ---------------------------------------------------------
        # 2. Approved & Historical Intake Rules
        # ---------------------------------------------------------
        programmes_master = [
            ("BTECH-CSE", "B.Tech Computer Science & Engineering", 120),
            ("BTECH-ECE", "B.Tech Electronics & Communication Engineering", 90),
            ("BTECH-MECH", "B.Tech Mechanical Engineering", 60),
            ("MTECH-AI", "M.Tech Artificial Intelligence & Robotics", 30),
            ("BSC-DATA", "B.Sc Data Science & Analytics", 60),
        ]

        for inst in institutions_master:
            for p_code, p_name, seats in programmes_master:
                db.add(ApprovedIntake(
                    institution_id=inst["id"],
                    institution_name=inst["name"],
                    programme_id=p_code,
                    programme_name=p_name,
                    academic_year="2025-2026",
                    admission_cycle="Regular 2025",
                    approved_intake_seats=seats,
                    supernumerary_quota=int(seats * 0.15),
                    nri_quota=int(seats * 0.05),
                    rule_configured=True,
                    rule_id=f"AICTE-APH-2025-{inst['state'][:3]}-{p_code[:3]}",
                    rule_source="AICTE Approval Process Handbook (Synthetic Demo Model)",
                    effective_date="2025-04-01",
                ))

                # Multi-year historical cohorts
                base_admitted = int(seats * 0.95)
                for yr_offset, acad_yr in enumerate(["2022-2023", "2023-2024", "2024-2025"]):
                    admitted = base_admitted + (yr_offset * 2)
                    db.add(HistoricalIntake(
                        institution_id=inst["id"],
                        institution_name=inst["name"],
                        programme_id=p_code,
                        programme_name=p_name,
                        academic_year=acad_yr,
                        admitted_count=admitted,
                        approved_intake=seats,
                        z_score=0.45,
                        pct_change=2.1,
                        is_anomaly=False,
                        ground_truth="NORMAL",
                    ))

        # ---------------------------------------------------------
        # 3. Diverse Student Profiles across all 36 States & UTs (82 Students)
        # ---------------------------------------------------------
        student_blueprints = [
            # 1. Andhra Pradesh
            ("Vamsi Krishna", "INST-TIRUPATI-IITT", "BTECH-CSE", "Regular 2024", "ANDHRA_PRADESH"),
            ("Sai Teja", "INST-VIZAG-AU", "BTECH-ECE", "Regular 2025", "ANDHRA_PRADESH"),
            # 2. Arunachal Pradesh
            ("Tenzin Dorjee", "INST-NIRJULI-NERIST", "BTECH-CSE", "Regular 2024", "ARUNACHAL_PRADESH"),
            ("Oken Tayeng", "INST-YUPIA-NITAP", "BTECH-MECH", "Regular 2025", "ARUNACHAL_PRADESH"),
            # 3. Assam
            ("Debojit Barman", "INST-GUWAHATI-IITG", "BTECH-CSE", "Regular 2023", "ASSAM"),
            ("Jonali Saikia", "INST-SILCHAR-NITS", "BSC-DATA", "Regular 2025", "ASSAM"),
            # 4. Bihar
            ("Alok Kumar", "INST-PATNA-IITP", "BTECH-CSE", "Regular 2024", "BIHAR"),
            ("Shweta Kumari", "INST-PATNA-NITP", "BTECH-ECE", "Regular 2025", "BIHAR"),
            # 5. Chhattisgarh
            ("Devendra Sahu", "INST-BHILAI-IITBHL", "BTECH-CSE", "Regular 2024", "CHHATTISGARH"),
            ("Priya Netam", "INST-RAIPUR-NITRR", "BTECH-MECH", "Regular 2025", "CHHATTISGARH"),
            # 6. Goa
            ("Ashley Fernandes", "INST-GOA-IITGOA", "BTECH-CSE", "Regular 2024", "GOA"),
            ("Sanjana Naik", "INST-PONDA-NITGOA", "BSC-DATA", "Regular 2025", "GOA"),
            # 7. Gujarat
            ("Harsh Patel", "INST-GNAGAR-IITGN", "BTECH-CSE", "Regular 2024", "GUJARAT"),
            ("Kruti Shah", "INST-SURAT-SVNIT", "BTECH-ECE", "Regular 2024", "GUJARAT"),
            ("Bhavik Mehta", "INST-GNAGAR-IITGN", "MTECH-AI", "Regular 2025", "GUJARAT"),
            # 8. Haryana
            ("Vikas Dhull", "INST-KURUKSHETRA-NITKKR", "BTECH-CSE", "Regular 2024", "HARYANA"),
            ("Simran Yadav", "INST-SONIPAT-IIIT", "BTECH-ECE", "Regular 2025", "HARYANA"),
            # 9. Himachal Pradesh
            ("Rohit Sharma", "INST-MANDI-IITMANDI", "BTECH-CSE", "Regular 2024", "HIMACHAL_PRADESH"),
            ("Ankita Thakur", "INST-HAMIRPUR-NITH", "BSC-DATA", "Regular 2025", "HIMACHAL_PRADESH"),
            # 10. Jharkhand
            ("Ritesh Soren", "INST-DHANBAD-IITISM", "BTECH-CSE", "Regular 2023", "JHARKHAND"),
            ("Preeti Murmu", "INST-JAMSHEDPUR-NITJSR", "BTECH-ECE", "Regular 2025", "JHARKHAND"),
            # 11. Karnataka
            ("Varun Gowda", "INST-BLR-PES", "BTECH-CSE", "Regular 2024", "KARNATAKA"),
            ("Shreya Rao", "INST-BLR-IISC", "MTECH-AI", "Regular 2023", "KARNATAKA"),
            ("Chethan Hegde", "INST-DHARWAD-IIT", "BTECH-ECE", "Regular 2025", "KARNATAKA"),
            ("Divya Nayak", "INST-BLR-PES", "BSC-DATA", "Regular 2025", "KARNATAKA"),
            ("Pavan Kumar", "INST-BLR-PES", "BTECH-MECH", "Regular 2024", "KARNATAKA"),
            # 12. Kerala
            ("Jithin Thomas", "INST-CALICUT-NITC", "BTECH-CSE", "Regular 2024", "KERALA"),
            ("Anjali Menon", "INST-KOCHI-CUSAT", "BTECH-ECE", "Regular 2025", "KERALA"),
            ("Rahul Nair", "INST-CALICUT-NITC", "BSC-DATA", "Regular 2024", "KERALA"),
            # 13. Madhya Pradesh
            ("Shivam Chouhan", "INST-INDORE-IITI", "BTECH-CSE", "Regular 2024", "MADHYA_PRADESH"),
            ("Ritu Baghel", "INST-BHOPAL-MANIT", "BTECH-ECE", "Regular 2025", "MADHYA_PRADESH"),
            # 14. Maharashtra
            ("Aditya Deshmukh", "INST-PUNE-COEP", "BTECH-CSE", "Regular 2024", "MAHARASHTRA"),
            ("Tanvi Joshi", "INST-PUNE-COEP", "BTECH-ECE", "Regular 2024", "MAHARASHTRA"),
            ("Prathamesh Patil", "INST-MUMBAI-IITB", "BTECH-CSE", "Regular 2023", "MAHARASHTRA"),
            ("Sneha Kulkarni", "INST-MUMBAI-VJTI", "BTECH-MECH", "Regular 2025", "MAHARASHTRA"),
            ("Omkar Shinde", "INST-PUNE-COEP", "BSC-DATA", "Regular 2025", "MAHARASHTRA"),
            ("Gauri Gokhale", "INST-MUMBAI-IITB", "MTECH-AI", "Regular 2024", "MAHARASHTRA"),
            # 15. Manipur
            ("Ronit Meitei", "INST-IMPHAL-NITMN", "BTECH-CSE", "Regular 2024", "MANIPUR"),
            ("Linthoingambi Devi", "INST-IMPHAL-IIITM", "BTECH-ECE", "Regular 2025", "MANIPUR"),
            # 16. Meghalaya
            ("Banrilang Marbaniang", "INST-SHILLONG-NITMG", "BTECH-CSE", "Regular 2024", "MEGHALAYA"),
            ("Eric Nongrum", "INST-SHILLONG-NEHU", "BSC-DATA", "Regular 2025", "MEGHALAYA"),
            # 17. Mizoram
            ("Lalduhawma Sailo", "INST-AIZAWL-NITMZ", "BTECH-CSE", "Regular 2024", "MIZORAM"),
            ("Vanlalruati", "INST-AIZAWL-MZU", "BTECH-ECE", "Regular 2025", "MIZORAM"),
            # 18. Nagaland
            ("Alem Ao", "INST-CHUMU-NITNL", "BTECH-CSE", "Regular 2024", "NAGALAND"),
            ("Kevisezo Angami", "INST-KOHIMA-NU", "BSC-DATA", "Regular 2025", "NAGALAND"),
            # 19. Odisha
            ("Subrat Nayak", "INST-BHUB-IITBBS", "BTECH-CSE", "Regular 2024", "ODISHA"),
            ("Lipsa Mohanty", "INST-ROURKELA-NITR", "BTECH-ECE", "Regular 2025", "ODISHA"),
            # 20. Punjab
            ("Harpreet Singh", "INST-ROPAR-IITRPR", "BTECH-CSE", "Regular 2024", "PUNJAB"),
            ("Jasleen Kaur", "INST-JALANDHAR-NITJ", "BTECH-ECE", "Regular 2025", "PUNJAB"),
            # 21. Rajasthan
            ("Vikram Singh Rathore", "INST-JAIPUR-MNIT", "BTECH-CSE", "Regular 2024", "RAJASTHAN"),
            ("Pooja Choudhary", "INST-JAIPUR-MNIT", "BTECH-ECE", "Regular 2025", "RAJASTHAN"),
            # 22. Sikkim
            ("Karma Bhutia", "INST-RAVANGLA-NITS", "BTECH-CSE", "Regular 2024", "SIKKIM"),
            ("Dawa Lepcha", "INST-MAJITAR-SMIT", "BTECH-ECE", "Regular 2025", "SIKKIM"),
            # 23. Tamil Nadu
            ("Karthik Subramanian", "INST-TRICHY-NITT", "BTECH-CSE", "Regular 2024", "TAMIL_NADU"),
            ("Meera Venkatraman", "INST-CHENNAI-IITM", "BTECH-ECE", "Regular 2023", "TAMIL_NADU"),
            ("Vignesh Balaji", "INST-CHENNAI-ANNA", "BTECH-CSE", "Regular 2025", "TAMIL_NADU"),
            ("Deepa Natarajan", "INST-TRICHY-NITT", "MTECH-AI", "Regular 2024", "TAMIL_NADU"),
            ("Senthil Kumar", "INST-CHENNAI-ANNA", "BTECH-MECH", "Regular 2024", "TAMIL_NADU"),
            ("Lavanya Sundaram", "INST-CHENNAI-IITM", "BSC-DATA", "Regular 2025", "TAMIL_NADU"),
            # 24. Telangana
            ("Sai Krishna Reddy", "INST-HYD-IITH", "BTECH-CSE", "Regular 2023", "TELANGANA"),
            ("Ramya Teja", "INST-HYD-JNTU", "BTECH-ECE", "Regular 2024", "TELANGANA"),
            ("Harish Varma", "INST-HYD-IITH", "MTECH-AI", "Regular 2024", "TELANGANA"),
            ("Sravani Challa", "INST-HYD-JNTU", "BSC-DATA", "Regular 2025", "TELANGANA"),
            # 25. Tripura
            ("Bishal Debbarma", "INST-AGARTALA-NITA", "BTECH-CSE", "Regular 2024", "TRIPURA"),
            ("Barnali Saha", "INST-AGARTALA-IIITT", "BTECH-ECE", "Regular 2025", "TRIPURA"),
            # 26. Uttar Pradesh
            ("Utkarsh Tiwari", "INST-KANPUR-IITK", "BTECH-CSE", "Regular 2023", "UTTAR_PRADESH"),
            ("Shambhavi Mishra", "INST-VARANASI-BHU", "BTECH-ECE", "Regular 2024", "UTTAR_PRADESH"),
            ("Alok Pandey", "INST-KANPUR-IITK", "MTECH-AI", "Regular 2024", "UTTAR_PRADESH"),
            ("Renu Srivastava", "INST-VARANASI-BHU", "BSC-DATA", "Regular 2025", "UTTAR_PRADESH"),
            # 27. Uttarakhand
            ("Deepanshu Rawat", "INST-ROORKEE-IITR", "BTECH-CSE", "Regular 2024", "UTTARAKHAND"),
            ("Neha Joshi", "INST-SRINAGAR-NITUK", "BTECH-ECE", "Regular 2025", "UTTARAKHAND"),
            # 28. West Bengal
            ("Sourav Banerjee", "INST-KGP-IITKGP", "BTECH-CSE", "Regular 2023", "WEST_BENGAL"),
            ("Debolina Mukherjee", "INST-KOLKATA-JU", "BTECH-ECE", "Regular 2024", "WEST_BENGAL"),
            ("Anirban Sen", "INST-KGP-IITKGP", "MTECH-AI", "Regular 2024", "WEST_BENGAL"),

            # 8 Union Territories
            # 1. Andaman and Nicobar Islands
            ("Joshua Daniel", "INST-PORTBLAIR-DBRAIT", "BTECH-CSE", "Regular 2024", "ANDAMAN_AND_NICOBAR"),
            ("Maya Roy", "INST-PORTBLAIR-DBRAIT", "BSC-DATA", "Regular 2025", "ANDAMAN_AND_NICOBAR"),
            # 2. Chandigarh
            ("Raghav Bhasin", "INST-CHANDIGARH-PEC", "BTECH-CSE", "Regular 2024", "CHANDIGARH"),
            ("Navneet Walia", "INST-CHANDIGARH-PEC", "BTECH-ECE", "Regular 2025", "CHANDIGARH"),
            # 3. Dadra and Nagar Haveli and Daman and Diu
            ("Chirag Patel", "INST-SILVASSA-GEC", "BTECH-MECH", "Regular 2024", "DADRA_NAGAR_DAMAN_DIU"),
            ("Dipti Solanki", "INST-SILVASSA-GEC", "BTECH-ECE", "Regular 2025", "DADRA_NAGAR_DAMAN_DIU"),
            # 4. Delhi (NCT)
            ("Aarav Sharma", "INST-DELHI-DTU", "BTECH-CSE", "Regular 2024", "DELHI"),
            ("Priya Patel", "INST-DELHI-IIITD", "BTECH-CSE", "Regular 2024", "DELHI"),
            ("Rohan Verma", "INST-DELHI-NSUT", "BTECH-ECE", "Regular 2025", "DELHI"),
            ("Ananya Gupta", "INST-DELHI-DTU", "BSC-DATA", "Regular 2025", "DELHI"),
            ("Ishaan Malhotra", "INST-DELHI-IITD", "BTECH-CSE", "Regular 2023", "DELHI"),
            ("Kavya Singhania", "INST-DELHI-IITD", "MTECH-AI", "Regular 2024", "DELHI"),
            # 5. Jammu and Kashmir
            ("Farhan Mir", "INST-SRINAGAR-NITSRI", "BTECH-CSE", "Regular 2024", "JAMMU_AND_KASHMIR"),
            ("Ishrat Wani", "INST-SRINAGAR-NITSRI", "BTECH-ECE", "Regular 2025", "JAMMU_AND_KASHMIR"),
            ("Mohit Raina", "INST-JAMMU-IITJMU", "BSC-DATA", "Regular 2025", "JAMMU_AND_KASHMIR"),
            # 6. Ladakh
            ("Stanzin Norboo", "INST-LEH-UOL", "BTECH-CSE", "Regular 2024", "LADAKH"),
            ("Rigzin Angmo", "INST-LEH-UOL", "BSC-DATA", "Regular 2025", "LADAKH"),
            # 7. Lakshadweep
            ("Mohammed Aslam", "INST-KAVARATTI-GPC", "BTECH-MECH", "Regular 2024", "LAKSHADWEEP"),
            ("Fathima Rauf", "INST-KAVARATTI-GPC", "BTECH-ECE", "Regular 2025", "LAKSHADWEEP"),
            # 8. Puducherry
            ("Muthu Kumaran", "INST-KARAIDIKAL-NITPY", "BTECH-CSE", "Regular 2024", "PUDUCHERRY"),
            ("Anitha Selvam", "INST-PUDUCHERRY-PEC", "BTECH-ECE", "Regular 2025", "PUDUCHERRY"),
            # Reconcile Rajasthan Premier Institutions: Ensure active enrolments across all 73 institutions
            ("Kavita Shekhawat", "INST-JODHPUR-IITJ", "BTECH-CSE", "Regular 2024", "RAJASTHAN"),
            ("Manish Maheshwari", "INST-PILANI-BITS", "BTECH-ECE", "Regular 2024", "RAJASTHAN"),
        ]

        created_students = []
        for idx, (name, inst_id, prog_code, adm_cycle, state) in enumerate(student_blueprints):
            stu_num = idx + 1
            stu_ref = f"STU-IND-{stu_num:03d}"
            apaar_id = f"9876-2026-{stu_num:04d}"

            student = Student(
                student_ref=stu_ref,
                apaar_id=apaar_id,
                full_name=name,
                primary_institution_id=inst_id,
                identity_route="AADHAAR_APAAR",
                identity_status="APAAR_VERIFIED",
                nationality="Indian",
                is_nri=False,
                is_oci=False,
                is_foreign_national=False,
            )
            db.add(student)
            created_students.append(student)

            # Primary Enrolment
            enrolment = Enrolment(
                student_ref=stu_ref,
                apaar_id=apaar_id,
                institution_id=inst_id,
                institution_name=next(inst["name"] for inst in institutions_master if inst["id"] == inst_id),
                programme_id=prog_code,
                programme_name=next(p[1] for p in programmes_master if p[0] == prog_code),
                academic_year="2025-2026",
                admission_cycle=adm_cycle,
                enrolment_start=date(2025, 8, 1),
                enrolment_end=None,
                enrolment_status="Active",
                seat_category="General Merit",
                record_version=1,
            )
            db.add(enrolment)
            db.flush()

            # Enrolment Version record
            db.add(EnrolmentVersion(
                enrolment_id=enrolment.id,
                student_ref=stu_ref,
                version_number=1,
                institution_id=inst_id,
                programme_id=prog_code,
                enrolment_status="Active",
                academic_year="2025-2026",
                changed_by="system_seeder",
                change_reason="Initial admission matriculation",
                diff_payload={"status": "Active", "year": "2025-2026"},
            ))

            # DPDP Consent records for each student
            for purpose in ["EMPLOYMENT_VERIFICATION", "AICTE_AUDIT", "CREDIT_MOBILITY", "SCHOLARSHIP"]:
                db.add(StudentConsent(
                    student_ref=stu_ref,
                    apaar_id=apaar_id,
                    purpose=purpose,
                    consent_granted=True if idx % 10 != 0 else False,
                    status="ACTIVE" if idx % 10 != 0 else "WITHDRAWN",
                    data_scope="NAME_PROGRAMME_COMPLETION_ONLY",
                    granted_at=datetime.utcnow() - timedelta(days=60),
                ))

        # ---------------------------------------------------------
        # 4. Cross-State and Intra-State Transfers (20 Transfers)
        # ---------------------------------------------------------
        transfer_specs = [
            # Delhi -> Maharashtra (Completed)
            ("STU-IND-071", "INST-DELHI-DTU", "DELHI", "INST-PUNE-COEP", "MAHARASHTRA", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-DELHI-DTU-0101"),
            # Tamil Nadu -> Delhi (Released)
            ("STU-IND-053", "INST-TRICHY-NITT", "TAMIL_NADU", "INST-DELHI-DTU", "DELHI", "BTECH-CSE", TransferStatus.RELEASED, "NOC-TRICHY-NITT-0102"),
            # Maharashtra -> West Bengal (Pending Admission)
            ("STU-IND-032", "INST-MUMBAI-IITB", "MAHARASHTRA", "INST-KGP-IITKGP", "WEST_BENGAL", "BTECH-CSE", TransferStatus.PENDING_ADMISSION, "NOC-MUMBAI-IITB-0103"),
            # Karnataka -> Telangana (Pending Release)
            ("STU-IND-020", "INST-BLR-PES", "KARNATAKA", "INST-HYD-IITH", "TELANGANA", "BTECH-CSE", TransferStatus.PENDING_RELEASE, None),
            # Uttar Pradesh -> Delhi (Completed)
            ("STU-IND-064", "INST-KANPUR-IITK", "UTTAR_PRADESH", "INST-DELHI-IITD", "DELHI", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-KANPUR-IITK-0105"),
            # Gujarat -> Gujarat (Released)
            ("STU-IND-014", "INST-SURAT-SVNIT", "GUJARAT", "INST-GNAGAR-IITGN", "GUJARAT", "BTECH-ECE", TransferStatus.RELEASED, "NOC-SURAT-SVNIT-0106"),
            # West Bengal -> Tamil Nadu (Rejected)
            ("STU-IND-070", "INST-KOLKATA-JU", "WEST_BENGAL", "INST-CHENNAI-IITM", "TAMIL_NADU", "BTECH-ECE", TransferStatus.REJECTED, None),
            # Kerala -> Maharashtra (Cancelled)
            ("STU-IND-025", "INST-CALICUT-NITC", "KERALA", "INST-PUNE-COEP", "MAHARASHTRA", "BTECH-CSE", TransferStatus.CANCELLED, None),
            # Rajasthan -> Delhi (Completed)
            ("STU-IND-049", "INST-JAIPUR-MNIT", "RAJASTHAN", "INST-DELHI-DTU", "DELHI", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-JAIPUR-MNIT-0109"),
            # Tamil Nadu -> Tamil Nadu (Intra-state Completed)
            ("STU-IND-055", "INST-CHENNAI-ANNA", "TAMIL_NADU", "INST-TRICHY-NITT", "TAMIL_NADU", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-CHENNAI-ANNA-0110"),
            # Maharashtra -> Maharashtra (Intra-state Completed)
            ("STU-IND-030", "INST-PUNE-COEP", "MAHARASHTRA", "INST-MUMBAI-VJTI", "MAHARASHTRA", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-PUNE-COEP-0111"),
            # Delhi -> Delhi (Intra-state Released)
            ("STU-IND-072", "INST-DELHI-IIITD", "DELHI", "INST-DELHI-NSUT", "DELHI", "BTECH-CSE", TransferStatus.RELEASED, "NOC-DELHI-IIITD-0112"),
            # Telangana -> Telangana (Intra-state Pending Release)
            ("STU-IND-060", "INST-HYD-JNTU", "TELANGANA", "INST-HYD-IITH", "TELANGANA", "BTECH-ECE", TransferStatus.PENDING_RELEASE, None),
            # Uttar Pradesh -> Uttar Pradesh (Intra-state Completed)
            ("STU-IND-065", "INST-VARANASI-BHU", "UTTAR_PRADESH", "INST-KANPUR-IITK", "UTTAR_PRADESH", "BTECH-ECE", TransferStatus.COMPLETED, "NOC-VARANASI-BHU-0114"),
            # Kerala -> Kerala (Intra-state Pending Admission)
            ("STU-IND-026", "INST-KOCHI-CUSAT", "KERALA", "INST-CALICUT-NITC", "KERALA", "BTECH-ECE", TransferStatus.PENDING_ADMISSION, "NOC-KOCHI-CUSAT-0115"),
            # Arunachal Pradesh -> Assam (Completed)
            ("STU-IND-003", "INST-NIRJULI-NERIST", "ARUNACHAL_PRADESH", "INST-GUWAHATI-IITG", "ASSAM", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-NERIST-0116"),
            # Jammu and Kashmir -> Chandigarh (Released)
            ("STU-IND-077", "INST-SRINAGAR-NITSRI", "JAMMU_AND_KASHMIR", "INST-CHANDIGARH-PEC", "CHANDIGARH", "BTECH-CSE", TransferStatus.RELEASED, "NOC-NITSRI-0117"),
            # Ladakh -> Himachal Pradesh (Pending Admission)
            ("STU-IND-080", "INST-LEH-UOL", "LADAKH", "INST-MANDI-IITMANDI", "HIMACHAL_PRADESH", "BTECH-CSE", TransferStatus.PENDING_ADMISSION, "NOC-LEH-0118"),
            # Jharkhand -> Bihar (Completed)
            ("STU-IND-019", "INST-DHANBAD-IITISM", "JHARKHAND", "INST-PATNA-IITP", "BIHAR", "BTECH-CSE", TransferStatus.COMPLETED, "NOC-ISM-0119"),
        ]

        for trf_idx, (s_ref, src_inst, src_state, dst_inst, dst_state, prog, trf_status, noc) in enumerate(transfer_specs):
            trf_id = f"TRF-IND-2026-{trf_idx+1:03d}"
            t_req = TransferRequest(
                id=trf_id,
                student_ref=s_ref,
                apaar_id=f"9876-2026-{int(s_ref[-3:]):04d}",
                source_institution_id=src_inst,
                source_institution_name=next(inst["name"] for inst in institutions_master if inst["id"] == src_inst),
                destination_institution_id=dst_inst,
                destination_institution_name=next(inst["name"] for inst in institutions_master if inst["id"] == dst_inst),
                source_state=src_state,
                destination_state=dst_state,
                programme_id=prog,
                programme_name=next(p[1] for p in programmes_master if p[0] == prog),
                academic_year="2025-2026",
                initiation_date=date(2026, 6, 1),
                requested_effective_date=date(2026, 7, 15),
                status=trf_status,
                noc_certificate_ref=noc,
                source_decision="APPROVED" if trf_status in {TransferStatus.RELEASED, TransferStatus.PENDING_ADMISSION, TransferStatus.COMPLETED} else None,
                destination_decision="CONFIRMED" if trf_status == TransferStatus.COMPLETED else "REJECTED" if trf_status == TransferStatus.REJECTED else None,
                created_by="system_seeder",
            )
            db.add(t_req)

        # ---------------------------------------------------------
        # 5. Temporal Integrity Alerts & Cases (12 Alerts)
        # ---------------------------------------------------------
        alert_specs = [
            ("ALT-IND-001", "STU-IND-001", "9876-2026-0001", "TEMPORAL_OVERLAP_CONFLICT", "HIGH", "Simultaneous active enrolment in two separate institutions", "OPEN"),
            ("ALT-IND-002", "STU-IND-008", "9876-2026-0008", "CONCURRENT_DUAL_DEGREE", "HIGH", "Concurrent degree without approved credit mobility NOC", "UNDER_REVIEW"),
            ("ALT-IND-003", "STU-IND-014", "9876-2026-0014", "EXCEPTION_REVIEW_REQUIRED", "MEDIUM", "Interrupted attendance during inter-state migration", "UNDER_REVIEW"),
            ("ALT-IND-004", "STU-IND-020", "9876-2026-0020", "INTAKE_ANOMALY", "MEDIUM", "Batch enrolment exceeded sanctioned quota threshold", "OPEN"),
            ("ALT-IND-005", "STU-IND-026", "9876-2026-0026", "TEMPORAL_OVERLAP_CONFLICT", "HIGH", "Date overlap without documented transfer NOC", "OPEN"),
            ("ALT-IND-006", "STU-IND-032", "9876-2026-0032", "DUPLICATE_SUBMISSION", "LOW", "Duplicate batch registration entry detected in CSV import", "RESOLVED"),
            ("ALT-IND-007", "STU-IND-040", "9876-2026-0040", "EXCEPTION_REVIEW_REQUIRED", "MEDIUM", "Special dispensation medical leave review", "RESOLVED"),
            ("ALT-IND-008", "STU-IND-053", "9876-2026-0053", "TEMPORAL_OVERLAP_CONFLICT", "HIGH", "Potential simultaneous enrolment detected prior to release clearance", "OPEN"),
            ("ALT-IND-009", "STU-IND-071", "9876-2026-0071", "INTAKE_ANOMALY", "LOW", "Supernumerary seat allocation threshold verification", "RESOLVED"),
            ("ALT-IND-010", "STU-IND-077", "9876-2026-0077", "EXCEPTION_REVIEW_REQUIRED", "MEDIUM", "Inter-state transfer migration grace period calculation", "UNDER_REVIEW"),
        ]

        for a_id, s_ref, apaar, a_type, sev, expl, a_stat in alert_specs:
            db.add(Alert(
                id=a_id,
                student_ref=s_ref,
                apaar_id=apaar,
                alert_type=a_type,
                severity=sev,
                status=a_stat,
                title=expl,
                explanation=expl,
                confidence_score=0.95 if sev == "HIGH" else 0.80,
                supporting_record_ids=[1, 2],
            ))
            # Review Event
            db.add(AlertReviewEvent(
                alert_id=a_id,
                action="INITIAL_ALERT_GENERATION" if a_stat == "OPEN" else "REVIEW_UNDERTAKEN",
                previous_status="OPEN",
                new_status=a_stat,
                actor="AICTE Regional Reviewer",
                decision="CASE_FLAGGED" if a_stat != "RESOLVED" else "RESOLVED_VALIDATED",
                note=f"Automated evaluation and case tracking for {a_id}",
            ))

        # ---------------------------------------------------------
        # 6. Cryptographically Signed Digital Credentials (Ed25519)
        # ---------------------------------------------------------
        cert_specs = [
            ("CERT-IND-2026-001", "STU-IND-075", "INST-DELHI-IITD", "BTECH-CSE"),
            ("CERT-IND-2026-002", "STU-IND-032", "INST-MUMBAI-IITB", "BTECH-CSE"),
            ("CERT-IND-2026-003", "STU-IND-054", "INST-CHENNAI-IITM", "BTECH-ECE"),
            ("CERT-IND-2026-004", "STU-IND-021", "INST-BLR-IISC", "MTECH-AI"),
            ("CERT-IND-2026-005", "STU-IND-059", "INST-HYD-IITH", "BTECH-CSE"),
            ("CERT-IND-2026-006", "STU-IND-064", "INST-KANPUR-IITK", "BTECH-CSE"),
            ("CERT-IND-2026-007", "STU-IND-005", "INST-GUWAHATI-IITG", "BTECH-CSE"),
            ("CERT-IND-2026-008", "STU-IND-078", "INST-SRINAGAR-NITSRI", "BTECH-ECE"),
        ]

        for c_id, s_ref, inst_id, prog in cert_specs:
            stu_idx = int(s_ref[-3:]) - 1
            s_name = student_blueprints[stu_idx][0] if 0 <= stu_idx < len(student_blueprints) else "Demo Student"
            inst_name = next(i["name"] for i in institutions_master if i["id"] == inst_id)
            prog_name = next(p[1] for p in programmes_master if p[0] == prog)
            s_apaar = f"9876-2026-{int(s_ref[-3:]):04d}"

            payload = {
                "certificate_id": c_id,
                "student_ref": s_ref,
                "student_name": s_name,
                "institution_id": inst_id,
                "institution_name": inst_name,
                "programme_id": prog,
                "programme_name": prog_name,
                "issue_date": "2026-05-30",
                "completion_date": "2026-05-15",
                "credential_type": "AICTE_VERIFIED_COMPLETION",
                "apaar_id": s_apaar,
            }
            sig_hex = CertificateService.compute_ed25519_signature(payload)

            db.add(Certificate(
                certificate_id=c_id,
                student_ref=s_ref,
                apaar_id=s_apaar,
                student_name=s_name,
                institution_id=inst_id,
                institution_name=inst_name,
                programme_id=prog,
                programme_name=prog_name,
                issue_date="2026-05-30",
                completion_date="2026-05-15",
                status="VALID",
                signature_algorithm="Ed25519",
                signature_hex=sig_hex,
                public_key_id=ACTIVE_KEY_ID,
                payload_json=payload,
            ))

        # ---------------------------------------------------------
        # 7. Verifier Organizations & Request Logs
        # ---------------------------------------------------------
        verifiers = [
            ("ORG-TCS-BGV", "Tata Consultancy Services Background Verification Cell", "EMPLOYER", "bgv@tcs.example.com"),
            ("ORG-INFY-BGV", "Infosys Talent Verification Directorate", "EMPLOYER", "bgv@infosys.example.com"),
            ("ORG-WIPRO-BGV", "Wipro Global Credentials Verification Hub", "EMPLOYER", "bgv@wipro.example.com"),
        ]
        for org_id, org_name, org_type, email in verifiers:
            db.add(VerifierOrganization(
                id=org_id,
                org_name=org_name,
                org_type=org_type,
                is_approved=True,
                contact_email=email,
            ))
            # Verification Log
            db.add(VerificationRequestLog(
                verifier_org_id=org_id,
                verifier_org_name=org_name,
                query_student_ref="STU-IND-075",
                query_apaar_id="9876-2026-0075",
                certificate_id="CERT-IND-2026-001",
                verification_outcome="MATCH_VERIFIED",
                limited_response_json={"status": "VALID", "issued_to": "Ishaan Malhotra", "institution": "Indian Institute of Technology Delhi"},
                ip_address="127.0.0.1",
            ))

        # ---------------------------------------------------------
        # 8. User Accounts across All Roles & States
        # ---------------------------------------------------------
        AuthService.seed_demo_users(db)

        # Seed additional state and institution registrar demo users
        extra_users = [
            ("coep_registrar", "registrar@coep.ac.in", "Registrar, COEP Pune", "institution_officer", "INSTITUTION_REGISTRAR", "INST-PUNE-COEP", "CoepRegistrar@2026!"),
            ("nitt_registrar", "registrar@nitt.edu", "Registrar, NIT Trichy", "institution_officer", "INSTITUTION_REGISTRAR", "INST-TRICHY-NITT", "NittRegistrar@2026!"),
            ("pes_registrar", "registrar@pes.edu", "Registrar, PES Bengaluru", "institution_officer", "INSTITUTION_REGISTRAR", "INST-BLR-PES", "PesRegistrar@2026!"),
            ("dtu_registrar", "registrar@dtu.ac.in", "Registrar, DTU Delhi", "institution_officer", "INSTITUTION_REGISTRAR", "INST-DELHI-DTU", "DtuRegistrar@2026!"),
            ("iitb_registrar", "registrar@iitb.ac.in", "Registrar, IIT Bombay", "institution_officer", "INSTITUTION_REGISTRAR", "INST-MUMBAI-IITB", "IitbRegistrar@2026!"),
            ("student_aarav", "aarav.student@pramaan.gov.in", "Aarav Sharma (Student Demo Delhi)", "student", "STUDENT", "INST-DELHI-DTU", "StudentAarav@2026!", "STU-IND-081"),
            ("student_karthik", "karthik.student@pramaan.gov.in", "Karthik Subramanian (Student Demo TN)", "student", "STUDENT", "INST-TRICHY-NITT", "StudentKarthik@2026!", "STU-IND-054"),
            ("student_aditya", "aditya.student@pramaan.gov.in", "Aditya Deshmukh (Student Demo MH)", "student", "STUDENT", "INST-PUNE-COEP", "StudentAditya@2026!", "STU-IND-032"),
        ]

        for u_data in extra_users:
            uname, uemail, ufname, urole, ucat, uinst, upwd = u_data[:7]
            ustu_ref = u_data[7] if len(u_data) > 7 else None

            existing = db.query(User).filter((User.username == uname) | (User.email == uemail)).first()
            if not existing:
                new_user = User(
                    username=uname,
                    email=uemail,
                    password_hash=PasswordHasher.hash_password(upwd),
                    full_name=ufname,
                    role=urole,
                    role_category=ucat,
                    institution_id=uinst,
                    is_active=True,
                )
                db.add(new_user)
                db.flush()

                if ustu_ref:
                    db.add(StudentUserLink(
                        user_id=new_user.id,
                        student_ref=ustu_ref,
                        is_primary=True,
                    ))

        # ---------------------------------------------------------
        # 9. Audit Events
        # ---------------------------------------------------------
        db.add(AuditLog(
            action="SYNTHETIC_DATASET_INITIALIZED",
            performed_by="system_seeder",
            entity_type="SYSTEM",
            entity_id="INDIA_WIDE_DEMO",
            details={
                "environment": "INDIA — SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL GOVERNMENT DATA",
                "states_covered": 36,
                "institutions_seeded": len(institutions_master),
                "students_seeded": len(student_blueprints),
            },
            timestamp=datetime.utcnow(),
        ))

        db.commit()

        counts = {
            "status": "SUCCESS",
            "database_path": str(db_file.resolve()),
            "institutions": len(institutions_master),
            "students": db.query(Student).count(),
            "enrolments": db.query(Enrolment).count(),
            "transfers": db.query(TransferRequest).count(),
            "alerts": db.query(Alert).count(),
            "certificates": db.query(Certificate).count(),
            "consents": db.query(StudentConsent).count(),
            "users": db.query(User).count(),
        }
        print("Synthetic India-Wide Dataset successfully generated!")
        print(f"Summary: {counts}")
        return counts


if __name__ == "__main__":
    reseed_flag = "--reseed" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--reseed"]
    target = args[0] if args else DEFAULT_TARGET_DB
    seed_synthetic_india_data(target, reseed=reseed_flag)
