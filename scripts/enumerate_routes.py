import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

openapi = app.openapi()
paths = openapi.get("paths", {})
print(f"TOTAL OPENAPI PATHS: {len(paths)}\n")

all_endpoints = []
for path, methods in paths.items():
    for method, details in methods.items():
        summary = details.get("summary", "")
        tags = ",".join(details.get("tags", []))
        operation_id = details.get("operationId", "")
        all_endpoints.append((path, method.upper(), summary, tags, operation_id))

all_endpoints.sort(key=lambda x: (x[0], x[1]))
print(f"TOTAL ENDPOINTS: {len(all_endpoints)}\n")
for path, method, summary, tags, op_id in all_endpoints:
    print(f"{method:6} {path:55} [{tags:20}] {summary}")
