import sqlite3, datetime, json

c = sqlite3.connect(".cache/responses.sqlite")
cols = [r[1] for r in c.execute("pragma table_info(responses)").fetchall()]
print("responses cols:", cols)
for row in c.execute("select * from responses"):
    d = dict(zip(cols, row))
    url = str(d.get("url") or d.get("key") or "")
    stamp = d.get("stored_at") or d.get("fetched_at") or d.get("saved_at")
    try:
        human = datetime.datetime.fromtimestamp(float(stamp), datetime.timezone.utc)
    except Exception:
        human = stamp
    size = len(str(d.get("body") or d.get("content") or ""))
    print(url[:110], "|", human, "|", size)
