"""Platform source discovery and QQ SQLCipher decryption adapters."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Iterator

try:
    import sqlcipher3.dbapi2 as sqlcipher
except ImportError:
    sqlcipher = None

from .storage import Storage


class SourceError(Exception):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data or {}


class QQSourceAdapter:
    source_names = {"nt_msg.db", "nt_msg_plain.db"}
    companion_tables = {
        "profile_info.db": ("profile_info_v6",),
        "group_info.db": ("group_detail_info_ver1",),
        "recent_contact.db": ("recent_contact_v3_table",),
    }
    skip_dirs = {"node_modules", ".git", ".venv", "cache", "temp", "tmp", "logs"}

    def __init__(self, data_dir: Path, storage: Storage) -> None:
        self.data_dir = data_dir.resolve()
        self.storage = storage

    @property
    def can_decrypt(self) -> bool:
        return sqlcipher is not None

    def discover(self, extra_roots: list[str] | None = None) -> dict[str, Any]:
        roots = self._default_roots()
        for value in (extra_roots or [])[:8]:
            candidate = Path(value).expanduser()
            if candidate.exists():
                roots.append(candidate.resolve())
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for root in roots:
            for source in self._find_sources(root):
                normalized = str(source).casefold()
                if normalized in seen:
                    continue
                seen.add(normalized)
                source_kind = self.source_kind(source)
                if not source_kind:
                    continue
                account_id, label = self.account_identity(source)
                stat = source.stat()
                with self.storage.connect() as conn:
                    imported = conn.execute(
                        "SELECT imported_at FROM imports WHERE platform='qq' AND account_id=? ORDER BY imported_at DESC LIMIT 1",
                        (account_id,),
                    ).fetchone()
                    account_number = account_id.removeprefix("qq-") if account_id.startswith("qq-") else ""
                    profile = conn.execute(
                        "SELECT nickname,remark,avatar_ref FROM qq_profiles WHERE account_id=? AND qq=? LIMIT 1",
                        (account_id, account_number),
                    ).fetchone() if account_number.isdigit() else None
                if profile:
                    display_name = str(profile["remark"] or profile["nickname"] or "").strip()
                    if display_name:
                        label = f"{display_name} · QQ {account_number}"
                items.append(
                    {
                        "id": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16],
                        "platform": "qq",
                        "account_id": account_id,
                        "account_label": label,
                        "path": str(source),
                        "source_kind": source_kind,
                        "requires_decryption": source_kind == "encrypted",
                        "size": stat.st_size,
                        "modified_at": int(stat.st_mtime),
                        "last_imported_at": imported["imported_at"] if imported else None,
                        "avatar_ref": profile["avatar_ref"] if profile else "",
                    }
                )
        items.sort(key=lambda item: (item["account_label"], item["source_kind"] != "plaintext", -item["modified_at"]))
        return {"platform": "qq", "supported": True, "items": items, "roots_checked": len(roots)}

    @staticmethod
    def _default_roots() -> list[Path]:
        home = Path.home()
        values = [home / "Documents" / "Tencent Files", home / "Documents" / "QQ"]
        for variable, suffix in (
            ("APPDATA", ("Tencent", "QQ")),
            ("LOCALAPPDATA", ("Tencent", "QQ")),
            ("APPDATA", ("QQ",)),
            ("LOCALAPPDATA", ("QQ",)),
        ):
            base = os.environ.get(variable)
            if base:
                values.append(Path(base).joinpath(*suffix))
        roots: list[Path] = []
        seen: set[str] = set()
        for value in values:
            if value.exists() and str(value).casefold() not in seen:
                seen.add(str(value).casefold())
                roots.append(value.resolve())
        return roots

    def _find_sources(self, root: Path, max_depth: int = 7) -> Iterable[Path]:
        if root.is_file():
            if root.name.casefold() in self.source_names:
                yield root.resolve()
            return
        root_depth = len(root.parts)
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - root_depth
            directories[:] = [
                name for name in directories
                if name.casefold() not in self.skip_dirs and depth < max_depth
            ]
            for name in files:
                if name.casefold() in self.source_names:
                    yield (current_path / name).resolve()

    @staticmethod
    def source_kind(source: Path) -> str | None:
        try:
            with source.open("rb") as stream:
                header = stream.read(16)
            if header == b"SQLite format 3\x00":
                return "plaintext"
            if source.name.casefold() == "nt_msg.db" and source.stat().st_size > 1024:
                return "encrypted"
        except OSError:
            return None
        return None

    @staticmethod
    def account_identity(source: Path) -> tuple[str, str]:
        for part in reversed(source.parts[:-1]):
            lowered = part.casefold()
            if lowered.startswith("nt_qq_") and len(part) > 6:
                suffix = part[6:]
                return f"qq-{suffix}", f"QQ 账户 {suffix[:12]}"
            if part.isdigit() and 5 <= len(part) <= 14:
                return f"qq-{part}", f"QQ {part}"
        digest = hashlib.sha256(str(source.parent).casefold().encode("utf-8")).hexdigest()[:12]
        return f"qq-{digest}", f"QQ 账户 {digest[:6]}"

    @staticmethod
    def assert_stable(source: Path) -> None:
        journal = Path(str(source) + "-journal")
        if journal.exists():
            raise SourceError("SOURCE_BUSY", "QQ 数据库仍在使用中。请完全退出 QQ 后重试自动解密。")

    @staticmethod
    def snapshot_state(source: Path) -> tuple[tuple[str, int, int], ...]:
        state: list[tuple[str, int, int]] = []
        for candidate in (source, Path(str(source) + "-wal")):
            try:
                stat = candidate.stat()
                state.append((candidate.name, stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                state.append((candidate.name, -1, -1))
        return tuple(state)

    @contextmanager
    def decrypted_message_tables(self, source: Path, database_key: str, include_names: set[str] | None = None) -> Iterator[dict[str, Path]]:
        if sqlcipher is None:
            raise SourceError("DECRYPTION_UNAVAILABLE", "当前发行版未包含 SQLCipher 解密组件。")
        key_bytes = database_key.encode("ascii", errors="ignore")
        if len(key_bytes) != 16 or len(database_key) != 16:
            raise SourceError("DECRYPTION_KEY_REQUIRED", "需要该 QQ 账号对应的 16 字节数据库密钥。")
        self.assert_stable(source)
        companion_sources = {
            name: source.parent / name for name in self.companion_tables
            if (include_names is None or name in include_names) and (source.parent / name).is_file() and (source.parent / name).stat().st_size > 1024
        }
        message_size = source.stat().st_size if include_names is None or "nt_msg.db" in include_names else 0
        required = (message_size + sum(path.stat().st_size for path in companion_sources.values())) * 2 + (256 << 20)
        if shutil.disk_usage(self.data_dir).free < required:
            raise SourceError("INSUFFICIENT_SPACE", "应用数据目录空间不足，无法安全生成解密临时文件。")
        with tempfile.TemporaryDirectory(prefix="decrypt-", dir=self.data_dir) as folder:
            outputs: dict[str, Path] = {}
            output = Path(folder) / "nt_msg_plain.db"
            if include_names is None or "nt_msg.db" in include_names:
                self._decrypt_selected_tables(source, output, database_key, ("c2c_msg_table", "group_msg_table"), required=True)
                outputs["nt_msg.db"] = output
            for name, companion in companion_sources.items():
                try:
                    self.assert_stable(companion)
                    companion_output = Path(folder) / f"{Path(name).stem}_plain.db"
                    if self._decrypt_selected_tables(
                        companion, companion_output, database_key, self.companion_tables[name], required=False
                    ):
                        outputs[name] = companion_output
                except SourceError:
                    # Optional metadata must never prevent the user's messages from importing.
                    continue
            yield outputs

    def _decrypt_selected_tables(
        self, source: Path, output: Path, database_key: str, tables: tuple[str, ...], required: bool
    ) -> bool:
        clear = output.with_name(f"{output.stem}_cipher.db")
        self.assert_stable(source)
        before = self.snapshot_state(source)
        with source.open("rb") as incoming, clear.open("wb") as outgoing:
            incoming.seek(1024)
            while chunk := incoming.read(8 << 20):
                outgoing.write(chunk)
        source_wal = Path(str(source) + "-wal")
        if source_wal.is_file() and source_wal.stat().st_size:
            shutil.copyfile(source_wal, Path(str(clear) + "-wal"))
        if before != self.snapshot_state(source):
            raise SourceError("SOURCE_BUSY", "复制期间 QQ 数据库发生变化。请完全退出 QQ 后重试。")
        return self._export_plain_tables(clear, output, database_key, tables, required)

    @staticmethod
    def _export_plain_tables(
        clear: Path, output: Path, database_key: str,
        requested_tables: tuple[str, ...] = ("c2c_msg_table", "group_msg_table"),
        required: bool = True,
    ) -> bool:
        encrypted = None
        plain = None
        try:
            encrypted = sqlcipher.connect(str(clear), isolation_level=None)
            encrypted.execute("PRAGMA cipher_page_size = 4096")
            safe_key = database_key.replace("'", "''")
            encrypted.execute(f"PRAGMA key = '{safe_key}'")
            encrypted.execute("PRAGMA kdf_iter = 4000")
            encrypted.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
            encrypted.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
            encrypted.execute("SELECT count(*) FROM sqlite_master").fetchone()
            tables = {row[0] for row in encrypted.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            selected = [table for table in requested_tables if table in tables]
            if required and set(requested_tables) - tables:
                raise SourceError("SOURCE_UNSUPPORTED", "解密成功，但数据库缺少当前支持的 QQ 消息表。")
            if not selected:
                return False
            plain = sqlite3.connect(output)
            for table in selected:
                ddl = encrypted.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                plain.execute(ddl)
                column_count = len(encrypted.execute(f'PRAGMA table_info("{table}")').fetchall())
                placeholders = ",".join("?" for _ in range(column_count))
                cursor = encrypted.execute(f'SELECT * FROM "{table}"')
                while rows := cursor.fetchmany(5000):
                    plain.executemany(f'INSERT INTO "{table}" VALUES({placeholders})', rows)
                    plain.commit()
            if plain.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SourceError("DECRYPTION_FAILED", "解密结果未通过 SQLite 完整性检查。")
            return True
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError("DECRYPTION_FAILED", "QQ 数据库解密失败，请检查账号密钥和 QQ 版本。") from exc
        finally:
            if plain is not None:
                plain.close()
            if encrypted is not None:
                encrypted.close()
