"""Exercise the built core over real stdio using temporary synthetic data only."""
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source = root / "synthetic.db"
    conn = sqlite3.connect(source)
    for table in ("c2c_msg_table", "group_msg_table"):
        conn.execute(f'CREATE TABLE {table}("40001", "40011", "40012", "40013", "40020", "40021", "40030", "40033", "40050", "40800")')
    conn.executemany('INSERT INTO c2c_msg_table VALUES(?,2,0,0,"sender","peer",0,0,1700000000,NULL)', [(i,) for i in range(205)])
    conn.commit()
    conn.close()
    requests = [
        ("system.health", {}),
        ("source.import", {"path": str(source), "account_id": "synthetic"}),
        ("message.list", {"conversation_id": "qq:synthetic:c2c:peer", "account_id": "synthetic"}),
        ("message.search", {"account_id": "different-synthetic"}),
        ("source.import", {"path": str(source), "account_id": "synthetic", "import_mode": "incremental"}),
        ("source.import", {"path": str(source), "account_id": "synthetic", "import_mode": "full"}),
        ("archive.export", {"path": str(root / "backup.db")}),
        ("source.manual_import", {"path": str(root / "backup.db"), "format": "app_db"}),
        ("source.manual_import", {"path": str(source), "format": "qq_plain", "account_id": "manual"}),
        ("favorite.set", {"message_id":"msg:qq:synthetic:c2c:peer:0","account_id":"synthetic","enabled":True}),
        ("favorite.list", {"account_id":"synthetic"}),
        ("message.context", {"message_id":"msg:qq:synthetic:c2c:peer:0","account_id":"synthetic"}),
        ("message.search", {"account_id":"synthetic","order":"asc","limit":40}),
        ("conversation.pin", {"conversation_id":"qq:synthetic:c2c:peer","account_id":"synthetic","pinned":True}),
        ("profile.save", {"conversation_id":"qq:synthetic:c2c:peer","account_id":"synthetic","role_text":"synthetic-role"}),
        ("ai.catalog", {}),
        ("ai.budget.get", {}),
    ]
    payload = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n" for i, (method, params) in enumerate(requests))
    run = subprocess.run(["build/core/qq-insight-core.exe", "--data-dir", str(root / "app")], input=payload, capture_output=True, encoding="utf-8", timeout=60, check=True)
    lines = [json.loads(line) for line in run.stdout.splitlines()]
    results = {line["id"]: line["result"] for line in lines if "id" in line}
    assert results[0]["version"] == json.loads(Path("package.json").read_text(encoding="utf-8"))["version"]
    assert results[0]["capabilities"]["sqlcipher"]
    assert results[1]["total"] == 205
    assert len(results[2]["items"]) == 100 and results[2]["has_more"]
    assert results[3]["items"] == []
    assert results[4]["status"] == "already_imported"
    assert results[5]["import_mode"] == "full" and results[5]["changes"]["scanned"] == 205
    assert results[6]["message_count"] == 205
    assert results[7]["added"] == 0 and results[7]["skipped"] == 205
    assert results[8]["changes"]["added"] == 205
    assert results[9]['favorite']
    assert len(results[10]['items']) == 1
    assert results[11]['target_id'] == 'msg:qq:synthetic:c2c:peer:0'
    assert len(results[12]['items']) == 40
    assert results[13]['pinned']
    assert results[14]['role_text'] == 'synthetic-role'
    assert len(results[15]['items']) == 8
    assert results[16]['daily_used'] == 0
    assert any(line.get("method") == "source.progress" for line in lines)
print("Packaged core stdio passed: SQLCipher available, incremental/full modes, progress, pagination, account isolation, manual import, archive roundtrip")
