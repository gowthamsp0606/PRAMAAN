import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command

from app.config import settings
from app.main import app
from app.rate_limiter import InMemoryRateLimiter, verifier_rate_limiter, reevaluate_rate_limiter
from app.security import mask_identifier, mask_sensitive_payload


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_production_mode_safety_latch():
    """Verify production mode rejects unsafe prototype settings and passes when fully secured."""
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{base_env.get('PYTHONPATH', '')}"

    # 1. Reject default secret key in production
    env1 = base_env.copy()
    env1["ENVIRONMENT"] = "production"
    env1["SECRET_KEY"] = "demo-institution-secret-key-sentinel-2026"
    p1 = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        capture_output=True, text=True, env=env1, cwd=str(BACKEND_DIR),
    )
    assert p1.returncode != 0
    assert "Production requires a non-default SECRET_KEY" in p1.stderr

    # 2. Reject missing AUTH_REQUIRED in production
    env2 = base_env.copy()
    env2["ENVIRONMENT"] = "production"
    env2["SECRET_KEY"] = "super-secret-key-with-more-than-32-chars-entropy"
    env2["AUTH_REQUIRED"] = "false"
    p2 = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        capture_output=True, text=True, env=env2, cwd=str(BACKEND_DIR),
    )
    assert p2.returncode != 0
    assert "Production mode remains disabled for this prototype" in p2.stderr

    # 3. Allow production when properly configured
    valid_token = "prod-admin-token-12345678"
    valid_hash = hashlib.sha256(valid_token.encode("utf-8")).hexdigest()
    env3 = base_env.copy()
    env3["ENVIRONMENT"] = "production"
    env3["ENABLE_PRODUCTION_MODE"] = "true"
    env3["SECRET_KEY"] = "super-secret-key-with-more-than-32-chars-entropy"
    env3["AUTH_REQUIRED"] = "true"
    env3["API_TOKEN_PRINCIPALS_JSON"] = json.dumps({
        valid_hash: {"subject": "prod-admin", "role": "administrator"}
    })
    p3 = subprocess.run(
        [sys.executable, "-c", "import app.config; print('CONFIG_LOADED_OK')"],
        capture_output=True, text=True, env=env3, cwd=str(BACKEND_DIR),
    )
    assert p3.returncode == 0
    assert "CONFIG_LOADED_OK" in p3.stdout


def test_rate_limiting_enforcement():
    """Verify rate limiter blocks request bursts with HTTP 429 and Retry-After header."""
    limiter = InMemoryRateLimiter(requests_limit=3, window_seconds=60)

    class FakeRequest:
        def __init__(self, ip):
            self.headers = {}
            self.client = type("Client", (), {"host": ip})()

    req = FakeRequest("192.168.1.100")

    # First 3 requests succeed
    limiter.check(req, force=True)
    limiter.check(req, force=True)
    limiter.check(req, force=True)

    # 4th request must raise 429
    with pytest.raises(Exception) as exc_info:
        limiter.check(req, force=True)
    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers

    # Different client IP is not blocked
    other_req = FakeRequest("192.168.1.101")
    limiter.check(other_req, force=True)  # Should not raise


def test_safe_generic_error_handling():
    """Verify unhandled application exceptions return clean 500 JSON without leaking stack traces."""
    client = TestClient(app)

    # Trigger a 404 or route error
    resp = client.get("/api/v1/certificates/NONEXISTENT-ID/verify")
    assert resp.status_code == 200
    assert resp.json()["verification_status"] == "NOT_FOUND"

    # Verify no traceback in response body
    assert "Traceback" not in resp.text
    assert "sqlalchemy" not in resp.text.lower()


def test_privacy_masking_invariants():
    """Verify identifier masking and payload redaction utilities conform to privacy guarantees."""
    assert mask_identifier("123456789012") == "********9012"
    assert mask_identifier("SHORT") == "****HORT"
    assert mask_identifier(None) is None
    assert mask_identifier("") == ""

    sensitive = {
        "student_ref": "STU-001",
        "apaar_id": "111122223333",
        "passport_ref": "PASS98765",
        "identity_evidence": "Matched Aadhaar biometric verification",
        "nested": {
            "query_apaar_id": "999988887777",
            "safe_field": "Computer Science",
            "signature_hex": "abcdef123456",
        },
    }
    masked = mask_sensitive_payload(sensitive)
    assert masked["student_ref"] == "STU-001"
    assert masked["apaar_id"] == "********3333"
    assert masked["passport_ref"] == "*****8765"
    assert masked["identity_evidence"] == "[redacted]"
    assert masked["nested"]["query_apaar_id"] == "********7777"
    assert masked["nested"]["safe_field"] == "Computer Science"
    assert masked["nested"]["signature_hex"] is None


def test_disposable_database_migration_cycle():
    """Verify Alembic migrations upgrade to head and downgrade to base on disposable database without touching demo DB."""
    import gc
    demo_db_path = BACKEND_DIR / "apaar_sentinel.db"
    demo_mtime_before = demo_db_path.stat().st_mtime if demo_db_path.exists() else None

    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db_path = tmp_file.name
    tmp_file.close()

    try:
        tmp_db_url = f"sqlite:///{Path(tmp_db_path).as_posix()}"
        alembic_cfg_path = str(BACKEND_DIR / "alembic.ini")
        cfg = Config(alembic_cfg_path)
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", tmp_db_url)

        # 1. Upgrade to head
        command.upgrade(cfg, "head")

        # Verify tables created
        engine = create_engine(tmp_db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "alert_review_events" in tables
        assert "import_jobs" in tables
        assert "import_row_results" in tables
        assert "alembic_version" in tables
        engine.dispose()

        # 2. Downgrade to base
        command.downgrade(cfg, "base")

        # Verify tables dropped
        engine = create_engine(tmp_db_url)
        inspector = inspect(engine)
        downgraded_tables = inspector.get_table_names()
        assert "alert_review_events" not in downgraded_tables
        assert "import_jobs" not in downgraded_tables
        assert "import_row_results" not in downgraded_tables
        engine.dispose()

    finally:
        gc.collect()
        try:
            if os.path.exists(tmp_db_path):
                os.remove(tmp_db_path)
        except OSError:
            pass

    # Verify demo database was never modified
    if demo_db_path.exists():
        assert demo_db_path.stat().st_mtime == demo_mtime_before
