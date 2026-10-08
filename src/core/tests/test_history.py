from pathlib import Path
import sqlite3
import tempfile
import unittest

from local_assistant.service import AssistantService, CoreError, _qq_bundle_sha256
import test_core
from test_core import field


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "plain.db"
        test_core.CoreTest.make_plain_database(self.source)
        with sqlite3.connect(self.source) as conn:
            conn.executemany('INSERT INTO c2c_msg_table VALUES(?,2,0,0,"u1","peer",123456,123456,?,?,NULL,"测试同学")',
                             [(i, 1700000000 + i // 7, field(40800, field(45101, f"合成记录 {i} 100%_".encode()))) for i in range(2, 206)])
        conn.close()
        self.service = AssistantService(self.root / "data")
        self.service.import_snapshot(str(self.source), "synthetic-a")
        self.conversation = self.service.list_conversations(account_id="synthetic-a")["items"][0]["id"]

    def test_all_pages_same_timestamp_no_duplicates(self):
        cursor, ids, sizes = None, [], []
        while True:
            page = self.service.list_messages(self.conversation, account_id="synthetic-a", cursor=cursor)
            sizes.append(len(page["items"]))
            ids.extend(item["id"] for item in page["items"])
            self.assertEqual(page["items"], sorted(page["items"], key=lambda item: (item["sent_at"], item["id"])))
            if not page["has_more"]:
                self.assertIsNone(page["next_cursor"])
                break
            cursor = page["next_cursor"]
        self.assertEqual(sizes, [100, 100, 5])
        self.assertEqual(len(set(ids)), 205)

    def test_filters_and_scope_applied_before_paging(self):
        for query in ("测试同学", "123456", "100%_", "合成记录"):
            page = self.service.search_messages(query, account_id="synthetic-a", limit=10)
            self.assertEqual(len(page["items"]), 10)
            self.assertTrue(page["has_more"])
        self.assertEqual(self.service.search_messages("不存在", account_id="synthetic-a")["items"], [])
        self.assertEqual(self.service.search_messages("", sender="u1", direction="outgoing")["items"], [])
        self.assertEqual(len(self.service.search_messages("", sender="u1", direction="incoming")["items"]), 80)
        self.assertEqual(self.service.list_messages(self.conversation, account_id="synthetic-b")["items"], [])
        self.assertEqual(self.service.search_messages("测试同学", account_id="synthetic-b")["items"], [])
        # Literal wildcard characters, not a SQL pattern.
        self.assertEqual(self.service.search_messages("%not-a-wildcard%")["items"], [])

    def test_invalid_query_and_cursor(self):
        for kwargs in ({"limit": 0}, {"limit": True}, {"cursor": {}}, {"cursor": {"sent_at": "1", "id": "x"}},
                       {"direction": "invalid"}, {"query": None}):
            with self.assertRaises(CoreError) as error:
                self.service.search_messages(**kwargs)
            self.assertEqual(error.exception.code, "INVALID_PARAMS")

    def test_conversations_beyond_first_page(self):
        with self.service.storage.connect() as conn:
            conn.executemany("INSERT INTO conversations(id,kind,title,updated_at,platform,account_id,peer_qq) VALUES(?,'group',?,100,'qq','synthetic-a',?)",
                             [(f"group-{i:03}", f"合成群{i}", str(900000 + i)) for i in range(205)])
        first = self.service.list_conversations(account_id="synthetic-a")
        second = self.service.list_conversations(account_id="synthetic-a", cursor=first["next_cursor"])
        self.assertEqual(len(first["items"]) + len(second["items"]), 206)
        self.assertFalse(second["has_more"])
        self.assertEqual(len(self.service.list_conversations(query="900204", account_id="synthetic-a")["items"]), 1)

    def test_reimport_does_not_duplicate_fts(self):
        with self.service.storage.connect() as conn:
            conn.execute("UPDATE imports SET projection_version=1")
        self.service.import_snapshot(str(self.source), "synthetic-a")
        with self.service.storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0], 205)

    def test_wal_changes_update_fingerprint(self):
        source = self.root / "nt_msg.db"
        source.write_bytes(b"synthetic" * 300)
        wal = self.root / "nt_msg.db-wal"
        before = _qq_bundle_sha256(source)
        wal.write_bytes(b"synthetic-wal" * 300)
        self.assertNotEqual(before, _qq_bundle_sha256(source))


if __name__ == "__main__":
    unittest.main()
