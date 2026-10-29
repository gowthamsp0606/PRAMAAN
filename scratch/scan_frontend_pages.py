import os
import re

pages_dir = "frontend/src/pages"
results = {}

for fname in os.listdir(pages_dir):
    if not fname.endswith(".tsx"):
        continue
    fpath = os.path.join(pages_dir, fname)
    with open(fpath, encoding="utf-8") as f:
        content = f.read()
    
    api_calls = re.findall(r"api\.([a-zA-Z0-9_]+)", content)
    has_fetch = "fetch(" in content
    # check mock data arrays
    const_arrays = re.findall(r"const\s+([A-Z0-9_]+)\s*=\s*\[", content)
    
    results[fname] = {
        "api_calls": sorted(list(set(api_calls))),
        "has_fetch": has_fetch,
        "mock_arrays": const_arrays,
        "lines": len(content.splitlines())
    }

for page, data in sorted(results.items()):
    print(f"=== {page} ({data['lines']} lines) ===")
    print(f"  API Calls: {', '.join(data['api_calls']) if data['api_calls'] else 'NONE'}")
    if data['mock_arrays']:
        print(f"  Constants: {', '.join(data['mock_arrays'])}")
    if data['has_fetch']:
        print(f"  Uses direct fetch(): YES")
