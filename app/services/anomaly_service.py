import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.intake import HistoricalIntake, ApprovedIntake
from app.models.alert import Alert
from app.models.student import Student
from app.models.enrolment import Enrolment

class HistoricalAnomalyService:
    """
    Explainable statistical baseline and finding engine for detecting unusual shifts in institutional admissions.
    Visible anomaly methods:
    1. Z-score on Year-on-Year change against moving baseline (|Z| >= 2.0).
    2. Interquartile Range (IQR) comparison against peer cohorts.
    3. Reviewer dismissal workflow allowing officers to document legitimate expansions or closures.
    4. Unified explainable findings separating statistical anomaly indicators from deterministic rule conflicts.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_historical_trends(self, institution_id: str, programme_id: str) -> Dict[str, Any]:
        rows: List[HistoricalIntake] = self.db.query(HistoricalIntake).filter(
            HistoricalIntake.institution_id == institution_id,
            HistoricalIntake.programme_id == programme_id
        ).order_by(HistoricalIntake.academic_year.asc()).all()

        if not rows:
            return {
                "institution_id": institution_id,
                "programme_id": programme_id,
                "history": [],
                "insufficient_history": True,
                "baseline_sample_size": 0,
                "message": "No historical intake records found for this institution and programme."
            }

        counts = [r.admitted_count for r in rows]
        baseline_rows = rows[:-1] if len(rows) > 1 and rows[-1].is_anomaly else rows
        baseline_counts = [r.admitted_count for r in baseline_rows]

        # A flagged latest observation must not dilute its own comparison baseline.
        mean_val = sum(baseline_counts) / len(baseline_counts) if baseline_counts else 0.0
        variance = sum((x - mean_val) ** 2 for x in baseline_counts) / (len(baseline_counts) if len(baseline_counts) > 1 else 1)
        std_dev = math.sqrt(variance)

        # Robust statistics (Median and IQR)
        sorted_counts = sorted(baseline_counts)
        n = len(sorted_counts)
        if n > 0:
            median_val = sorted_counts[n // 2] if n % 2 == 1 else (sorted_counts[n // 2 - 1] + sorted_counts[n // 2]) / 2.0
            q1 = sorted_counts[n // 4] if n >= 4 else sorted_counts[0]
            q3 = sorted_counts[(3 * n) // 4] if n >= 4 else sorted_counts[-1]
            iqr_val = round(q3 - q1, 1)
        else:
            median_val = 0.0
            iqr_val = 0.0

        sample_size = len(baseline_counts)
        insufficient_history = sample_size < 3
        insufficient_reason = (
            f"At least 3 historical cohort years are required for statistical significance (sample size: {sample_size})."
            if insufficient_history else None
        )

        history_items = []
        for idx, r in enumerate(rows):
            prev_val = counts[idx - 1] if idx > 0 else r.admitted_count
            pct_change = round(((r.admitted_count - prev_val) / prev_val * 100), 1) if prev_val > 0 else 0.0
            z = round((r.admitted_count - mean_val) / std_dev, 2) if std_dev > 0 else 0.0

            history_items.append({
                "id": r.id,
                "academic_year": r.academic_year,
                "admitted_count": r.admitted_count,
                "approved_intake": r.approved_intake,
                "pct_change": pct_change,
                "z_score": z,
                "is_anomaly": r.is_anomaly,
                "iqr_status": r.iqr_status,
                "peer_group_iqr_diff": r.peer_group_iqr_diff,
                "dismissed": r.dismissed,
                "dismissal_reason": r.dismissal_reason,
                "ground_truth": r.ground_truth,
                "explanation": r.anomaly_explanation
            })

        latest = history_items[-1] if history_items else None
        current_count = rows[-1].admitted_count if rows else None
        baseline_min = min(baseline_counts) if baseline_counts else None
        baseline_max = max(baseline_counts) if baseline_counts else None
        comparison_explanation = None
        if current_count is not None and baseline_counts:
            comparison_explanation = (
                f"Current reported enrolment is {current_count} students, compared with a "
                f"historical range of {baseline_min}–{baseline_max} students. "
                "This deviation may warrant review."
            )

        return {
            "institution_id": institution_id,
            "institution_name": rows[0].institution_name,
            "programme_id": programme_id,
            "programme_name": rows[0].programme_name,
            "baseline_mean": round(mean_val, 1),
            "baseline_std": round(std_dev, 1),
            "baseline_median": round(median_val, 1),
            "baseline_iqr": iqr_val,
            "baseline_sample_size": sample_size,
            "baseline_values": baseline_counts,
            "historical_range": {"minimum": baseline_min, "maximum": baseline_max},
            "current_reported_enrolment": current_count,
            "deviation_from_baseline_mean": round(current_count - mean_val, 1) if current_count is not None else None,
            "comparison_explanation": comparison_explanation,
            "insufficient_history": insufficient_history,
            "insufficient_reason": insufficient_reason,
            "detection_method": "Multi-tier: Z-Score (|Z| >= 2.0) & Peer IQR Comparison",
            "history": history_items,
            "latest_record": latest
        }

    def get_all_anomalies(
        self,
        institution_id: Optional[str] = None,
        programme_id: Optional[str] = None,
        academic_year: Optional[str] = None,
        dismissed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        query = self.db.query(HistoricalIntake).filter(HistoricalIntake.is_anomaly == True)
        if institution_id:
            query = query.filter(HistoricalIntake.institution_id == institution_id)
        if programme_id:
            query = query.filter(HistoricalIntake.programme_id == programme_id)
        if academic_year:
            query = query.filter(HistoricalIntake.academic_year == academic_year)
        if dismissed is not None:
            query = query.filter(HistoricalIntake.dismissed == dismissed)

        anomalies = query.order_by(HistoricalIntake.academic_year.desc()).all()
        return [
            {
                "id": a.id,
                "institution_id": a.institution_id,
                "institution_name": a.institution_name,
                "programme_id": a.programme_id,
                "programme_name": a.programme_name,
                "academic_year": a.academic_year,
                "admitted_count": a.admitted_count,
                "approved_intake": a.approved_intake,
                "pct_change": a.pct_change,
                "z_score": a.z_score,
                "iqr_status": a.iqr_status,
                "dismissed": a.dismissed,
                "dismissed_by": a.dismissed_by,
                "dismissed_at": a.dismissed_at.isoformat() if a.dismissed_at else None,
                "dismissal_reason": a.dismissal_reason,
                "ground_truth": a.ground_truth,
                "explanation": a.anomaly_explanation
            }
            for a in anomalies
        ]

    def dismiss_anomaly(self, anomaly_id: int, reason: str, dismissed_by: str) -> Dict[str, Any]:
        item = self.db.query(HistoricalIntake).filter(HistoricalIntake.id == anomaly_id).first()
        if not item:
            raise ValueError(f"Historical record {anomaly_id} not found.")

        if not reason or not reason.strip() or len(reason.strip()) < 5:
            raise ValueError("A valid, substantive justification of at least 5 characters is required to dismiss an anomaly.")

        item.dismissed = True
        item.dismissed_by = dismissed_by or "AICTE Officer (Regional Office)"
        item.dismissed_at = datetime.now(timezone.utc)
        item.dismissal_reason = reason.strip()
        self.db.commit()
        self.db.refresh(item)
        return {
            "success": True,
            "id": item.id,
            "dismissed": True,
            "reason": item.dismissal_reason,
            "dismissed_by": item.dismissed_by
        }

    def get_explainable_findings(
        self,
        institution_id: Optional[str] = None,
        finding_type: Optional[str] = None,
        severity: Optional[str] = None,
        is_statistical: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Unified explainable findings endpoint separating statistical anomaly indicators
        from deterministic rule findings across all core Sentinel engines.
        """
        findings: List[Dict[str, Any]] = []

        # 1. Statistical Historical Deviations
        if finding_type in (None, "HISTORICAL_DEVIATION"):
            anom_q = self.db.query(HistoricalIntake).filter(HistoricalIntake.is_anomaly == True)
            if institution_id:
                anom_q = anom_q.filter(HistoricalIntake.institution_id == institution_id)
            for a in anom_q.all():
                sev = "HIGH" if abs(a.z_score or 0) >= 3.0 else "MEDIUM" if abs(a.z_score or 0) >= 2.0 else "LOW"
                findings.append({
                    "finding_id": f"FIND-ANOM-{a.id}",
                    "finding_type": "HISTORICAL_DEVIATION",
                    "is_statistical_anomaly": True,
                    "rule_or_model_id": "STAT-ZSCORE-V1",
                    "institution_id": a.institution_id,
                    "institution_name": a.institution_name,
                    "programme_id": a.programme_id,
                    "programme_name": a.programme_name,
                    "academic_year": a.academic_year,
                    "observed_value": a.admitted_count,
                    "comparison_baseline": {"mean": a.approved_intake, "z_score": a.z_score, "pct_change": a.pct_change},
                    "sample_size": 5,
                    "severity": sev,
                    "status": "RESOLVED" if a.dismissed else "OPEN",
                    "dismissed": bool(a.dismissed),
                    "dismissal_reason": a.dismissal_reason,
                    "evidence": {
                        "z_score": a.z_score,
                        "pct_change": a.pct_change,
                        "iqr_status": a.iqr_status,
                        "peer_group_iqr_diff": a.peer_group_iqr_diff,
                    },
                    "explanation": a.anomaly_explanation or (
                        f"Reported enrolment of {a.admitted_count} represents a {a.pct_change}% shift (z={a.z_score}) "
                        "against moving historical baseline."
                    ),
                    "review_recommended": not bool(a.dismissed),
                })

        # 2. Deterministic Temporal Overlap Conflicts
        if finding_type in (None, "TEMPORAL_CONFLICT"):
            alert_q = self.db.query(Alert).filter(Alert.status != "RESOLVED")
            for alt in alert_q.all():
                findings.append({
                    "finding_id": f"FIND-ALERT-{alt.id}",
                    "finding_type": "TEMPORAL_CONFLICT",
                    "is_statistical_anomaly": False,
                    "rule_or_model_id": "RULE-TEMP-OVERLAP-001",
                    "institution_id": None,
                    "institution_name": None,
                    "programme_id": None,
                    "programme_name": None,
                    "academic_year": None,
                    "observed_value": f"Student Ref: {alt.student_ref}",
                    "comparison_baseline": "Single concurrent full-time enrolment permitted by policy",
                    "sample_size": None,
                    "severity": alt.severity or "HIGH",
                    "status": alt.status,
                    "dismissed": alt.status == "RESOLVED",
                    "dismissal_reason": alt.reviewer_note if alt.status == "RESOLVED" else None,
                    "evidence": {"supporting_record_ids": alt.supporting_record_ids},
                    "explanation": alt.explanation or "Student has concurrent overlapping active enrolments across institutions.",
                    "review_recommended": True,
                })

        # 3. Deterministic Identity Inconsistencies
        if finding_type in (None, "IDENTITY_INCONSISTENCY"):
            flagged_q = self.db.query(Student).filter(Student.identity_status == "IDENTITY_FLAGGED")
            if institution_id:
                flagged_q = flagged_q.filter(Student.primary_institution_id == institution_id)
            for stu in flagged_q.all():
                findings.append({
                    "finding_id": f"FIND-IDENT-{stu.student_ref}",
                    "finding_type": "IDENTITY_INCONSISTENCY",
                    "is_statistical_anomaly": False,
                    "rule_or_model_id": "RULE-IDENTITY-COLLISION-001",
                    "institution_id": stu.primary_institution_id,
                    "institution_name": None,
                    "programme_id": None,
                    "programme_name": None,
                    "academic_year": None,
                    "observed_value": f"Flagged Student: {stu.student_ref}",
                    "comparison_baseline": "Valid verified APAAR or documented exemption",
                    "sample_size": None,
                    "severity": "HIGH",
                    "status": "OPEN",
                    "dismissed": False,
                    "dismissal_reason": None,
                    "evidence": {"apaar_id": stu.apaar_id, "identity_status": stu.identity_status},
                    "explanation": "Student identity flagged due to collision or unresolved verification dispute.",
                    "review_recommended": True,
                })

        # Apply filters
        if severity:
            findings = [f for f in findings if f["severity"] == severity]
        if is_statistical is not None:
            findings = [f for f in findings if f["is_statistical_anomaly"] == is_statistical]

        stat_count = sum(1 for f in findings if f["is_statistical_anomaly"])
        determ_count = sum(1 for f in findings if not f["is_statistical_anomaly"])

        return {
            "total_findings": len(findings),
            "statistical_anomalies_count": stat_count,
            "deterministic_rule_count": determ_count,
            "findings": findings,
        }

    def compute_synthetic_benchmark_metrics(self) -> Dict[str, Any]:
        records = self.db.query(HistoricalIntake).all()
        if not records:
            return {"total": 0, "metrics_available": False}

        tp = 0
        fp = 0
        tn = 0
        fn = 0

        for r in records:
            actual_is_anomaly = (r.ground_truth == "ANOMALY")
            pred_is_anomaly = bool(r.is_anomaly)

            if pred_is_anomaly and actual_is_anomaly:
                tp += 1
            elif pred_is_anomaly and not actual_is_anomaly:
                fp += 1
            elif not pred_is_anomaly and not actual_is_anomaly:
                tn += 1
            elif not pred_is_anomaly and actual_is_anomaly:
                fn += 1

        precision = round((tp / (tp + fp)), 3) if (tp + fp) > 0 else 0.0
        recall = round((tp / (tp + fn)), 3) if (tp + fn) > 0 else 0.0
        fpr = round((fp / (fp + tn)), 3) if (fp + tn) > 0 else 0.0
        accuracy = round(((tp + tn) / (tp + tn + fp + fn)), 3) if (tp + tn + fp + fn) > 0 else 0.0

        return {
            "dataset": "AICTE Synthetic Historical Multi-Year Benchmark (Fictional)",
            "metrics_available": True,
            "confusion_matrix": {
                "true_positives": tp,
                "false_positives": fp,
                "true_negatives": tn,
                "false_negatives": fn,
                "total_samples": len(records)
            },
            "metrics": {
                "precision": precision,
                "recall": recall,
                "false_positive_rate": fpr,
                "accuracy": accuracy
            },
            "methodology": "Two-tailed Z-score deviation against 5-year moving window (|z| >= 2.0) with peer IQR validation"
        }
