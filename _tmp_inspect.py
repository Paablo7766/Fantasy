import sqlite3, json, collections, datetime

c = sqlite3.connect(".cache/responses.sqlite")
names = [r[0] for r in c.execute("select name from sqlite_master where type='table'").fetchall()]
print("tables:", names)
for t in names:
    try:
        n = c.execute(f"select count(*) from {t}").fetchone()[0]
    except Exception as exc:
        n = f"err {exc}"
    print(t, n)

# price snapshots in sqlite?
for t in names:
    cols = [r[1] for r in c.execute(f"pragma table_info({t})").fetchall()]
    if "day" in cols:
        print("\n==", t, cols)
        rows = c.execute(f"select day, count(*) from {t} group by day order by day").fetchall()
        for day, n in rows:
            print("  ", day, n)
