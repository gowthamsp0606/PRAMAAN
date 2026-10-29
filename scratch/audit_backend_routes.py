import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
health = client.get("/health")
print("GET /health status:", health.status_code)
print("GET /health json:", health.json())

openapi = app.openapi()
paths = openapi.get("paths", {})
print(f"Total OpenAPI path operations: {len(paths)}")
for p in sorted(paths.keys()):
    methods = list(paths[p].keys())
    print(f"  {methods} {p}")
