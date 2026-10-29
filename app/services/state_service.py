from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.transfer import TransferRequest, TransferStatus
from app.models.intake import ApprovedIntake, HistoricalIntake


KNOWN_INSTITUTION_STATES: Dict[str, str] = {
    # 28 Indian States
    # 1. Andhra Pradesh
    "INST-TIRUPATI-IITT": "ANDHRA_PRADESH",
    "INST-VIZAG-AU": "ANDHRA_PRADESH",
    # 2. Arunachal Pradesh
    "INST-NIRJULI-NERIST": "ARUNACHAL_PRADESH",
    "INST-YUPIA-NITAP": "ARUNACHAL_PRADESH",
    # 3. Assam
    "INST-GUWAHATI-IITG": "ASSAM",
    "INST-SILCHAR-NITS": "ASSAM",
    # 4. Bihar
    "INST-PATNA-IITP": "BIHAR",
    "INST-PATNA-NITP": "BIHAR",
    # 5. Chhattisgarh
    "INST-BHILAI-IITBHL": "CHHATTISGARH",
    "INST-RAIPUR-NITRR": "CHHATTISGARH",
    # 6. Goa
    "INST-GOA-IITGOA": "GOA",
    "INST-PONDA-NITGOA": "GOA",
    # 7. Gujarat
    "INST-GNAGAR-IITGN": "GUJARAT",
    "INST-SURAT-SVNIT": "GUJARAT",
    # 8. Haryana
    "INST-KURUKSHETRA-NITKKR": "HARYANA",
    "INST-SONIPAT-IIIT": "HARYANA",
    # 9. Himachal Pradesh
    "INST-MANDI-IITMANDI": "HIMACHAL_PRADESH",
    "INST-HAMIRPUR-NITH": "HIMACHAL_PRADESH",
    # 10. Jharkhand
    "INST-DHANBAD-IITISM": "JHARKHAND",
    "INST-JAMSHEDPUR-NITJSR": "JHARKHAND",
    # 11. Karnataka
    "INST-BLR-IISC": "KARNATAKA",
    "INST-BLR-PES": "KARNATAKA",
    "INST-DHARWAD-IIT": "KARNATAKA",
    # 12. Kerala
    "INST-CALICUT-NITC": "KERALA",
    "INST-KOCHI-CUSAT": "KERALA",
    # 13. Madhya Pradesh
    "INST-INDORE-IITI": "MADHYA_PRADESH",
    "INST-BHOPAL-MANIT": "MADHYA_PRADESH",
    # 14. Maharashtra
    "INST-PUNE-COEP": "MAHARASHTRA",
    "INST-MUMBAI-IITB": "MAHARASHTRA",
    "INST-MUMBAI-VJTI": "MAHARASHTRA",
    # 15. Manipur
    "INST-IMPHAL-NITMN": "MANIPUR",
    "INST-IMPHAL-IIITM": "MANIPUR",
    # 16. Meghalaya
    "INST-SHILLONG-NITMG": "MEGHALAYA",
    "INST-SHILLONG-NEHU": "MEGHALAYA",
    # 17. Mizoram
    "INST-AIZAWL-NITMZ": "MIZORAM",
    "INST-AIZAWL-MZU": "MIZORAM",
    # 18. Nagaland
    "INST-CHUMU-NITNL": "NAGALAND",
    "INST-KOHIMA-NU": "NAGALAND",
    # 19. Odisha
    "INST-BHUB-IITBBS": "ODISHA",
    "INST-ROURKELA-NITR": "ODISHA",
    # 20. Punjab
    "INST-ROPAR-IITRPR": "PUNJAB",
    "INST-JALANDHAR-NITJ": "PUNJAB",
    # 21. Rajasthan
    "INST-JAIPUR-MNIT": "RAJASTHAN",
    "INST-JODHPUR-IITJ": "RAJASTHAN",
    "INST-PILANI-BITS": "RAJASTHAN",
    # 22. Sikkim
    "INST-RAVANGLA-NITS": "SIKKIM",
    "INST-MAJITAR-SMIT": "SIKKIM",
    # 23. Tamil Nadu
    "INST-CHENNAI-SJCE": "TAMIL_NADU",
    "INST-DEMO-01": "TAMIL_NADU",
    "INST-TRICHY-NITT": "TAMIL_NADU",
    "INST-CHENNAI-IITM": "TAMIL_NADU",
    "INST-CHENNAI-ANNA": "TAMIL_NADU",
    # 24. Telangana
    "INST-HYD-IITH": "TELANGANA",
    "INST-HYD-JNTU": "TELANGANA",
    # 25. Tripura
    "INST-AGARTALA-NITA": "TRIPURA",
    "INST-AGARTALA-IIITT": "TRIPURA",
    # 26. Uttar Pradesh
    "INST-KANPUR-IITK": "UTTAR_PRADESH",
    "INST-VARANASI-BHU": "UTTAR_PRADESH",
    # 27. Uttarakhand
    "INST-ROORKEE-IITR": "UTTARAKHAND",
    "INST-SRINAGAR-NITUK": "UTTARAKHAND",
    # 28. West Bengal
    "INST-KGP-IITKGP": "WEST_BENGAL",
    "INST-KOLKATA-JU": "WEST_BENGAL",

    # 8 Union Territories
    # 1. Andaman and Nicobar Islands
    "INST-PORTBLAIR-DBRAIT": "ANDAMAN_AND_NICOBAR",
    # 2. Chandigarh
    "INST-CHANDIGARH-PEC": "CHANDIGARH",
    # 3. Dadra and Nagar Haveli and Daman and Diu
    "INST-SILVASSA-GEC": "DADRA_NAGAR_DAMAN_DIU",
    # 4. Delhi (NCT)
    "INST-DELHI-DTU": "DELHI",
    "INST-DELHI-IITD": "DELHI",
    "INST-DELHI-NSUT": "DELHI",
    "INST-DELHI-IIITD": "DELHI",
    # 5. Jammu and Kashmir
    "INST-SRINAGAR-NITSRI": "JAMMU_AND_KASHMIR",
    "INST-JAMMU-IITJMU": "JAMMU_AND_KASHMIR",
    # 6. Ladakh
    "INST-LEH-UOL": "LADAKH",
    # 7. Lakshadweep
    "INST-KAVARATTI-GPC": "LAKSHADWEEP",
    # 8. Puducherry
    "INST-KARAIDIKAL-NITPY": "PUDUCHERRY",
    "INST-PUDUCHERRY-PEC": "PUDUCHERRY",
}

