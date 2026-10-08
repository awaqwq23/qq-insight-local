from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_core
import test_incremental
from local_assistant.service import AssistantService, CoreError


@contextmanager
def database(path):
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "plain.db"
        test_core.CoreTest.make_plain_database(self.source)
        self.app = AssistantService(self.root / "app")
        self.other = AssistantService(self.root / "other")

    def load(self, account="synthetic"):
        return self.app.manual_import(str(self.source), "qq_plain", account)

    def archive(self):
        path = self.root / "backup.db"
        self.app.export_archive(str(path))
        return path

    def test_roundtrip_accounts_profiles_and_repeated_merge(self):
        self.load()
        self.load("second")
        self.app.save_profile("合成角色")
        with self.app.storage.connect() as conn:
            conn.execute("INSERT INTO qq_profiles VALUES('synthetic','peer','peer','123456','合成名字','','')")
        archive = self.archive()
        with database(archive) as conn:
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT format_version FROM archive_manifest").fetchone()[0], 1)
            self.assertFalse(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%key%' AND name<>'message_fts_keys'").fetchall())
        result = self.other.manual_import(str(archive), "app_db")
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(self.other.get_profile()["role_text"], "合成角色")
        self.assertEqual(self.other.overview(account_id="second")["message_count"], 1)
        result = self.other.manual_import(str(archive), "app_db")
        self.assertEqual((result["added"], result["skipped"]), (0, 2))
        with self.other.storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM message_changes").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM import_parts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM qq_profiles").fetchone()[0], 1)
        with patch.object(self.other.qq_sources, "discover", return_value={"items": []}):
            accounts = self.other.discover_sources()["accounts"]
        self.assertEqual({a["account_id"] for a in accounts}, {"synthetic", "second"})

    def test_existing_message_and_role_preserved(self):
        self.load()
        archive = self.archive()
        self.other.manual_import(str(self.source), "qq_plain", "synthetic")
        self.other.save_profile("当前角色")
        with self.other.storage.connect() as conn:
            conn.execute("UPDATE messages SET text='保留当前正文'")
        result = self.other.manual_import(str(archive), "app_db")
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.other.search_messages()["items"][0]["text"], "保留当前正文")
        self.assertEqual(self.other.get_profile()["role_text"], "当前角色")

    def test_legacy_db_with_wal_is_read_without_modification(self):
        self.load()
        writer = sqlite3.connect(self.app.storage.path)
        try:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("INSERT INTO profile VALUES(1,'WAL角色','now')")
            writer.commit()
            paths = [self.app.storage.path, Path(str(self.app.storage.path) + "-wal"), Path(str(self.app.storage.path) + "-shm")]
            before = [hashlib.sha256(p.read_bytes()).digest() for p in paths]
            result = self.other.manual_import(str(self.app.storage.path), "app_db")
            self.assertEqual(result["added"], 1)
            self.assertEqual(self.other.get_profile()["role_text"], "WAL角色")
            self.assertEqual(before, [hashlib.sha256(p.read_bytes()).digest() for p in paths])
            # Backup API also includes committed WAL changes.
            archive = self.archive()
            with database(archive) as conn:
                self.assertEqual(conn.execute("SELECT role_text FROM profile").fetchone()[0], "WAL角色")
        finally:
            writer.close()

    def test_reject_wrong_format_version_and_account_mismatch(self):
        self.load()
        archive = self.archive()
        with self.assertRaises(CoreError):
            self.other.manual_import(str(self.source), "app_db")
        with database(archive) as conn:
            conn.execute("UPDATE archive_manifest SET format_version=100")
        with self.assertRaises(CoreError) as raised:
            self.other.manual_import(str(archive), "app_db")
        self.assertEqual(raised.exception.code, "ARCHIVE_VERSION_UNSUPPORTED")
        with database(archive) as conn:
            conn.execute("UPDATE archive_manifest SET format_version=1")
            conn.execute("UPDATE messages SET account_id='different'")
        with self.assertRaises(CoreError):
            self.other.manual_import(str(archive), "app_db")
        self.assertEqual(self.other.health()["message_count"], 0)

    def test_failure_rolls_back_all_tables_and_cleans_temporary_files(self):
        self.load()
        archive = self.archive()
        with patch.object(self.other.storage, "index_messages", side_effect=sqlite3.OperationalError("synthetic failure")):
            with self.assertRaises(CoreError):
                self.other.manual_import(str(archive), "app_db")
        with self.other.storage.connect() as conn:
            for table in ("messages", "conversations", "message_changes", "messages_fts", "message_fts_keys"):
                self.assertEqual(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
        self.assertFalse(list((self.root / "other").glob("archive-*")))

    def test_no_overwrite_or_self_import(self):
        self.load()
        before = self.source.read_bytes()
        with self.assertRaises(CoreError):
            self.app.export_archive(str(self.source))
        self.assertEqual(before, self.source.read_bytes())
        with self.assertRaises(CoreError):
            self.app.export_archive(str(self.app.storage.path))
        with self.assertRaises(CoreError):
            self.app.manual_import(str(self.app.storage.path), "app_db")

    def test_manual_plain_includes_companions_and_validates_scope(self):
        profile = self.root / "profile_info.db"
        with database(profile) as conn:
            conn.execute('CREATE TABLE profile_info_v6("1000","1002","20002","20009","20004")')
            conn.execute('INSERT INTO profile_info_v6 VALUES("peer","123456","合成联系人","合成备注","")')
        result = self.load()
        self.assertEqual(result["metadata"]["profiles"], 1)
        self.assertIn("合成备注", self.app.list_conversations()["items"][0]["title"])
        with self.assertRaises(CoreError):
            self.app.manual_import(str(self.source), "qq_plain", "")
        with self.assertRaises(CoreError):
            self.app.manual_import(str(self.source), "other", "synthetic")

    def test_manual_encrypted_renamed_and_wrong_key(self):
        encrypted = self.root / "renamed-backup.qqdb"
        test_incremental.IncrementalTest.encrypt(self, self.source, encrypted)
        before = encrypted.read_bytes()
        with self.assertRaises(CoreError):
            self.app.manual_import(str(encrypted), "qq_encrypted", "synthetic", "bad-key")
        with self.assertRaises(CoreError):
            self.app.manual_import(str(encrypted), "qq_encrypted", "synthetic", "wrongkey12345678")
        result = self.app.manual_import(str(encrypted), "qq_encrypted", "synthetic", "0123456789abcdef")
        self.assertEqual(result["changes"]["added"], 1)
        self.assertEqual(encrypted.read_bytes(), before)
        self.assertFalse(list((self.root / "app").glob("decrypt-*")))

    def test_old_backup_without_digest_is_supported(self):
        self.load()
        archive = self.archive()
        with database(archive) as conn:
            conn.execute("ALTER TABLE messages DROP COLUMN source_digest")
            conn.execute("DROP TABLE archive_manifest")
        self.assertEqual(self.other.manual_import(str(archive), "app_db")["added"], 1)

