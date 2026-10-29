from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.intake import HistoricalIntake
from app.services.anomaly_service import HistoricalAnomalyService


def test_latest_anomaly_is_compared_against_prior_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    years = ["2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"]
    counts = [420, 430, 410, 440, 540]

    with sessions() as db:
        db.add_all([
            HistoricalIntake(
                institution_id="INST-SYNTHETIC",
                institution_name="Synthetic Institution",
                programme_id="PROG-SYNTHETIC",
                programme_name="Synthetic Programme",
                academic_year=year,
                admitted_count=count,
                approved_intake=600,
                is_anomaly=index == len(years) - 1,
                ground_truth="ANOMALY" if index == len(years) - 1 else "NORMAL",
            )
            for index, (year, count) in enumerate(zip(years, counts))
        ])
        db.commit()

        result = HistoricalAnomalyService(db).get_historical_trends(
            "INST-SYNTHETIC", "PROG-SYNTHETIC"
        )

    assert result["baseline_values"] == [420, 430, 410, 440]
    assert result["baseline_mean"] == 425.0
    assert result["baseline_sample_size"] == 4
    assert result["historical_range"] == {"minimum": 410, "maximum": 440}
    assert result["current_reported_enrolment"] == 540
    assert result["deviation_from_baseline_mean"] == 115.0
    assert result["comparison_explanation"] == (
        "Current reported enrolment is 540 students, compared with a historical "
        "range of 410–440 students. This deviation may warrant review."
    )
    engine.dispose()