from pathlib import Path
import sqlite3
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import sqlcipher3.dbapi2 as sqlcipher
import test_core
from test_core import field
from local_assistant.service import AssistantService, CoreError
from local_assistant.sources import SourceError
from local_assistant.protocol import decode_message_details


class IncrementalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "plain.db"
        test_core.CoreTest.make_plain_database(self.source)
        self.execute(self.source, 'UPDATE c2c_msg_table SET "40020"="peer","40090"=NULL,"40093"=NULL')
        self.profile = self.root / "profile_info.db"
        self.execute(self.profile, 'CREATE TABLE profile_info_v6("1000","1002","20002","20009","20004")')
        self.execute(self.profile, 'INSERT INTO profile_info_v6 VALUES("peer","123456","合成联系人","合成备注","")')
        self.group = self.root / "group_info.db"
        self.execute(self.group, 'CREATE TABLE group_detail_info_ver1("60001","60007","60026")')
        self.execute(self.group, 'INSERT INTO group_detail_info_ver1 VALUES("800001","合成群","合成群备注")')
        self.execute(self.source, 'INSERT INTO group_msg_table VALUES(2,2,0,0,"peer","group-uid","800001","123456",1700000000,?,NULL,"群名片")',
                     (field(40800, field(45101, "合成群正文".encode())),))
        self.companions = {"profile_info.db": self.profile, "group_info.db": self.group}
        self.service = AssistantService(self.root / "app")

    @staticmethod
    def execute(path, sql, params=()):
        conn = sqlite3.connect(path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def load(self, mode="incremental", account="synthetic"):
        return self.service.import_snapshot(str(self.source), account, companion_paths=self.companions, import_mode=mode)

    def add_message(self, number=3, timestamp=1600000000):
        self.execute(self.source, 'INSERT INTO c2c_msg_table VALUES(?,2,0,0,"peer","peer","123456",NULL,?,?,NULL,NULL)',
                     (number, timestamp, field(40800, field(45101, "晚同步的旧消息".encode()))))

    def test_late_same_time_and_revisions_only_decode_changed(self):
        initial = self.load()
        self.add_message(-5, 1500000000)
        self.add_message(3, 1700000000)
        self.execute(self.source, 'UPDATE c2c_msg_table SET "40800"=? WHERE "40001"=1',
                     (field(40800, field(45101, "修订后的正文".encode())),))
        with patch("local_assistant.service.decode_message_details", wraps=decode_message_details) as decoder:
            result = self.load()
        self.assertEqual(decoder.call_count, 3)
        self.assertEqual(result["changes"], {"scanned": 4, "added": 2, "updated": 1, "unchanged": 1})
        self.assertGreater(result["last_change_seq"], initial["last_change_seq"])
        self.assertEqual(len(self.service.search_messages("修订后的正文", account_id="synthetic")["items"]), 1)
        self.assertEqual(len(self.service.search_messages("晚同步的旧消息", account_id="synthetic")["items"]), 2)
        with self.service.storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM messages_fts WHERE text='请提交作业'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0], 4)

    def test_metadata_only_update_and_repeat(self):
        self.load()
        self.execute(self.profile, 'UPDATE profile_info_v6 SET "20009"="更新备注"')
        self.execute(self.group, 'UPDATE group_detail_info_ver1 SET "60026"="更新群备注"')
        with patch("local_assistant.service.decode_message_details", side_effect=AssertionError("unchanged messages decoded")):
            result = self.load()
        self.assertEqual(result["changes"]["scanned"], 0)
        self.assertEqual(result["metadata"]["profiles"], 1)
        self.assertEqual(result["metadata"]["groups"], 1)
        self.assertEqual(result["total"], 2)
        rows = self.service.list_conversations(account_id="synthetic")["items"]
        self.assertTrue(any("更新群备注" in row["title"] for row in rows))
        self.assertTrue(any("更新备注" in row["title"] for row in rows))
        self.assertEqual(self.service.search_messages("合成群正文")["items"][0]["sender_name"], "群名片")
        self.assertEqual(self.load()["status"], "already_imported")

    def test_new_messages_use_cached_profile_without_metadata_rewrite(self):
        self.load()
        self.add_message()
        result = self.load()
        self.assertEqual(result["metadata"], {"profiles": 0, "groups": 0, "local_avatars": 0})
        row = self.service.search_messages("晚同步的旧消息")["items"][0]
        self.assertEqual(row["sender_name"], "合成备注")
        self.assertEqual(row["sender_qq"], "123456")
        self.assertIn("合成备注", row["title"])

    def test_full_mode_repairs_projection_and_legacy_migration(self):
        self.load()
        with self.service.storage.connect() as conn:
            conn.execute("UPDATE messages SET text='damaged',sender_name='' WHERE conversation_id LIKE '%c2c%'")
        with patch("local_assistant.service.decode_message_details", wraps=decode_message_details) as decoder:
            result = self.load("full")
        self.assertEqual(result["status"], "reindexed")
        self.assertEqual(decoder.call_count, 2)
        self.assertEqual(self.service.search_messages("damaged")["items"], [])
        with self.service.storage.connect() as conn:
            conn.execute("UPDATE imports SET projection_version=3")
        self.assertEqual(self.load()["import_mode"], "full")

    def test_failure_rolls_back_messages_fts_sequence_and_checkpoint(self):
        initial = self.load()
        self.add_message()
        with patch.object(self.service, "_import_qq_metadata", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.load()
        self.assertEqual(self.service.overview("synthetic")["message_count"], 2)
        with self.service.storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT max(seq) FROM message_changes").fetchone()[0], initial["last_change_seq"])
            self.assertEqual(conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0], 2)
        self.assertEqual(self.load()["changes"]["added"], 1)

    def test_accounts_and_invalid_mode(self):
        self.load(account="synthetic-a")
        self.load(account="synthetic-b")
        self.assertEqual(self.load(account="synthetic-a")["status"], "already_imported")
        self.assertEqual(self.service.overview("synthetic-b")["message_count"], 2)
        with self.assertRaises(CoreError) as exc:
            self.load("invalid")
        self.assertEqual(exc.exception.code, "INVALID_PARAMS")

    def test_plaintext_wal_is_read_from_private_copy_without_source_writes(self):
        self.load()
        writer = sqlite3.connect(self.source)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute('INSERT INTO c2c_msg_table VALUES(4,2,0,0,"peer","peer","123456",NULL,1600000000,?,NULL,NULL)',
                       (field(40800, field(45101, "合成WAL增量".encode())),))
        writer.commit()
        paths = [self.source, Path(str(self.source) + "-wal"), Path(str(self.source) + "-shm")]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        result = self.load()
        self.assertEqual(result["changes"]["added"], 1)
        self.assertEqual(len(self.service.search_messages("合成WAL增量")["items"]), 1)
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])
        self.assertEqual(list((self.root / "app").glob("snapshot-*")), [])

    def encrypt(self, plain, output):
        cipher = self.root / (output.stem + "-encrypted-temp.db")
        # Test-owned file only; encrypt fresh rather than retaining synthetic WAL.
        if cipher.exists():
            cipher.unlink()
        incoming = sqlite3.connect(plain)
        encrypted = sqlcipher.connect(cipher)
        try:
            for statement in ("PRAGMA cipher_page_size=4096", "PRAGMA key='0123456789abcdef'", "PRAGMA kdf_iter=4000",
                              "PRAGMA cipher_hmac_algorithm=HMAC_SHA1", "PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512"):
                encrypted.execute(statement)
            for name, ddl in incoming.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
                encrypted.execute(ddl)
                data = incoming.execute(f'SELECT * FROM "{name}"').fetchall()
                if data:
                    encrypted.executemany(f'INSERT INTO "{name}" VALUES({",".join("?" for _ in data[0])})', data)
            encrypted.commit()
        finally:
            incoming.close()
            encrypted.close()
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b"NTQQ" + b"\x00" * 1020 + cipher.read_bytes())

    def encrypted_load(self, mode="incremental"):
        return self.service.prepare_source(str(self.root / "encrypted" / "nt_msg.db"), "synthetic", confirm_decryption=True,
                                           database_key="0123456789abcdef", import_mode=mode)

    def test_encrypted_metadata_only_skips_message_decryption(self):
        self.encrypt(self.source, self.root / "encrypted" / "nt_msg.db")
        self.encrypt(self.profile, self.root / "encrypted" / "profile_info.db")
        self.encrypted_load()
        self.execute(self.profile, 'UPDATE profile_info_v6 SET "20009"="新备注"')
        self.encrypt(self.profile, self.root / "encrypted" / "profile_info.db")
        with patch.object(self.service.qq_sources, "_decrypt_selected_tables", wraps=self.service.qq_sources._decrypt_selected_tables) as decrypt:
            result = self.encrypted_load()
        self.assertEqual([call.args[0].name for call in decrypt.call_args_list], ["profile_info.db"])
        self.assertEqual(result["metadata"]["profiles"], 1)
        self.assertEqual(result["changes"]["scanned"], 0)

    def test_failed_optional_database_retried_not_marked_complete(self):
        self.encrypt(self.source, self.root / "encrypted" / "nt_msg.db")
        self.encrypt(self.profile, self.root / "encrypted" / "profile_info.db")
        original = self.service.qq_sources._decrypt_selected_tables
        def fail_profile(source, *args, **kwargs):
            if source.name == "profile_info.db":
                raise SourceError("DECRYPTION_FAILED", "synthetic")
            return original(source, *args, **kwargs)
        with patch.object(self.service.qq_sources, "_decrypt_selected_tables", side_effect=fail_profile):
            first = self.encrypted_load()
        self.assertEqual(len(first["warnings"]), 1)
        with patch.object(self.service.qq_sources, "_decrypt_selected_tables", wraps=original) as decrypt:
            second = self.encrypted_load()
        self.assertEqual([call.args[0].name for call in decrypt.call_args_list], ["profile_info.db"])
        self.assertEqual(second["warnings"], [])
        self.assertEqual(second["metadata"]["profiles"], 1)
        self.assertEqual(self.service.overview("synthetic")["message_count"], 2)


if __name__ == "__main__":
    unittest.main()
