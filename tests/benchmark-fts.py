"""Synthetic microbenchmark of the old/new FTS insert, not end-to-end QQ timing."""
import json
import sqlite3
import time

results = {}
for mode in ("before", "after"):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE messages_fts USING fts5(message_id UNINDEXED,text)")
    started = time.perf_counter()
    for i in range(10000):
        key = f"synthetic-{i}"
        if mode == "before":
            conn.execute("INSERT INTO messages_fts(message_id,text) SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM messages_fts WHERE message_id=?)", (key, "synthetic text", key))
        else:
            conn.execute("INSERT INTO messages_fts(message_id,text) VALUES(?,?)", (key, "synthetic text"))
    conn.commit()
    results[mode] = round(time.perf_counter() - started, 3)
    conn.close()
print(json.dumps(results))
