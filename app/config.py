import os
import json
from pathlib import Path
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    _backend_dir = Path(__file__).resolve().parent.parent
    _env_path = _backend_dir / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
    else:
        load_dotenv(override=False)
except ImportError:
    pass

_DEMO_SECRET_KEY = "demo-institution-secret-key-sentinel-2026"
_environment_value = os.getenv("ENVIRONMENT", "development").lower()
_environment = "production" if _environment_value in {"prod", "production"} else _environment_value
_secret_key = os.getenv("SECRET_KEY", _DEMO_SECRET_KEY)
_api_token_principals = json.loads(os.getenv("API_TOKEN_PRINCIPALS_JSON", "{}"))

# Safe canonical DB resolution: resolve to absolute file path in backend directory
_backend_demo_db = (_backend_dir / "pramaan_india_demo.db").resolve()
_backend_protected_db = (_backend_dir / "apaar_sentinel.db").resolve()

_raw_db = os.getenv("DATABASE_URL", "").strip()
if not _raw_db or "pramaan_india_demo.db" in _raw_db:
    _resolved_db = f"sqlite:///{_backend_demo_db.as_posix()}"
elif "apaar_sentinel.db" in _raw_db:
    _resolved_db = f"sqlite:///{_backend_protected_db.as_posix()}"
elif _raw_db.startswith("sqlite:///./"):
    _relative_name = _raw_db.removeprefix("sqlite:///./")
    _resolved_db = f"sqlite:///{(_backend_dir / _relative_name).resolve().as_posix()}"
else:
    _resolved_db = _raw_db

if _environment == "production":
    if _secret_key == _DEMO_SECRET_KEY or len(_secret_key) < 32:
        raise RuntimeError("Production requires a non-default SECRET_KEY of at least 32 characters.")
    _auth_required_env = os.getenv("AUTH_REQUIRED", "false").lower() in {"1", "true", "yes"}
    _enable_prod_preview = os.getenv("ENABLE_PRODUCTION_MODE", "false").lower() in {"1", "true", "yes"}
    if not _auth_required_env or not _api_token_principals or not _enable_prod_preview:
        raise RuntimeError(
            "Production mode remains disabled for this prototype pending complete security and deployment review: non-default SECRET_KEY, AUTH_REQUIRED=true, configured API_TOKEN_PRINCIPALS_JSON, and explicit ENABLE_PRODUCTION_MODE=true are mandatory."
        )

class Settings(BaseModel):
    APP_NAME: str = "APAAR Sentinel"
    APP_VERSION: str = "1.0.0-hackathon-preview"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = _resolved_db
    SECRET_KEY: str = _secret_key
    ENVIRONMENT: str = _environment
    AUTH_REQUIRED: bool = os.getenv("AUTH_REQUIRED", "false").lower() in {"1", "true", "yes"}
    API_TOKEN_PRINCIPALS: dict[str, dict[str, str]] = _api_token_principals
    DEMO_REVIEWER: str = os.getenv("DEMO_REVIEWER", "Demo Officer (AICTE-RO-102)")
    TRANSFER_GRACE_PERIOD_DAYS: int = int(os.getenv("TRANSFER_GRACE_PERIOD_DAYS", "30"))
    ALLOW_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "ALLOW_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://10.31.9.99:5173,http://10.31.9.62:5173",
        ).split(",")
        if origin.strip()
    ]

settings = Settings()
