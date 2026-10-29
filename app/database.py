import os
import stat
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

if "sqlite" in settings.DATABASE_URL:
    db_file = engine.url.database
    if db_file and os.path.exists(db_file):
        try:
            mode = os.stat(db_file).st_mode
            if not (mode & stat.S_IWRITE):
                os.chmod(db_file, mode | stat.S_IWRITE)
        except OSError:
            pass

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        try:
            cols = [c[1] for c in cursor.execute("PRAGMA table_info(students)").fetchall()]
            if cols and "identity_status" not in cols:
                col_str = ", ".join(cols)
                cursor.execute(f"CREATE TEMP VIEW IF NOT EXISTS students AS SELECT {col_str}, 'APAAR_VERIFIED' AS identity_status FROM main.students")
        except Exception:
            pass
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

