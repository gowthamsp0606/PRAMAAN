import sqlite3
import os
from pathlib import Path

db_path = Path("backend/apaar_sentinel.db")
print("Exists:", db_path.exists())
print("Size bytes:", db_path.stat().st_size)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()
tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
print("Tables count:", len(tables))
for t in sorted(tables):
    try:
        cnt = cursor.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {cnt}")
    except Exception as e:
        print(f"  {t}: ERROR {e}")
conn.close()
