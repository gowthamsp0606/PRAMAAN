import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 1. Enforce a non-demo DATABASE_URL BEFORE any application modules are imported.
os.environ["ENVIRONMENT"] = "development"
_DEFAULT_DEMO_DB = "apaar_sentinel.db"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEMO_DB_PATH = _BACKEND_ROOT / _DEFAULT_DEMO_DB
if "DATABASE_URL" not in os.environ or _DEFAULT_DEMO_DB in os.environ.get("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Ensure asyncio Proactor loop self-pipe can connect on Windows environments where IPv4 loopback is restricted
import socket
_orig_socketpair = socket.socketpair
def _safe_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
    try:
        return _orig_socketpair(family, type, proto)
    except Exception:
        return _orig_socketpair(socket.AF_INET6, type, proto)
socket.socketpair = _safe_socketpair

from app.database import Base, get_db
import app.database as app_db
import app.seed_data as seed_data
from app.main import app


class _TestDatabase:
    """Process-wide holder so every TestClient(app) uses the current isolated session factory."""

    session_factory = None
    engine = None


def _isolated_get_db():
    if _TestDatabase.session_factory is None:
        raise RuntimeError(
            "Test database is not configured. API tests must run under the isolate_database_for_tests fixture."
        )
    db = _TestDatabase.session_factory()
    try:
        yield db
    finally:
        db.close()


# Bind the override on the live FastAPI app at import time so module-level
# TestClient(app) construction cannot fall back to the application engine.
app.dependency_overrides[get_db] = _isolated_get_db


@event.listens_for(Engine, "before_cursor_execute")
def safety_check_reject_real_db(conn, cursor, statement, parameters, context, executemany):
    raw_url = str(conn.engine.url)
    if _DEFAULT_DEMO_DB in raw_url:
        raise RuntimeError(
            f"SAFETY VIOLATION: Automated test attempted to execute database operations on the demo database: {raw_url}. "
            "Tests must run strictly against isolated temporary databases."
        )


def _snapshot_demo_db():
    if not _DEMO_DB_PATH.exists():
        return None
    digest = hashlib.sha256()
    with open(_DEMO_DB_PATH, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return (_DEMO_DB_PATH.stat().st_size, digest.hexdigest())


@pytest.fixture(scope="session", autouse=True)
def protect_demo_database():
    before = _snapshot_demo_db()
    yield
    after = _snapshot_demo_db()
    assert after == before, (
        f"SAFETY VIOLATION: tests modified {_DEMO_DB_PATH}. "
        f"before={before!r} after={after!r}"
    )


@pytest.fixture(autouse=True)
def isolate_database_for_tests(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def _set_fk_pragma(dbapi_conn, record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr(seed_data, "engine", test_engine)
    monkeypatch.setattr(seed_data, "SessionLocal", TestSessionLocal)

    monkeypatch.setattr(app_db, "engine", test_engine)
    monkeypatch.setattr(app_db, "SessionLocal", TestSessionLocal)

    previous_factory = _TestDatabase.session_factory
    previous_engine = _TestDatabase.engine
    previous_overrides = app.dependency_overrides.copy()
    _TestDatabase.engine = test_engine
    _TestDatabase.session_factory = TestSessionLocal
    app.dependency_overrides[get_db] = _isolated_get_db

    yield test_engine, TestSessionLocal

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)
    app.dependency_overrides[get_db] = _isolated_get_db
    _TestDatabase.session_factory = previous_factory
    _TestDatabase.engine = previous_engine
    test_engine.dispose()


@pytest.fixture
def client(isolate_database_for_tests):
    """Shared TestClient that always uses the autouse isolated database, seeded with demo data."""
    seed_data.init_db_and_seed()
    return TestClient(app)


@pytest.fixture
def db_sessions(isolate_database_for_tests):
    _engine, session_factory = isolate_database_for_tests
    return session_factory
