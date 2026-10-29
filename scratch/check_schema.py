import sqlite3

for path in ["apaar_sentinel.db", "backend/apaar_sentinel.db"]:
    try:
        con = sqlite3.connect(path)
        cols = [c[1] for c in con.execute("PRAGMA table_info(students)").fetchall()]
        print(f"Path: {path}")
        print(f"  Columns: {cols}")
        print(f"  identity_status in cols? {'identity_status' in cols}")
    except Exception as e:
        print(f"Path: {path} -> {e}")
