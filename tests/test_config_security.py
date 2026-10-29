import os
from pathlib import Path
import subprocess
import sys


def run_config_import(secret: str):
    environment = os.environ.copy()
    environment["ENVIRONMENT"] = "production"
    environment["SECRET_KEY"] = secret
    backend_dir = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = (
        f"{backend_dir}{os.pathsep}{environment.get('PYTHONPATH', '')}"
        if "PYTHONPATH" in environment
        else backend_dir
    )
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        capture_output=True,
        text=True,
        env=environment,
        cwd=backend_dir,
        check=False,
    )


def test_production_rejects_builtin_demo_secret():
    result = run_config_import("demo-institution-secret-key-sentinel-2026")

    assert result.returncode != 0
    assert "Production requires a non-default SECRET_KEY" in result.stderr


def test_production_remains_disabled_without_api_authentication():
    result = run_config_import("a-test-secret-with-more-than-thirty-two-characters")

    assert result.returncode != 0
    assert "Production mode remains disabled for this prototype" in result.stderr