STATE_NAMES: Dict[str, str] = {
    # 28 States
    "ANDHRA_PRADESH": "State of Andhra Pradesh",
    "ARUNACHAL_PRADESH": "State of Arunachal Pradesh",
    "ASSAM": "State of Assam",
    "BIHAR": "State of Bihar",
    "CHHATTISGARH": "State of Chhattisgarh",
    "GOA": "State of Goa",
    "GUJARAT": "State of Gujarat",
    "HARYANA": "State of Haryana",
    "HIMACHAL_PRADESH": "State of Himachal Pradesh",
    "JHARKHAND": "State of Jharkhand",
    "KARNATAKA": "State of Karnataka",
    "KERALA": "State of Kerala",
    "MADHYA_PRADESH": "State of Madhya Pradesh",
    "MAHARASHTRA": "State of Maharashtra",
    "MANIPUR": "State of Manipur",
    "MEGHALAYA": "State of Meghalaya",
    "MIZORAM": "State of Mizoram",
    "NAGALAND": "State of Nagaland",
    "ODISHA": "State of Odisha",
    "PUNJAB": "State of Punjab",
    "RAJASTHAN": "State of Rajasthan",
    "SIKKIM": "State of Sikkim",
    "TAMIL_NADU": "State of Tamil Nadu",
    "TELANGANA": "State of Telangana",
    "TRIPURA": "State of Tripura",
    "UTTAR_PRADESH": "State of Uttar Pradesh",
    "UTTARAKHAND": "State of Uttarakhand",
    "WEST_BENGAL": "State of West Bengal",
    # 8 Union Territories
    "ANDAMAN_AND_NICOBAR": "Union Territory of Andaman & Nicobar",
    "CHANDIGARH": "Union Territory of Chandigarh",
    "DADRA_NAGAR_DAMAN_DIU": "Union Territory of Dadra & Nagar Haveli and Daman & Diu",
    "DELHI": "National Capital Territory of Delhi",
    "JAMMU_AND_KASHMIR": "Union Territory of Jammu & Kashmir",
    "LADAKH": "Union Territory of Ladakh",
    "LAKSHADWEEP": "Union Territory of Lakshadweep",
    "PUDUCHERRY": "Union Territory of Puducherry",
}


