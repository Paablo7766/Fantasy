import sqlite3, time, datetime, json

con = sqlite3.connect(".cache/responses.sqlite")
cur = con.cursor()
tables = cur.execute("select name from sqlite_master where type='table'").fetchall()
print("tables", tables)
for (name,) in tables:
    cols = [row[1] for row in cur.execute(f"pragma table_info({name})").fetchall()]
    print("-", name, cols)
    if "stored_at" in cols:
        rows = cur.execute(
            f"select cache_key, kind, stored_at, expires_at from {name} order by stored_at desc limit 8"
        ).fetchall()
        now = time.time()
        for key, kind, stored, expires in rows:
            age = (now - stored) / 60 if isinstance(stored, (int, float)) else None
            print(
                "   ",
                kind,
                f"age={age:.1f}min" if age is not None else "age=?",
                f"expired={expires < now}" if isinstance(expires, (int, float)) else "",
                key[:110],
            )
