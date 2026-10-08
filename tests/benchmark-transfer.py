"""Synthetic DB backup/merge/query benchmark; no QQ source or real chats."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time

spec = importlib.util.spec_from_file_location("benchmark", Path(__file__).with_name("benchmark-incremental.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source, companions, _ = benchmark.fixtures(root)
    app = benchmark.AssistantService(root / "app")
    app.import_snapshot(str(source), "synthetic", companion_paths=companions)
    measurements = {}
    def measure(name, call):
        start = time.perf_counter()
        value = call()
        measurements[name] = {"seconds": round(time.perf_counter() - start, 3)}
        return value
    archive = root / "backup.db"
    measure("export_50000", lambda: app.export_archive(str(archive)))
    other = benchmark.AssistantService(root / "other")
    result = measure("merge_50000", lambda: other.manual_import(str(archive), "app_db"))
    assert result["added"] == 50000
    result = measure("merge_50000_repeat", lambda: other.manual_import(str(archive), "app_db"))
    assert result["added"] == 0 and result["skipped"] == 50000
    measure("overview_50000", lambda: other.overview(account_id="synthetic"))
    measure("list_200_conversations", lambda: other.list_conversations(account_id="synthetic"))
    page = measure("latest_100_messages", lambda: other.search_messages(account_id="synthetic", limit=100))
    measure("second_100_messages", lambda: other.search_messages(account_id="synthetic", limit=100, cursor=page["next_cursor"]))
    measure("search_missing_text", lambda: other.search_messages("不存在的测试关键字", account_id="synthetic"))
    with other.storage.connect() as conn:
        assert conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0] == 50000
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print(json.dumps(measurements, indent=2))
    Path("build/qa/transfer-benchmark.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
