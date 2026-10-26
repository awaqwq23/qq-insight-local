"""Application services for the offline test build."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from typing import Any

from .protocol import decode_message_details, decode_cached_replies
from .sources import QQSourceAdapter, SourceError
from .storage import Storage
from .archive import TransferError, export_database, import_database


PROJECTION_VERSION = 7


from .errors import CoreError
from .workspace import WorkspaceFeatures
from .roster import export_roster, roster_scope
from .member_cache import import_cache, cache_info
from .ai import GroupAI
from .workspace_agent import WorkspaceAgent
from .chat_memory import ChatMemory
from .media import MediaStore, merge_media


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _part_sha256(source: Path) -> str:
    digest = hashlib.sha256()
    for path in (source, Path(str(source) + "-wal")):
        if not path.is_file():
            digest.update(b"missing;")
            continue
        digest.update(str(path.stat().st_size).encode("ascii") + b":")
        with path.open("rb") as stream:
            while chunk := stream.read(8 << 20):
                digest.update(chunk)
    return digest.hexdigest()


def _bundle_parts(source: Path, companions: dict[str, Path]) -> dict[str, str]:
    return {name: _part_sha256(path) for name, path in {"nt_msg.db": source, **companions}.items() if path.is_file()}


def _qq_bundle_sha256(source: Path) -> str:
    companions = {name: source.parent / name for name in ("profile_info.db", "group_info.db", "recent_contact.db")}
    return hashlib.sha256(json.dumps(_bundle_parts(source, companions), sort_keys=True).encode()).hexdigest()



def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row_digest(row) -> str:
    digest = hashlib.sha256()
    for value in row:
        if isinstance(value, bytes):
            payload = b"b" + value
        elif value is None:
            payload = b"jnull"
        elif type(value) is int:
            payload = b"j" + str(value).encode()
        else:
            payload = b"j" + json.dumps(value, ensure_ascii=False).encode()
        digest.update(str(len(payload)).encode() + b":" + payload)
    return digest.hexdigest()


def _direction(value: int | None) -> str:
    return {0: "incoming", 1: "outgoing", 2: "outgoing", 3: "system"}.get(value, "unknown")


class AssistantService(WorkspaceFeatures):
    def __init__(self, data_dir: Path, on_progress=None) -> None:
        self.on_progress = on_progress or (lambda message: None)
        self.data_dir = data_dir.resolve()
        self.storage = Storage(data_dir)
        self.qq_sources = QQSourceAdapter(self.data_dir, self.storage)
        self.media_store = MediaStore(self)
        self.ai = GroupAI(self)
        self.chat_memory = ChatMemory(self)
        self.workspace_agent = WorkspaceAgent(self)

    def health(self) -> dict[str, Any]:
        with self.storage.connect() as conn:
            messages = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        return {
            "name": "QQ Insight local core",
            "version": "0.18.2-rel",
            "mode": "offline_rules_only",
            "message_count": messages,
            "capabilities": {"qq": True, "wechat": False, "sqlcipher": self.qq_sources.can_decrypt},
        }

    def discover_sources(self, platform: str = "qq", extra_roots: list[str] | None = None) -> dict[str, Any]:
        if platform != "qq":
            return {"platform": platform, "supported": False, "items": [], "message": "微信适配接口已预留，当前版本尚未实现。"}
        result = self.qq_sources.discover(extra_roots)
        with self.storage.connect() as conn:
            result["accounts"] = [dict(row) for row in conn.execute(
                "SELECT account_id,'QQ '||account_id AS account_label,'qq' AS platform,1 AS offline "
                "FROM (SELECT account_id FROM conversations WHERE platform='qq' UNION SELECT account_id FROM imports WHERE platform='qq') ORDER BY account_id")]
        return result

    def export_archive(self, path: str) -> dict[str, Any]:
        try:
            result = export_database(self.storage, path, self.on_progress)
            return result
        except TransferError as exc:
            raise CoreError(exc.code, str(exc)) from exc
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise CoreError("EXPORT_FAILED", "导出失败，请检查目标目录权限和剩余空间。已有文件未被覆盖。") from exc

    def roster_scope(self, account_id, conversation_id, platform='qq'):
        return roster_scope(self, account_id, conversation_id, platform)

    def member_cache_info(self, account_id, conversation_id, platform='qq'):
        return cache_info(self, account_id, conversation_id, platform)

    def export_roster(self, path, account_id, kind='groups', conversation_id='', platform='qq', online=None, cache_stamp=None):
        return export_roster(self, path, account_id, kind, conversation_id, platform, online, cache_stamp)

    def manual_import(self, path: str, format: str, account_id: str = "", database_key: str = "",
                      import_mode: str = "incremental") -> dict[str, Any]:
        self._validate_import_mode(import_mode)
        if format == "app_db":
            try:
                result = import_database(self.storage, path, self.on_progress)
                with self.storage.connect() as conn:
                    images = conn.execute("SELECT DISTINCT a.sha256,a.mime,a.data FROM favorites f JOIN media_assets a ON a.sha256=f.asset_id WHERE f.media_index>=0")
                    for image in images:
                        try: self.media_store.save_favorite(tuple(image))
                        except OSError: result.setdefault('warnings',[]).append('图片数据已保存在数据库，收藏目录暂未能写入。')
                return result
            except TransferError as exc:
                raise CoreError(exc.code, str(exc)) from exc
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                raise CoreError("ARCHIVE_INVALID", "数据库合并失败：文件损坏、结构不兼容或空间不足。本次合并已回滚。") from exc
        if format not in ("qq_plain", "qq_encrypted"):
            raise CoreError("INVALID_PARAMS", "请选择支持的数据库类型。")
        if not isinstance(account_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", account_id):
            raise CoreError("INVALID_PARAMS", "请填写所属 QQ 号或选择已有账号。")
        source = Path(path).expanduser().resolve()
        if source == self.storage.path.resolve():
            raise CoreError("SOURCE_INVALID", "当前文件是应用数据库，请选择软件数据库导入。")
        if format == "qq_plain":
            companions = {name: source.parent / name for name in self.qq_sources.companion_tables
                          if (source.parent / name).is_file() and self.qq_sources.source_kind(source.parent / name) == "plaintext"}
            return self.import_snapshot(path, account_id, companion_paths=companions, import_mode=import_mode)
        if not isinstance(database_key, str) or len(database_key) != 16 or not database_key.isascii():
            raise CoreError("DECRYPTION_KEY_REQUIRED", "请输入该数据库对应的 16 字符 ASCII 密钥。")
        return self.prepare_source(path, account_id, confirm_decryption=True, database_key=database_key,
                                   import_mode=import_mode, source_format="qq_encrypted")

    @staticmethod
    def _validate_import_mode(import_mode: str) -> None:
        if import_mode not in ("incremental", "full"):
            raise CoreError("INVALID_PARAMS", "更新模式必须为 incremental 或 full")

    def _saved_parts(self, platform: str, account_id: str, origin: str) -> dict[str, str]:
        with self.storage.connect() as conn:
            return dict(conn.execute("SELECT part,digest FROM import_parts WHERE platform=? AND account_id=? AND source_origin=?",
                                     (platform, account_id, origin)).fetchall())

    def prepare_source(self, path: str, account_id: str, account_label: str = "", platform: str = "qq",
                       confirm_decryption: bool = False, database_key: str = "", import_mode: str = "incremental",
                       source_format: str = "") -> dict[str, Any]:
        self._validate_import_mode(import_mode)
        if platform != "qq":
            raise CoreError("PLATFORM_NOT_IMPLEMENTED", "当前只实现 QQ。")
        source = Path(path).expanduser().resolve()
        kind = self.qq_sources.source_kind(source) if source.is_file() else None
        if source_format not in ("", "qq_encrypted"):
            raise CoreError("INVALID_PARAMS", "数据源格式无效。")
        if source_format == "qq_encrypted":
            if not source.is_file() or source.stat().st_size <= 1024 or kind == "plaintext":
                raise CoreError("SOURCE_INVALID", "所选文件不是支持的 NTQQ 加密库，请检查导入类型。")
            kind = "encrypted"
        if kind == "plaintext":
            return self.import_snapshot(str(source), account_id, account_label, platform, import_mode=import_mode)
        if kind != "encrypted":
            raise CoreError("SOURCE_INVALID", "自动识别到的文件不是支持的 NTQQ 数据库。")
        if not confirm_decryption:
            raise CoreError("DECRYPTION_CONFIRM_REQUIRED", "解密将在应用私有临时目录生成明文副本，导入后删除。",
                            {"account_id": account_id, "requires_key": True})
        self.on_progress("正在比较消息、联系人和群资料的更新状态…")
        companions = {name: source.parent / name for name in self.qq_sources.companion_tables
                      if (source.parent / name).is_file() and (source.parent / name).stat().st_size > 1024}
        parts = _bundle_parts(source, companions)
        origin = str(source)
        with self.storage.connect() as conn:
            prior = conn.execute("SELECT projection_version FROM imports WHERE platform=? AND account_id=? AND source_path=? ORDER BY imported_at DESC LIMIT 1",
                                 (platform, account_id, origin)).fetchone()
        mode = "full" if not prior or prior[0] < PROJECTION_VERSION else import_mode
        saved = self._saved_parts(platform, account_id, origin)
        selected = set(parts) if mode == "full" else {name for name, digest in parts.items() if saved.get(name) != digest}
        if not selected:
            return self._apply_import(None, {}, origin, parts, {}, account_id, account_label, platform, mode)
        try:
            self.on_progress("正在解密有变化的数据库…" if mode == "incremental" else "正在完整解密数据库…")
            with self.qq_sources.decrypted_message_tables(source, database_key, include_names=selected) as plain:
                if parts != _bundle_parts(source, companions):
                    raise CoreError("SOURCE_BUSY", "读取期间数据库发生变化，请退出 QQ 后重试。")
                successful = {name: parts[name] for name in plain}
                warnings = [f"{name} 未能读取，本次保留原资料，下次重试。" for name in selected - plain.keys()]
                result = self._apply_import(plain.get("nt_msg.db"), {name: value for name, value in plain.items() if name != "nt_msg.db"},
                                            origin, parts, successful, account_id, account_label, platform, mode, warnings)
        except SourceError as exc:
            raise CoreError(exc.code, str(exc), exc.data) from exc
        result["decrypted"] = True
        return result

    def import_snapshot(self, path: str, account_id: str = "legacy", account_label: str = "", platform: str = "qq",
                        source_fingerprint: str | None = None, source_name: str | None = None,
                        companion_paths: dict[str, Path] | None = None, import_mode: str = "incremental") -> dict[str, Any]:
        self._validate_import_mode(import_mode)
        if platform != "qq":
            raise CoreError("PLATFORM_NOT_IMPLEMENTED", "当前只实现 QQ 数据导入。")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise CoreError("SOURCE_NOT_FOUND", "请选择存在的明文 SQLite 文件")
        with source.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise CoreError("SOURCE_INVALID", "该文件不是明文 SQLite 快照")
        try:
            self.qq_sources.assert_stable(source)
        except SourceError as exc:
            raise CoreError(exc.code, str(exc), exc.data) from exc
        companions = {name: Path(value) for name, value in (companion_paths or {}).items() if name in self.qq_sources.companion_tables}
        parts = _bundle_parts(source, companions)
        checked_parts = dict(parts)
        if source_fingerprint:
            parts["nt_msg.db"] = source_fingerprint
        origin = source_name or str(source)
        with self.storage.connect() as conn:
            prior = conn.execute("SELECT projection_version FROM imports WHERE platform=? AND account_id=? AND source_path=? ORDER BY imported_at DESC LIMIT 1",
                                 (platform, account_id, origin)).fetchone()
        mode = "full" if not prior or prior[0] < PROJECTION_VERSION else import_mode
        saved = self._saved_parts(platform, account_id, origin)
        selected = set(parts) if mode == "full" else {name for name, digest in parts.items() if saved.get(name) != digest}
        # Pin plaintext inputs too. A stable WAL belongs to the snapshot; never
        # checkpoint it on the user's source or read its main file as immutable.
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=self.data_dir) as folder:
            copies = {}
            for name, original in {"nt_msg.db": source, **companions}.items():
                if name not in selected:
                    continue
                try:
                    self.qq_sources.assert_stable(original)
                except SourceError as exc:
                    raise CoreError(exc.code, str(exc), exc.data) from exc
                copied = Path(folder) / name
                shutil.copyfile(original, copied)
                wal = Path(str(original) + "-wal")
                if wal.is_file() and wal.stat().st_size:
                    shutil.copyfile(wal, Path(str(copied) + "-wal"))
                    snapshot_conn = sqlite3.connect(copied)
                    try:
                        checkpoint = snapshot_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    finally:
                        snapshot_conn.close()
                    if checkpoint[0]:
                        raise CoreError("SOURCE_BUSY", "无法固定明文快照，请退出 QQ 后重试。")
                copies[name] = copied
            if checked_parts != _bundle_parts(source, companions):
                raise CoreError("SOURCE_BUSY", "复制期间数据库发生变化，请退出 QQ 后重试。")
            return self._apply_import(copies.get("nt_msg.db"), {name: value for name, value in copies.items() if name != "nt_msg.db"},
                                      origin, parts, {name: parts[name] for name in selected}, account_id, account_label, platform, mode)

    def _apply_import(self, source, companions, origin, parts, successful, account_id, account_label, platform, mode, warnings=None):
        changes = {"scanned": 0, "added": 0, "updated": 0, "unchanged": 0}
        warnings = list(warnings or [])
        fingerprint = hashlib.sha256(json.dumps([platform, account_id, origin, parts], sort_keys=True).encode()).hexdigest()
        try:
            with self.storage.connect() as target:
                target.execute("BEGIN IMMEDIATE")
                prior = target.execute("SELECT c2c_count,group_count FROM imports WHERE platform=? AND account_id=? AND source_path=? ORDER BY imported_at DESC LIMIT 1",
                                       (platform, account_id, origin)).fetchone()
                counts = {"c2c": prior[0] if prior else 0, "group": prior[1] if prior else 0}
                remaining_companions = dict(companions)
                preloaded = {}
                if source is not None and not target.execute(
                        "SELECT 1 FROM messages WHERE platform=? AND account_id=? LIMIT 1", (platform, account_id)).fetchone():
                    # First import: populate the small identity tables before decoding
                    # so every message is written once with its final display fields.
                    self.on_progress("正在预载联系人与群资料，避免首次导入后逐条回填…")
                    for name, field, importer in (("profile_info.db", "profiles", self._import_qq_profiles),
                                                   ("group_info.db", "groups", self._import_qq_groups)):
                        if name in remaining_companions:
                            preloaded[field] = importer(remaining_companions.pop(name), account_id, target, mode)
                if source is not None:
                    self.on_progress("正在增量比对聊天记录，仅解析新增与变化消息…" if mode == "incremental" else "正在全量解析聊天记录…")
                    source_conn = self._open_snapshot(source)
                    try:
                        for table, kind in (("c2c_msg_table", "c2c"), ("group_msg_table", "group")):
                            stats = self._import_table(source_conn, table, kind, platform, account_id, target, mode)
                            counts[kind] = stats["scanned"]
                            for key in changes:
                                changes[key] += stats[key]
                    finally:
                        source_conn.close()
                self.on_progress("正在更新联系人与群资料（仅回填变化项）…" if mode == "incremental" else "正在更新联系人与群资料（全量校验）…")
                metadata = self._import_qq_metadata(remaining_companions, account_id, target, mode)
                metadata.update(preloaded)
                for name, digest in successful.items():
                    target.execute("INSERT INTO import_parts VALUES(?,?,?,?,?) ON CONFLICT(platform,account_id,source_origin,part) DO UPDATE SET digest=excluded.digest",
                                   (platform, account_id, origin, name, digest))
                if successful:
                    target.execute("INSERT INTO imports(source_path,source_hash,imported_at,c2c_count,group_count,platform,account_id,account_label,projection_version) VALUES(?,?,?,?,?,?,?,?,?) "
                                   "ON CONFLICT(source_hash) DO UPDATE SET source_path=excluded.source_path,imported_at=excluded.imported_at,c2c_count=excluded.c2c_count,group_count=excluded.group_count,projection_version=excluded.projection_version",
                                   (origin, fingerprint, datetime.now(timezone.utc).isoformat(), counts["c2c"], counts["group"], platform, account_id, account_label, PROJECTION_VERSION))
                seq = target.execute("SELECT coalesce(max(seq),0) FROM message_changes WHERE platform=? AND account_id=?", (platform, account_id)).fetchone()[0]
        except sqlite3.Error as exc:
            raise CoreError("SOURCE_UNREADABLE", "导入失败，本次更新已回滚，请重试。") from exc
        status = "already_imported" if not successful and not warnings else "reindexed" if mode == "full" and prior else "updated" if prior else "imported"
        return {"status": status, "c2c_count": counts["c2c"], "group_count": counts["group"], "total": sum(counts.values()),
                "account_id": account_id, "import_mode": mode, "changes": changes, "metadata": metadata, "last_change_seq": seq, "warnings": warnings}

    def _import_table(self, source, table, kind, platform, account_id, target, mode):
        needed = ["40001", "40011", "40012", "40013", "40020", "40021", "40030", "40033", "40050", "40800"]
        present = {row[1] for row in source.execute(f"PRAGMA table_info({_quote(table)})")}
        if not set(needed).issubset(present):
            raise CoreError("SOURCE_UNSUPPORTED", f"{table} 字段与当前 QQ 适配器不匹配")
        select_parts = [f'{_quote(column)} AS c{column}' for column in needed]
        select_parts.extend(f'{_quote(column)} AS c{column}' if column in present else f'NULL AS c{column}' for column in ("40090", "40093", "40002", "40003", "40900"))
        rows = source.execute(f"SELECT {', '.join(select_parts)} FROM {_quote(table)}")
        stats = {"scanned": 0, "added": 0, "updated": 0, "unchanged": 0}
        profiles = {}
        for profile in target.execute("SELECT * FROM qq_profiles WHERE account_id=?", (account_id,)):
            for identity in (profile["uid"], profile["qq"]):
                if identity:
                    profiles[identity] = profile
        groups = {}
        for group in target.execute("SELECT * FROM qq_groups WHERE account_id=?", (account_id,)):
            for identity in (group["group_uid"], group["group_qq"], group["identity_key"]):
                if identity:
                    groups[identity] = group
        columns = "id,conversation_id,source_key,sent_at,direction,raw_direction,sender_key,text,content_kind,segment_count,parse_status,raw_blob,outer_type,subtype,platform,account_id,sender_qq,sender_name,media_json,source_digest,sync_key,reply_json,sender_nickname,sender_card"
        updates = ",".join(f"{column}=excluded.{column}" for column in columns.split(",") if column not in ("id", "source_key"))
        differs = " OR ".join(f"messages.{column} IS NOT excluded.{column}" for column in columns.split(",") if column not in ("id", "source_key"))
        message_sql = f"INSERT INTO messages({columns}) VALUES({','.join('?' for _ in columns.split(','))}) ON CONFLICT(source_key) DO UPDATE SET {updates} WHERE {differs}"
        conversation_sql = ("INSERT INTO conversations(id,kind,title,updated_at,platform,account_id,peer_uid,peer_qq,display_name,avatar_ref) VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET updated_at=max(updated_at,excluded.updated_at),"
                    "peer_uid=CASE WHEN excluded.peer_uid<>'' THEN excluded.peer_uid ELSE conversations.peer_uid END,"
                    "peer_qq=CASE WHEN excluded.peer_qq<>'' THEN excluded.peer_qq ELSE conversations.peer_qq END,"
                    "display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE conversations.display_name END,"
                    "title=CASE WHEN excluded.display_name<>'' THEN excluded.title ELSE conversations.title END,"
                    "avatar_ref=CASE WHEN excluded.avatar_ref<>'' THEN excluded.avatar_ref ELSE conversations.avatar_ref END")
        conversation_ids = {(r['kind'],r['peer_qq']): r['id'] for r in target.execute("SELECT id,kind,peer_qq FROM conversations WHERE platform=? AND account_id=? AND peer_qq<>''",(platform,account_id))}
        imported_at = datetime.now(timezone.utc).isoformat()
        while batch := rows.fetchmany(400):
            conversation_batch, message_batch, fts_batch, change_batch = {}, [], [], []
            prepared = []
            variant_batch = []
            for row in batch:
                peer_uid, peer_qq = str(row["c40021"] or ""), str(row["c40030"] or "")
                peer = peer_uid or peer_qq or "unknown"
                key = f"{platform}:{account_id}:{kind}:{peer}:{row['c40001']}"
                prepared.append((row, key, peer, peer_uid, peer_qq, _row_digest(row)))
            keys = [entry[1] for entry in prepared]
            marks = ','.join('?' for _ in keys)
            records = [dict(record) for record in target.execute(f"SELECT * FROM messages WHERE source_key IN ({marks})",keys)]
            existing = {record['source_key']: record for record in records}
            for row, key, peer, peer_uid, peer_qq, digest in prepared:
                stats['scanned'] += 1
                old = existing.get(key)
                sync_key = ''
                previous = old['source_digest'] if old else None
                changed = previous != digest
                if previous is None:
                    stats["added"] += 1
                elif changed:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
                    if mode == "incremental":
                        continue
                conversation_id = old['conversation_id'] if old else conversation_ids.get((kind,peer_qq)) or f"{platform}:{account_id}:{kind}:{peer}"
                if peer_qq: conversation_ids[(kind,peer_qq)] = conversation_id
                direction = int(row["c40013"] or 0)
                sender_key = str(row["c40020"] or row["c40033"] or "")
                sender_qq = str(row["c40033"] or "")
                sender_name = str(row["c40090"] or row["c40093"] or "").strip()
                profile = profiles.get(sender_key) or profiles.get(sender_qq)
                if profile:
                    sender_qq = sender_qq or profile["qq"]
                    sender_name = sender_name or profile["remark"] or profile["nickname"]
                peer_name = sender_name if kind == "c2c" and direction == 0 else ""
                avatar = ""
                if kind == "group":
                    cached = groups.get(peer_uid) or groups.get(peer_qq)
                    if cached:
                        peer_name = cached["remark"] or cached["name"]
                        avatar = cached["avatar_ref"]
                    title = f"{peer_name} · 群 {peer_qq}" if peer_name else f"群聊 {peer_qq or peer_uid or '未知群号'}"
                else:
                    cached = profiles.get(peer_uid) or profiles.get(peer_qq)
                    if cached:
                        peer_name = cached["remark"] or cached["nickname"] or peer_name
                        avatar = cached["avatar_ref"]
                    title = (f"{peer_name} · QQ {peer_qq}" if peer_qq else peer_name) if peer_name else f"私聊 {peer_qq or peer_uid or '未知账号'}"
                conversation_values = (conversation_id, kind, title, int(row["c40050"] or 0), platform, account_id, peer_uid, peer_qq, peer_name, avatar)
                previous_conversation = conversation_batch.get(conversation_id)
                if previous_conversation:
                    merged = list(conversation_values)
                    merged[3] = max(merged[3], previous_conversation[3])
                    for index in (6, 7, 8, 9):
                        merged[index] = merged[index] or previous_conversation[index]
                    if not peer_name:
                        merged[2] = previous_conversation[2]
                    conversation_values = tuple(merged)
                conversation_batch[conversation_id] = conversation_values
                details = decode_message_details(row["c40800"], int(row["c40011"] or 0))
                details['replies'] = details.get('replies', []) or decode_cached_replies(row['c40900'])
                message_id = old['id'] if old else f"msg:{key}"
                raw_blob = row['c40800']
                if old:
                    if old['text'] and not old['text'].startswith('[') and str(details['text']).startswith('['):
                        details['text'],details['content_kind'],raw_blob = old['text'],old['content_kind'],old['raw_blob']
                    if old['text'] != details['text']:
                        variant_batch.append((message_id, hashlib.sha256((old['text']+old['media_json']).encode()).hexdigest(),old['text'],old['media_json']))
                    details['media'] = merge_media(json.loads(old['media_json'] or '[]'),details['media'])
                    details['replies'] = details.get('replies') or json.loads(old['reply_json'] or '[]')
                    sender_name = sender_name or old['sender_name']
                    sender_qq = sender_qq or old['sender_qq']
                message_batch.append((message_id, conversation_id, key, int(row["c40050"] or 0), _direction(direction), direction, sender_key,
                                str(details["text"]), str(details["content_kind"]), int(details["segment_count"]), "partial" if int(details["semantic_status"]) >= 0 else "unknown",
                                raw_blob, row["c40011"], row["c40012"], platform, account_id, sender_qq, sender_name, json.dumps(details["media"], ensure_ascii=False), digest, sync_key, json.dumps(details.get("replies",[]),ensure_ascii=False),
                                str(row['c40093'] or '').strip() if kind == 'group' else '', str(row['c40090'] or '').strip() if kind == 'group' else ''))
                fts_batch.append((message_id, str(details["text"])))
                if changed:
                    change_batch.append((platform, account_id, message_id, "added" if previous is None else "updated", imported_at))
                current = dict(zip(columns.split(','),message_batch[-1]))
                existing[key] = current
            target.executemany(conversation_sql, conversation_batch.values())
            target.executemany(message_sql, message_batch)
            target.executemany('INSERT OR IGNORE INTO message_variants VALUES(?,?,?,?)',variant_batch)
            self.storage.index_messages(target, fts_batch)
            target.executemany("INSERT INTO message_changes(platform,account_id,message_id,change_kind,imported_at) VALUES(?,?,?,?,?)", change_batch)
            if stats["scanned"] % 2000 == 0:
                self.on_progress(f"已检查 {stats['scanned']} 条{'私聊' if kind == 'c2c' else '群聊'}，新增 {stats['added']}、变化 {stats['updated']} 条…")
        return stats

    @staticmethod
    def _open_snapshot(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _import_qq_metadata(self, companions: dict[str, Path], account_id: str, target=None, mode="full") -> dict[str, int]:
        profile_count = self._import_qq_profiles(companions.get("profile_info.db"), account_id, target, mode)
        group_count = self._import_qq_groups(companions.get("group_info.db"), account_id, target, mode)
        avatar_count = self._import_recent_avatars(companions.get("recent_contact.db"), account_id, target, mode)
        return {"profiles": profile_count, "groups": group_count, "local_avatars": avatar_count}

    def _import_qq_profiles(self, path: Path | None, account_id: str, target=None, mode="full") -> int:
        if not path:
            return 0
        source = self._open_snapshot(path)
        try:
            columns = {row[1] for row in source.execute('PRAGMA table_info("profile_info_v6")')}
            required = {"1000", "1002", "20002", "20009", "20004"}
            if not required.issubset(columns):
                raise CoreError("SOURCE_UNSUPPORTED", "联系人资料字段不受支持，本次更新已回滚。")
            rows = source.execute('SELECT "1000" AS uid,"1002" AS qq,"20002" AS nickname,"20009" AS remark,"20004" AS avatar FROM "profile_info_v6"')
            count = 0
            with (nullcontext(target) if target is not None else self.storage.connect()) as target:
                for row in rows:
                    uid, qq = str(row["uid"] or ""), str(row["qq"] or "")
                    identity = uid or qq
                    if not identity:
                        continue
                    nickname = str(row["nickname"] or "").strip()
                    remark = str(row["remark"] or "").strip()
                    name = remark or nickname
                    avatar = str(row["avatar"] or "").strip()
                    if not avatar and qq:
                        avatar = f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100"
                    old = target.execute("SELECT uid,qq,nickname,remark,avatar_ref FROM qq_profiles WHERE account_id=? AND identity_key=?", (account_id, identity)).fetchone()
                    if mode == "incremental" and old and tuple(old) == (uid, qq, nickname, remark, avatar):
                        continue
                    old_name = (old["remark"] or old["nickname"]) if old else ""
                    target.execute(
                        "INSERT INTO qq_profiles(account_id,identity_key,uid,qq,nickname,remark,avatar_ref) VALUES(?,?,?,?,?,?,?) "
                        "ON CONFLICT(account_id,identity_key) DO UPDATE SET uid=excluded.uid,qq=excluded.qq,nickname=excluded.nickname,remark=excluded.remark,avatar_ref=excluded.avatar_ref",
                        (account_id, identity, uid, qq, nickname, remark, avatar),
                    )
                    if name:
                        title = f"{name} · QQ {qq}" if qq else name
                        for column, value in (("peer_uid", uid), ("peer_qq", qq)):
                            if value:
                                target.execute(f"UPDATE conversations SET display_name=?,avatar_ref=CASE WHEN ?<>'' THEN ? ELSE avatar_ref END,title=? WHERE account_id=? AND kind='c2c' AND {column}=?",
                                               (name, avatar, avatar, title, account_id, value))
                        for column, value in (("sender_key", uid), ("sender_qq", qq)):
                            if value:
                                target.execute("UPDATE messages SET sender_qq=CASE WHEN sender_qq='' THEN ? ELSE sender_qq END,"
                                               "sender_name=CASE WHEN sender_name='' OR sender_name=? THEN ? ELSE sender_name END "
                                               f"WHERE account_id=? AND {column}=? AND (sender_qq='' OR sender_name='' OR sender_name=?)",
                                               (qq, old_name, name, account_id, value, old_name))
                    count += 1
                    if count % 200 == 0:
                        self.on_progress(f"已更新 {count} 个联系人资料…")
            return count
        finally:
            source.close()

    def _import_qq_groups(self, path: Path | None, account_id: str, target=None, mode="full") -> int:
        if not path:
            return 0
        source = self._open_snapshot(path)
        try:
            columns = {row[1] for row in source.execute('PRAGMA table_info("group_detail_info_ver1")')}
            if not {"60001", "60007"}.issubset(columns):
                raise CoreError("SOURCE_UNSUPPORTED", "群资料字段不受支持，本次更新已回滚。")
            remark_expr = '"60026"' if "60026" in columns else "NULL"
            count = 0
            with (nullcontext(target) if target is not None else self.storage.connect()) as target:
                import_cache(source, target, account_id)
                rows = source.execute(f'SELECT "60001" AS group_qq,"60007" AS name,{remark_expr} AS remark FROM "group_detail_info_ver1"')
                for row in rows:
                    group_qq = str(row["group_qq"] or "")
                    if not group_qq:
                        continue
                    name = str(row["name"] or "").strip()
                    remark = str(row["remark"] or "").strip()
                    display = remark or name
                    avatar = f"https://p.qlogo.cn/gh/0/{group_qq}/100"
                    old = target.execute("SELECT name,remark FROM qq_groups WHERE account_id=? AND identity_key=?", (account_id, group_qq)).fetchone()
                    if mode == "incremental" and old and tuple(old) == (name, remark):
                        continue
                    target.execute(
                        "INSERT INTO qq_groups(account_id,identity_key,group_qq,name,remark,avatar_ref) VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(account_id,identity_key) DO UPDATE SET group_qq=excluded.group_qq,name=excluded.name,remark=excluded.remark,avatar_ref=CASE WHEN qq_groups.avatar_ref='' THEN excluded.avatar_ref ELSE qq_groups.avatar_ref END",
                        (account_id, group_qq, group_qq, name, remark, avatar),
                    )
                    if display:
                        title = f"{display} · 群 {group_qq}"
                        for column in ("peer_qq", "peer_uid"):
                            target.execute(f"UPDATE conversations SET display_name=?,avatar_ref=CASE WHEN avatar_ref='' THEN ? ELSE avatar_ref END,title=? WHERE account_id=? AND kind='group' AND {column}=?",
                                           (display, avatar, title, account_id, group_qq))
                    count += 1
            return count
        finally:
            source.close()

    def _import_recent_avatars(self, path: Path | None, account_id: str, target=None, mode="full") -> int:
        if not path:
            return 0
        source = self._open_snapshot(path)
        try:
            columns = {row[1] for row in source.execute('PRAGMA table_info("recent_contact_v3_table")')}
            if not {"40021", "41110"}.issubset(columns):
                raise CoreError("SOURCE_UNSUPPORTED", "头像资料字段不受支持，本次更新已回滚。")
            rows = source.execute('SELECT "40021" AS peer_uid,"41110" AS avatar FROM "recent_contact_v3_table" WHERE "41110" IS NOT NULL AND "41110"<>\'\'')
            count = 0
            with (nullcontext(target) if target is not None else self.storage.connect()) as target:
                for row in rows:
                    peer_uid = str(row["peer_uid"] or "")
                    avatar = str(row["avatar"] or "").strip()
                    avatar_path = Path(avatar)
                    if not peer_uid or not avatar or not avatar_path.is_absolute() or not avatar_path.is_file():
                        continue
                    before = target.total_changes
                    for column in ("peer_uid", "peer_qq"):
                        target.execute(f"UPDATE conversations SET avatar_ref=? WHERE account_id=? AND kind='group' AND {column}=? AND avatar_ref<>?",
                                       (avatar, account_id, peer_uid, avatar))
                    for column in ("identity_key", "group_qq"):
                        target.execute(f"UPDATE qq_groups SET avatar_ref=? WHERE account_id=? AND {column}=? AND avatar_ref<>?",
                                       (avatar, account_id, peer_uid, avatar))
                    count += int(target.total_changes > before)
            return count
        finally:
            source.close()

    @staticmethod
    def _scope(account_id: str | None, platform: str, alias: str = "") -> tuple[str, tuple[Any, ...]]:
        prefix = f"{alias}." if alias else ""
        if account_id:
            return f"{prefix}platform=? AND {prefix}account_id=?", (platform, account_id)
        return f"{prefix}platform=?", (platform,)

    def overview(self, account_id: str | None = None, platform: str = "qq") -> dict[str, Any]:
        message_where, params = self._scope(account_id, platform)
        conversation_where, conversation_params = self._scope(account_id, platform)
        with self.storage.connect() as conn:
            total, latest, nontext = conn.execute(
                f"SELECT count(*),max(sent_at),coalesce(sum(content_kind NOT LIKE '%文本%' AND text LIKE '[%'),0) FROM messages WHERE {message_where}", params).fetchone()
            conversations = conn.execute(f"SELECT count(*) FROM conversations WHERE {conversation_where}", conversation_params).fetchone()[0]
            recent = conn.execute(f"SELECT id,title,kind,updated_at,peer_qq,display_name,avatar_ref FROM conversations WHERE {conversation_where} ORDER BY updated_at DESC LIMIT 5", conversation_params).fetchall()
        return {"message_count": total, "conversation_count": conversations, "latest_timestamp": latest, "nontext_count": nontext, "recent_conversations": [dict(row) for row in recent], "analysis_mode": "本地规则，不调用外部 AI"}

    @staticmethod
    def _page_cursor(cursor, time_field: str):
        if cursor is None:
            return None
        if (not isinstance(cursor, dict) or type(cursor.get(time_field)) is not int
                or not isinstance(cursor.get("id"), str) or not cursor["id"]):
            raise CoreError("INVALID_PARAMS", "分页游标无效，请重新查询")
        return cursor[time_field], cursor["id"]

    @staticmethod
    def _like(query: str) -> str:
        if not isinstance(query, str) or len(query) > 1000:
            raise CoreError("INVALID_PARAMS", "搜索内容必须为不超过1000字的文本")
        return "%" + query.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"

    def list_conversations(self, query: str = "", limit: int = 200, account_id: str | None = None,
                           platform: str = "qq", cursor: dict | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise CoreError("INVALID_PARAMS", "limit 必须在 1 到 500 之间")
        where, scope = self._scope(account_id, platform, "c")
        pattern = self._like(query)
        params = list(scope)
        if query.strip():
            params.extend([pattern, pattern, pattern])
            where += " AND (c.title LIKE ? ESCAPE '!' OR c.peer_qq LIKE ? ESCAPE '!' OR c.display_name LIKE ? ESCAPE '!')"
        point = self._page_cursor(cursor, "updated_at")
        if point:
            pinned = cursor.get('pinned', 0)
            if pinned not in (0,1): raise CoreError('INVALID_PARAMS','置顶分页游标无效。')
            where += " AND (c.pinned,c.updated_at,c.id)<(?,?,?)"
            params.extend((pinned,*point))
        with self.storage.connect() as conn:
            rows = conn.execute(f"SELECT c.id,c.title,c.kind,c.updated_at,c.peer_uid,c.peer_qq,c.display_name,c.avatar_ref,c.pinned,"
                                f"(SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count "
                                f"FROM conversations c WHERE {where} ORDER BY c.pinned DESC,c.updated_at DESC,c.id DESC LIMIT ?",
                                (*params, limit + 1)).fetchall()
        items = [dict(row) for row in rows[:limit]]
        more = len(rows) > limit
        return {"items": items, "has_more": more,
                "next_cursor": {"pinned": items[-1]["pinned"], "updated_at": items[-1]["updated_at"], "id": items[-1]["id"]} if more else None}

    def list_messages(self, conversation_id: str, limit: int = 100, account_id: str | None = None,
                      platform: str = "qq", query: str = "", sender: str = "", direction: str = "",
                      cursor: dict | None = None, order: str | None = None, recent: bool = False) -> dict[str, Any]:
        if not isinstance(conversation_id, str) or not conversation_id:
            raise CoreError("INVALID_PARAMS", "请选择会话")
        result = self.search_messages(query, limit, account_id, platform, conversation_id, sender, direction, cursor, order, recent)
        if order is None: result["items"].reverse()
        return result

    def search_messages(self, query: str = "", limit: int = 80, account_id: str | None = None,
                        platform: str = "qq", conversation_id: str | None = None, sender: str = "",
                        direction: str = "", cursor: dict | None = None, order: str | None = None, recent: bool = False) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise CoreError("INVALID_PARAMS", "limit 必须在 1 到 500 之间")
        if order not in (None, 'asc', 'desc') or type(recent) is not bool:
            raise CoreError('INVALID_PARAMS', '消息排序参数无效。')
        sort = 'ASC' if order == 'asc' and not recent else 'DESC'
        comparison = '>' if sort == 'ASC' else '<'
        if direction not in ("", "incoming", "outgoing", "system", "unknown"):
            raise CoreError("INVALID_PARAMS", "消息方向无效")
        pattern, sender_pattern = self._like(query), self._like(sender)
        where, scope = self._scope(account_id, platform, "m")
        params = list(scope)
        if conversation_id:
            where += " AND m.conversation_id=?"
            params.append(conversation_id)
        if query.strip():
            columns = ("m.text", "m.sender_name", "m.sender_qq", "c.title", "c.peer_qq")
            where += " AND (" + " OR ".join(f"{column} LIKE ? ESCAPE '!'" for column in columns) + ")"
            params.extend([pattern] * len(columns))
        if sender.strip():
            where += " AND (m.sender_name LIKE ? ESCAPE '!' OR m.sender_qq LIKE ? ESCAPE '!' OR m.sender_key LIKE ? ESCAPE '!')"
            params.extend([sender_pattern] * 3)
        if direction and direction not in ('incoming','outgoing'):
            where += " AND m.direction=?"
            params.append(direction)
        point = self._page_cursor(cursor, "sent_at")
        if point:
            where += f" AND (m.sent_at,m.id){comparison}(?,?)"
            params.extend(point)
        with self.storage.connect() as conn:
            if direction in ('incoming','outgoing'):
                accounts=[account_id] if account_id else [r[0] for r in conn.execute('SELECT DISTINCT account_id FROM conversations WHERE platform=?',(platform,))]
                clauses=["m.direction='outgoing'"];self_params=[]
                for account in accounts:
                    ids=sorted(self._self_ids(conn,account));marks=','.join('?' for _ in ids)
                    clauses.append(f'(m.account_id=? AND (m.sender_qq IN ({marks}) OR m.sender_key IN ({marks})))');self_params.extend([account,*ids,*ids])
                predicate='('+' OR '.join(clauses)+')'
                where+=(" AND m.direction<>'system' AND " if direction=='outgoing' else " AND m.direction='incoming' AND NOT ")+predicate
                params.extend(self_params)
            rows = conn.execute(f"SELECT m.*,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE {where} ORDER BY m.sent_at {sort},m.id {sort} LIMIT ?", (*params,limit+1)).fetchall()
            more = len(rows) > limit
            items = self._message_items(conn, rows[:limit])
        next_cursor = {"sent_at": items[-1]["sent_at"], "id": items[-1]["id"]} if more else None
        if recent and order == 'asc': items.reverse()
        return {"items": items, "has_more": more, "next_cursor": next_cursor}

    def save_profile(self, role_text: str, conversation_id: str | None = None, account_id: str | None = None, platform: str = "qq") -> dict[str, Any]:
        if not isinstance(role_text, str): raise CoreError('INVALID_PARAMS', '角色应为文本。')
        role_text = role_text.strip()[:1000]
        if conversation_id:
            conversation=self._conversation(conversation_id, account_id, platform)
            with self.storage.connect() as conn:
                conn.execute('INSERT INTO conversation_preferences VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at', (conversation_id, role_text, datetime.now(timezone.utc).isoformat()))
            if conversation['kind']=='group':self.ai.save_group(conversation_id,account_id,{'role':role_text},platform)
            return self.get_profile(conversation_id, account_id, platform)
        with self.storage.connect() as conn:
            conn.execute("INSERT INTO profile(id,role_text,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at", (role_text, datetime.now(timezone.utc).isoformat()))
        return self.get_profile()

    def get_profile(self, conversation_id: str | None = None, account_id: str | None = None, platform: str = "qq") -> dict[str, Any]:
        if conversation_id:
            self._conversation(conversation_id, account_id, platform)
            with self.storage.connect() as conn:
                row = conn.execute('SELECT role_text,updated_at FROM conversation_preferences WHERE conversation_id=?', (conversation_id,)).fetchone()
            return {**(dict(row) if row else {'role_text':'','updated_at':''}), 'fallback_role':''}
        with self.storage.connect() as conn:
            row = conn.execute("SELECT role_text,updated_at FROM profile WHERE id=1").fetchone()
        return dict(row) if row else {"role_text": "", "updated_at": ""}

    def work_digest(self, conversation_id: str | None = None, limit: int = 500, account_id: str | None = None, platform: str = "qq") -> dict[str, Any]:
        if not conversation_id: raise CoreError('GROUP_REQUIRED', '请先选择一个群聊，工作概要按群独立生成。')
        self.ai.group(conversation_id, account_id, platform)
        with self.storage.connect() as conn:
            roles = dict(conn.execute('SELECT conversation_id,role_text FROM conversation_preferences'))
            if conversation_id:
                rows = conn.execute("SELECT m.id,m.conversation_id,m.sent_at,m.sender_qq,m.sender_name,m.media_json,m.text,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.conversation_id=? ORDER BY m.sent_at DESC LIMIT ?", (conversation_id, min(limit, 1000))).fetchall()
            else:
                where, params = self._scope(account_id, platform, "m")
                rows = conn.execute(f"SELECT m.id,m.conversation_id,m.sent_at,m.sender_qq,m.sender_name,m.media_json,m.text,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE {where} ORDER BY m.sent_at DESC LIMIT ?", (*params, min(limit, 1000))).fetchall()
        role = roles.get(conversation_id) or ""
        candidates: list[dict[str, Any]] = []
        # A standalone "请" often describes casual conversation, so do not
        # treat it as a task signal without a more specific action.
        signal = re.compile(
            r"(提交|上交|报名|收集(?:表|材料|信息)?|填写|整理|完成|通知|提醒|"
            r"截止|作业|参会|开会|回复|转发|"
            r"请(?:于|在|各位|大家|同学|班委|群主|将|把|及时|务必|尽快|完成|提交|"
            r"上交|填写|报名|收集|整理|回复|转发)|"
            r"需要(?:大家|各位|同学|班委|你|我们|在)|务必)"
        )
        for row in rows:
            text = row["text"]
            role_for_message = roles.get(row['conversation_id']) or ""
            acknowledgement = re.fullmatch(r'[\s\S]{0,30}?(?:收到|已收到|收到了|好的|好哒|明白|了解)(?:[啦了嗯哦好!！。.,，~～\s]|[\U0001F300-\U0001FAFF])*', text.strip())
            # A new directive after the acknowledgement is still a candidate.
            acknowledgement = acknowledgement and not re.search(r'请|务必|需要|确保|截止|明天|今天|安排', text)
            if acknowledgement or text.startswith("[") or not signal.search(text):
                continue
            relevance = "待核实"
            if "@" in text or (role_for_message and any(token and token in text for token in re.split(r"[，、；;\s]+", role_for_message))):
                relevance = "可能与我有关"
            due = self._due_hint(text, row["sent_at"])
            candidates.append({"id": row["id"], "conversation_id": row["conversation_id"], "conversation": row["title"], "sender_name": row["sender_name"], "sender_qq": row["sender_qq"], "text": text[:220], "sent_at": row["sent_at"], "role_context": role_for_message, "relevance": relevance, "due_hint": due, "reason": "命中本地任务线索；请在原文中确认责任人和截止时间"})
        candidates = candidates[:12]
        return {"mode": "local_rules", "role_context": role, "summary": f"已在 {'当前会话' if conversation_id else '最近消息'} 中找到 {len(candidates)} 条待核实事项线索。", "items": candidates, "coverage_note": "仅分析已导入的文本投影；图片、语音、未知段和责任归属需要人工确认。"}

    @staticmethod
    def _due_hint(text: str, timestamp: int) -> str:
        try:
            base = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8)))
        except (OSError, OverflowError, ValueError):
            return "未识别"
        for phrase, offset in (("今天", 0), ("明天", 1), ("后天", 2)):
            if phrase in text:
                return (base + timedelta(days=offset)).strftime("%Y-%m-%d") + "（从原文相对日期推断）"
        match = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", text)
        if match:
            return f"{base.year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}（年份需确认）"
        return "未识别"
