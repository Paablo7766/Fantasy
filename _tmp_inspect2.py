import sqlite3, json, datetime

c = sqlite3.connect(".cache/responses.sqlite")
print("sqlite 2026-10-25 rows sample:")
for row in c.execute(
    "select player_id, day, market_value, market_value_change, stored_at from price_snapshots where day='2026-10-25' limit 8"
):
    print("  ", row, datetime.datetime.fromtimestamp(row[4], datetime.timezone.utc))

print("\nsqlite max stored_at overall:", c.execute("select max(stored_at) from price_snapshots").fetchone())

rows = json.load(open(".cache/supabase-local/price_snapshots.json", encoding="utf-8"))
last = sorted(rows, key=lambda r: r["stored_at"])[-5:]
print("\njson latest by stored_at:")
for r in last:
    print("  ", r, datetime.datetime.fromtimestamp(r["stored_at"], datetime.timezone.utc))

same = {r["player_id"]: r for r in rows if r["day"] == "2026-10-24"}
print("\njson 10-24 count", len(same))
for pid in list(same)[:5]:
    print("  ", same[pid])
