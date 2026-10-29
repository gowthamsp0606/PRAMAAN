import json

with open("backend/openapi_dump.json", encoding="utf-8") as f:
    spec = json.load(f)

print(f"Total paths: {len(spec['paths'])}")
for path, methods in sorted(spec['paths'].items()):
    for method, details in methods.items():
        summary = details.get("summary", "")
        tags = details.get("tags", [])
        operation_id = details.get("operationId", "")
        print(f"{method.upper():6} {path:50} | {','.join(tags):30} | {summary[:35]}")