class StateService:
    @staticmethod
    def resolve_state_from_institution(institution_id: Optional[str]) -> str:
        if not institution_id:
            return "UNKNOWN"
        inst_upper = institution_id.upper()
        if inst_upper in KNOWN_INSTITUTION_STATES:
            return KNOWN_INSTITUTION_STATES[inst_upper]
        if "DELHI" in inst_upper or "DTU" in inst_upper or "IIITD" in inst_upper or "NSUT" in inst_upper or "IITD" in inst_upper:
            return "DELHI"
        if "MAHARASHTRA" in inst_upper or "PUNE" in inst_upper or "MUMBAI" in inst_upper or "COEP" in inst_upper or "IITB" in inst_upper or "VJTI" in inst_upper:
            return "MAHARASHTRA"
        if "TAMIL" in inst_upper or "TN" in inst_upper or "TRICHY" in inst_upper or "CHENNAI" in inst_upper or "NITT" in inst_upper or "IITM" in inst_upper or "ANNA" in inst_upper:
            return "TAMIL_NADU"
        if "KARNATAKA" in inst_upper or "BLR" in inst_upper or "BANGALORE" in inst_upper or "IISC" in inst_upper or "PES" in inst_upper or "DHARWAD" in inst_upper:
            return "KARNATAKA"
        if "TELANGANA" in inst_upper or "HYD" in inst_upper or "HYDERABAD" in inst_upper or "IITH" in inst_upper or "JNTU" in inst_upper:
            return "TELANGANA"
        if "UTTAR" in inst_upper or "UP" in inst_upper or "KANPUR" in inst_upper or "VARANASI" in inst_upper or "IITK" in inst_upper or "BHU" in inst_upper:
            return "UTTAR_PRADESH"
        if "GUJARAT" in inst_upper or "GNAGAR" in inst_upper or "AHMEDABAD" in inst_upper or "SURAT" in inst_upper or "IITGN" in inst_upper or "SVNIT" in inst_upper:
            return "GUJARAT"
        if "BENGAL" in inst_upper or "WB" in inst_upper or "KGP" in inst_upper or "KOLKATA" in inst_upper or "IITKGP" in inst_upper:
            return "WEST_BENGAL"
        if "KERALA" in inst_upper or "CALICUT" in inst_upper or "KOCHI" in inst_upper or "NITC" in inst_upper or "CUSAT" in inst_upper:
            return "KERALA"
        if "RAJASTHAN" in inst_upper or "JAIPUR" in inst_upper or "PILANI" in inst_upper or "MNIT" in inst_upper or "BITS" in inst_upper:
            return "RAJASTHAN"
        if "ANDHRA" in inst_upper or "AP" in inst_upper or "TIRUPATI" in inst_upper:
            return "ANDHRA_PRADESH"
        if "PUNJAB" in inst_upper or "ROPAR" in inst_upper:
            return "PUNJAB"
        return "OTHER"

    @classmethod
    def get_institutions_for_state(cls, db: Session, state: str) -> List[str]:
        state_norm = state.strip().upper()
        # Query distinct institutions from students, enrolments, and intake records
        inst_ids = set()
        for r in db.query(Student.primary_institution_id).distinct().all():
            if r[0]:
                inst_ids.add(r[0])
        for r in db.query(Enrolment.institution_id).distinct().all():
            if r[0]:
                inst_ids.add(r[0])
        for r in db.query(ApprovedIntake.institution_id).distinct().all():
            if r[0]:
                inst_ids.add(r[0])

        matching = []
        for inst_id in sorted(inst_ids):
            if cls.resolve_state_from_institution(inst_id) == state_norm:
                matching.append(inst_id)
        return matching

    @classmethod
    def get_state_dashboard_summary(cls, db: Session, state: str) -> Dict[str, Any]:
        state_norm = state.strip().upper()
        state_institutions = cls.get_institutions_for_state(db, state_norm)

        # Total students registered with primary institution in this state
        total_students = db.query(Student).filter(
            Student.primary_institution_id.in_(state_institutions)
        ).count() if state_institutions else 0

        # Verified APAAR students
        verified_apaar_count = db.query(Student).filter(
            Student.primary_institution_id.in_(state_institutions),
            Student.apaar_id.isnot(None),
            Student.identity_status == "VERIFIED",
        ).count() if state_institutions else 0

        apaar_penetration = round((verified_apaar_count / total_students * 100), 2) if total_students > 0 else 0.0

        # Enrolments
        active_enrolments = db.query(Enrolment).filter(
            Enrolment.institution_id.in_(state_institutions),
            Enrolment.enrolment_status == "Active",
        ).count() if state_institutions else 0

        total_enrolments = db.query(Enrolment).filter(
            Enrolment.institution_id.in_(state_institutions)
        ).count() if state_institutions else 0

        # Alerts in state institutions
        state_students = db.query(Student.student_ref).filter(
            Student.primary_institution_id.in_(state_institutions)
        ).distinct().scalar_subquery() if state_institutions else None

        total_alerts = db.query(Alert).filter(
            Alert.student_ref.in_(state_students)
        ).count() if state_students is not None else 0

        unresolved_alerts = db.query(Alert).filter(
            Alert.student_ref.in_(state_students),
            Alert.status != "RESOLVED",
        ).count() if state_students is not None else 0

        # Cross-state transfers:
        # Inbound: destination in this state, source outside this state
        inbound_transfers = db.query(TransferRequest).filter(
            TransferRequest.destination_institution_id.in_(state_institutions),
            ~TransferRequest.source_institution_id.in_(state_institutions),
        ).count() if state_institutions else 0

        # Outbound: source in this state, destination outside this state
        outbound_transfers = db.query(TransferRequest).filter(
            TransferRequest.source_institution_id.in_(state_institutions),
            ~TransferRequest.destination_institution_id.in_(state_institutions),
        ).count() if state_institutions else 0

        # Intra-state: both source and destination in this state
        intra_state_transfers = db.query(TransferRequest).filter(
            TransferRequest.source_institution_id.in_(state_institutions),
            TransferRequest.destination_institution_id.in_(state_institutions),
        ).count() if state_institutions else 0

        pending_action_transfers = db.query(TransferRequest).filter(
            (
                (TransferRequest.source_institution_id.in_(state_institutions) & (TransferRequest.status == TransferStatus.PENDING_RELEASE))
                | (TransferRequest.destination_institution_id.in_(state_institutions) & (TransferRequest.status == TransferStatus.RELEASED))
            )
        ).count() if state_institutions else 0

        return {
            "state_code": state_norm,
            "state_name": STATE_NAMES.get(state_norm, f"{state_norm.title()} State"),
            "institutions_count": len(state_institutions),
            "institutions": state_institutions,
            "metrics": {
                "total_registered_students": total_students,
                "verified_apaar_students": verified_apaar_count,
                "apaar_penetration_percentage": apaar_penetration,
                "total_enrolments": total_enrolments,
                "active_enrolments": active_enrolments,
                "total_alerts": total_alerts,
                "unresolved_alerts": unresolved_alerts,
            },
            "transfer_metrics": {
                "inbound_cross_state": inbound_transfers,
                "outbound_cross_state": outbound_transfers,
                "intra_state": intra_state_transfers,
                "pending_state_action": pending_action_transfers,
            },
            "status": "OPERATIONAL",
        }

    @classmethod
    def get_state_institutions(cls, db: Session, state: str) -> List[Dict[str, Any]]:
        state_norm = state.strip().upper()
        state_institutions = cls.get_institutions_for_state(db, state_norm)
        result = []
        for inst_id in state_institutions:
            student_count = db.query(Student).filter(Student.primary_institution_id == inst_id).count()
            active_enrolments = db.query(Enrolment).filter(
                Enrolment.institution_id == inst_id,
                Enrolment.enrolment_status == "Active",
            ).count()
            inst_students = db.query(Student.student_ref).filter(Student.primary_institution_id == inst_id).scalar_subquery()
            open_alerts = db.query(Alert).filter(
                Alert.student_ref.in_(inst_students),
                Alert.status != "RESOLVED",
            ).count()
            intake_records = db.query(ApprovedIntake).filter(ApprovedIntake.institution_id == inst_id).all()
            approved_intake = sum(rec.approved_intake_seats for rec in intake_records)
            enrolled_count = active_enrolments

            inst_name = inst_id
            if intake_records and intake_records[0].institution_name:
                inst_name = intake_records[0].institution_name
            elif "SJCE" in inst_id:
                inst_name = "St. Joseph's College of Engineering, Chennai"
            elif "DTU" in inst_id:
                inst_name = "Delhi Technological University, Delhi"
            elif "IITM" in inst_id:
                inst_name = "Indian Institute of Technology Madras"
            elif "NITT" in inst_id:
                inst_name = "National Institute of Technology, Tiruchirappalli"
            elif "ANNA" in inst_id:
                inst_name = "Anna University, Chennai"

            result.append({
                "institution_id": inst_id,
                "institution_name": inst_name,
                "state": state_norm,
                "total_students": student_count,
                "active_enrolments": active_enrolments,
                "open_alerts": open_alerts,
                "approved_intake_total": approved_intake,
                "actual_intake_total": enrolled_count,
                "compliance_status": "COMPLIANT" if (approved_intake == 0 or enrolled_count <= approved_intake) and open_alerts == 0 else "FLAGGED" if (approved_intake > 0 and enrolled_count > approved_intake) else "UNDER_REVIEW",
            })
        return result

    @classmethod
    def get_state_transfers(cls, db: Session, state: str) -> List[Dict[str, Any]]:
        state_norm = state.strip().upper()
        state_institutions = cls.get_institutions_for_state(db, state_norm)
        if not state_institutions:
            return []

        transfers = db.query(TransferRequest).filter(
            (TransferRequest.source_institution_id.in_(state_institutions))
            | (TransferRequest.destination_institution_id.in_(state_institutions))
        ).order_by(TransferRequest.initiation_date.desc()).all()

        results = []
        for t in transfers:
            is_inbound = t.destination_institution_id in state_institutions and t.source_institution_id not in state_institutions
            is_outbound = t.source_institution_id in state_institutions and t.destination_institution_id not in state_institutions
            direction = "INBOUND" if is_inbound else "OUTBOUND" if is_outbound else "INTRA_STATE"

            results.append({
                "transfer_id": t.id,
                "student_ref": t.student_ref,
                "direction": direction,
                "source_institution_id": t.source_institution_id,
                "source_institution_name": t.source_institution_name,
                "source_state": t.source_state or cls.resolve_state_from_institution(t.source_institution_id),
                "destination_institution_id": t.destination_institution_id,
                "destination_institution_name": t.destination_institution_name,
                "destination_state": t.destination_state or cls.resolve_state_from_institution(t.destination_institution_id),
                "programme_id": t.programme_id,
                "status": t.status,
                "initiation_date": str(t.initiation_date) if t.initiation_date else None,
                "requested_effective_date": str(t.requested_effective_date) if t.requested_effective_date else None,
                "noc_certificate_ref": t.noc_certificate_ref,
                "source_decision": t.source_decision,
                "destination_decision": t.destination_decision,
            })
        return results

    @classmethod
    def get_state_compliance_overview(cls, db: Session, state: str) -> Dict[str, Any]:
        state_norm = state.strip().upper()
        state_institutions = cls.get_institutions_for_state(db, state_norm)

        intake_records = db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id.in_(state_institutions)
        ).all() if state_institutions else []

        historical_records = db.query(HistoricalIntake).filter(
            HistoricalIntake.institution_id.in_(state_institutions)
        ).all() if state_institutions else []

        over_admissions = []
        for r in historical_records:
            if r.admitted_count > r.approved_intake:
                over_admissions.append({
                    "institution_id": r.institution_id,
                    "programme_id": r.programme_id,
                    "academic_year": r.academic_year,
                    "approved_intake": r.approved_intake,
                    "actual_admissions": r.admitted_count,
                    "excess": r.admitted_count - r.approved_intake,
                })

        return {
            "state": state_norm,
            "monitored_institutions": len(state_institutions),
            "quota_compliance_rate": round(
                ((len(historical_records) - len(over_admissions)) / len(historical_records) * 100), 2
            ) if historical_records else 100.0,
            "over_admission_incidents_count": len(over_admissions),
            "over_admission_incidents": over_admissions,
            "audit_standard": "AICTE Approval Process Handbook (APH) & State Quota Norms",
        }
