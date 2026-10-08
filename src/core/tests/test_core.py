from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import sqlcipher3.dbapi2 as sqlcipher

from local_assistant.protocol import decode_message_body, decode_message_details
from local_assistant.service import AssistantService, CoreError


def varint(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number: int, payload: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def int_field(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


class CoreTest(unittest.TestCase):
    @staticmethod
    def make_plain_database(path: Path, timestamp: int = 1700000000) -> None:
        conn = sqlite3.connect(path)
        for table in ("c2c_msg_table", "group_msg_table"):
            conn.execute(f'CREATE TABLE {table}("40001", "40011", "40012", "40013", "40020", "40021", "40030", "40033", "40050", "40800", "40090", "40093")')
        conn.execute('INSERT INTO c2c_msg_table VALUES(1,2,0,0,"u1","peer",123456,123456,?,?,NULL,"同学甲")', (timestamp, field(40800, field(45101, "请提交作业".encode()))))
        conn.commit()
        conn.close()

    def test_protocol_extracts_text(self) -> None:
        segment = field(45101, "请明天提交作业".encode()) + varint((45002 << 3) | 0) + varint(1)
        body = field(40800, segment)
        text, kind, count, status = decode_message_body(body, 2)
        self.assertEqual(text, "请明天提交作业")
        self.assertEqual(kind, "文本")
        self.assertEqual(count, 1)
        self.assertEqual(status, 1)

    def test_protocol_extracts_image_metadata(self) -> None:
        segment = b"".join((
            int_field(45002, 2), int_field(45003, 1),
            field(45402, b"photo.jpg"), int_field(45411, 640), int_field(45412, 480),
            field(45406, bytes.fromhex("00112233445566778899aabbccddeeff")),
            field(45812, b"C:\\QQData\\photo.jpg"),
        ))
        details = decode_message_details(field(40800, segment), 2)
        self.assertEqual(details["text"], "[图片: photo.jpg]")
        self.assertEqual(details["media"][0]["width"], 640)
        self.assertEqual(details["media"][0]["md5"], "00112233445566778899aabbccddeeff")

    def test_import_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "plain.db"
            self.make_plain_database(source)
            service = AssistantService(root / "data")
            first = service.import_snapshot(str(source))
            second = service.import_snapshot(str(source))
            self.assertEqual(first["c2c_count"], 1)
            self.assertEqual(second["status"], "already_imported")
            self.assertEqual(service.overview()["message_count"], 1)
            conversation = service.list_conversations()["items"][0]
            self.assertEqual(conversation["peer_qq"], "123456")
            self.assertIn("同学甲", conversation["title"])
            message = service.list_messages(conversation["id"])["items"][0]
            self.assertEqual(message["sender_name"], "同学甲")
            self.assertEqual(message["sender_qq"], "123456")
            with service.storage.connect() as conn:
                conn.execute("UPDATE imports SET projection_version=1")
                conn.execute("UPDATE messages SET sender_name='',sender_qq=''")
            rebuilt = service.import_snapshot(str(source))
            self.assertEqual(rebuilt["status"], "reindexed")
            refreshed = service.list_messages(conversation["id"])["items"][0]
            self.assertEqual(refreshed["sender_name"], "同学甲")

    def test_imports_profile_group_names_and_avatars(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "plain.db"
            self.make_plain_database(source)
            conn = sqlite3.connect(source)
            conn.execute(
                'INSERT INTO group_msg_table VALUES(2,2,0,0,"member-uid","group-uid",778899,445566,1700000010,?,?,?)',
                (field(40800, field(45101, "群消息".encode())), "群名片", "成员昵称"),
            )
            conn.commit()
            conn.close()

            profile = root / "profile.db"
            conn = sqlite3.connect(profile)
            conn.execute('CREATE TABLE profile_info_v6("1000","1002","20002","20009","20004")')
            conn.execute('INSERT INTO profile_info_v6 VALUES("peer",123456,"原昵称","好友备注","https://q1.qlogo.cn/g?b=qq&nk=123456&s=100")')
            conn.commit()
            conn.close()

            group = root / "group.db"
            conn = sqlite3.connect(group)
            conn.execute('CREATE TABLE group_detail_info_ver1("60001","60007","60026")')
            conn.execute('INSERT INTO group_detail_info_ver1 VALUES(778899,"测试群","课程群")')
            conn.commit()
            conn.close()

            service = AssistantService(root / "data")
            result = service.import_snapshot(
                str(source), "qq-820288706", companion_paths={
                    "profile_info.db": profile,
                    "group_info.db": group,
                },
            )
            self.assertEqual(result["metadata"]["profiles"], 1)
            self.assertEqual(result["metadata"]["groups"], 1)
            conversations = service.list_conversations(account_id="qq-820288706")["items"]
            private = next(item for item in conversations if item["kind"] == "c2c")
            group_chat = next(item for item in conversations if item["kind"] == "group")
            self.assertIn("好友备注", private["title"])
            self.assertIn("课程群", group_chat["title"])
            self.assertIn("qlogo.cn", private["avatar_ref"])
            self.assertIn("qlogo.cn", group_chat["avatar_ref"])

    def test_discovery_and_account_scoping(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "Tencent Files" / "123456" / "nt_qq" / "nt_db"
            second = root / "Tencent Files" / "654321" / "nt_qq" / "nt_db"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.make_plain_database(first / "nt_msg_plain.db", 1700000000)
            self.make_plain_database(second / "nt_msg_plain.db", 1700000001)
            service = AssistantService(root / "data")
            discovered = service.discover_sources(extra_roots=[str(root)])
            discovered_ids = {item["account_id"] for item in discovered["items"]}
            self.assertTrue({"qq-123456", "qq-654321"}.issubset(discovered_ids))
            service.import_snapshot(str(first / "nt_msg_plain.db"), "qq-123456", "QQ 123456")
            service.import_snapshot(str(second / "nt_msg_plain.db"), "qq-654321", "QQ 654321")
            self.assertEqual(service.overview("qq-123456")["message_count"], 1)
            self.assertEqual(service.overview("qq-654321")["message_count"], 1)

    def test_encrypted_source_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "nt_msg.db"
            source.write_bytes(b"x" * 2048)
            service = AssistantService(root / "data")
            with self.assertRaises(CoreError) as raised:
                service.prepare_source(str(source), "qq-test")
            self.assertEqual(raised.exception.code, "DECRYPTION_CONFIRM_REQUIRED")

    def test_decrypts_and_imports_sqlcipher_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cipher = root / "cipher.db"
            key = "0123456789abcdef"
            conn = sqlcipher.connect(cipher)
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute(f"PRAGMA key = '{key}'")
            conn.execute("PRAGMA kdf_iter = 4000")
            conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
            conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
            for table in ("c2c_msg_table", "group_msg_table"):
                conn.execute(f'CREATE TABLE {table}("40001", "40011", "40012", "40013", "40020", "40021", "40030", "40033", "40050", "40800")')
            conn.execute('INSERT INTO c2c_msg_table VALUES(1,2,0,0,"u1","peer",0,0,1700000000,?)', (field(40800, field(45101, "自动解密测试".encode())),))
            conn.commit()
            conn.close()
            source = root / "nt_msg.db"
            source.write_bytes((b"NTQQ" + b"\x00" * 1020) + cipher.read_bytes())
            profile_cipher = root / "profile_cipher.db"
            conn = sqlcipher.connect(profile_cipher)
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute(f"PRAGMA key = '{key}'")
            conn.execute("PRAGMA kdf_iter = 4000")
            conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
            conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
            conn.execute('CREATE TABLE profile_info_v6("1000","1002","20002","20009","20004")')
            conn.execute('INSERT INTO profile_info_v6 VALUES("peer",123456,"联系人","备注名","")')
            conn.commit()
            conn.close()
            (root / "profile_info.db").write_bytes((b"NTQQ" + b"\x00" * 1020) + profile_cipher.read_bytes())
            service = AssistantService(root / "data")
            result = service.prepare_source(
                str(source), "qq-test", "测试账号", confirm_decryption=True, database_key=key,
            )
            self.assertTrue(result["decrypted"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["metadata"]["profiles"], 1)
            self.assertEqual(service.overview("qq-test")["message_count"], 1)

    def test_decrypts_committed_rows_from_stable_wal_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cipher = root / "cipher.db"
            key = "0123456789abcdef"
            conn = sqlcipher.connect(cipher)
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute(f"PRAGMA key = '{key}'")
            conn.execute("PRAGMA kdf_iter = 4000")
            conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
            conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
            conn.execute("PRAGMA journal_mode = WAL")
            for table in ("c2c_msg_table", "group_msg_table"):
                conn.execute(f'CREATE TABLE {table}("40001", "40011", "40012", "40013", "40020", "40021", "40030", "40033", "40050", "40800")')
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute('INSERT INTO c2c_msg_table VALUES(1,2,0,0,"u1","peer",0,0,1700000000,?)', (field(40800, field(45101, "WAL 最新消息".encode())),))
            conn.commit()

            source = root / "nt_msg.db"
            source.write_bytes((b"NTQQ" + b"\x00" * 1020) + cipher.read_bytes())
            shutil.copyfile(Path(str(cipher) + "-wal"), Path(str(source) + "-wal"))
            conn.close()

            service = AssistantService(root / "data")
            result = service.prepare_source(
                str(source), "qq-wal", "WAL 测试账号", confirm_decryption=True, database_key=key,
            )
            self.assertEqual(result["total"], 1)
            messages = service.list_messages(service.list_conversations(account_id="qq-wal")["items"][0]["id"])["items"]
            self.assertEqual(messages[0]["text"], "WAL 最新消息")


if __name__ == "__main__":
    unittest.main()
