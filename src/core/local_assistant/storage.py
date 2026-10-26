"""SQLite storage owned by the app, never the QQ source database."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator
from .member_cache import SCHEMA as MEMBER_SCHEMA


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, source_hash TEXT NOT NULL UNIQUE,
  imported_at TEXT NOT NULL, c2c_count INTEGER NOT NULL, group_count INTEGER NOT NULL,
  platform TEXT NOT NULL DEFAULT 'qq', account_id TEXT NOT NULL DEFAULT 'legacy',
  account_label TEXT NOT NULL DEFAULT '', projection_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0,
  platform TEXT NOT NULL DEFAULT 'qq', account_id TEXT NOT NULL DEFAULT 'legacy',
  peer_uid TEXT NOT NULL DEFAULT '', peer_qq TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '', avatar_ref TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  source_key TEXT NOT NULL UNIQUE, sent_at INTEGER NOT NULL, direction TEXT NOT NULL,
  raw_direction INTEGER, sender_key TEXT, text TEXT NOT NULL, content_kind TEXT NOT NULL,
  segment_count INTEGER NOT NULL DEFAULT 0, parse_status TEXT NOT NULL, raw_blob BLOB,
  outer_type INTEGER, subtype INTEGER, platform TEXT NOT NULL DEFAULT 'qq',
  account_id TEXT NOT NULL DEFAULT 'legacy', sender_qq TEXT NOT NULL DEFAULT '',
  sender_name TEXT NOT NULL DEFAULT '', media_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS qq_profiles (
  account_id TEXT NOT NULL, identity_key TEXT NOT NULL, uid TEXT NOT NULL DEFAULT '',
  qq TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '', remark TEXT NOT NULL DEFAULT '',
  avatar_ref TEXT NOT NULL DEFAULT '', PRIMARY KEY(account_id, identity_key)
);
CREATE TABLE IF NOT EXISTS qq_groups (
  account_id TEXT NOT NULL, identity_key TEXT NOT NULL, group_uid TEXT NOT NULL DEFAULT '',
  group_qq TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', remark TEXT NOT NULL DEFAULT '',
  avatar_ref TEXT NOT NULL DEFAULT '', PRIMARY KEY(account_id, identity_key)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_time ON messages(conversation_id, sent_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(sent_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), role_text TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(message_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS message_fts_keys (message_id TEXT PRIMARY KEY, fts_rowid INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS import_parts (
  platform TEXT NOT NULL, account_id TEXT NOT NULL, source_origin TEXT NOT NULL,
  part TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(platform,account_id,source_origin,part)
);
CREATE TABLE IF NOT EXISTS message_changes (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, account_id TEXT NOT NULL,
  message_id TEXT NOT NULL, change_kind TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_preferences (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), role_text TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_assets (
  sha256 TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS message_media (
  message_id TEXT NOT NULL REFERENCES messages(id), media_index INTEGER NOT NULL,
  sha256 TEXT NOT NULL REFERENCES media_assets(sha256), PRIMARY KEY(message_id,media_index)
);
CREATE TABLE IF NOT EXISTS favorites (
  message_id TEXT NOT NULL REFERENCES messages(id), media_index INTEGER NOT NULL DEFAULT -1,
  created_at TEXT NOT NULL, asset_id TEXT NOT NULL DEFAULT '', PRIMARY KEY(message_id,media_index)
);
CREATE TABLE IF NOT EXISTS media_roots (account_id TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(account_id,path));
CREATE TABLE IF NOT EXISTS message_aliases (account_id TEXT NOT NULL,source_key TEXT NOT NULL,message_id TEXT NOT NULL REFERENCES messages(id),PRIMARY KEY(account_id,source_key));
CREATE TABLE IF NOT EXISTS message_variants (message_id TEXT NOT NULL REFERENCES messages(id),digest TEXT NOT NULL,text TEXT NOT NULL,media_json TEXT NOT NULL,PRIMARY KEY(message_id,digest));
"""


class Storage:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "assistant.db"
        with self.connect() as conn:
            had_fts_keys = conn.execute("SELECT 1 FROM sqlite_master WHERE name='message_fts_keys'").fetchone()
            conn.executescript(SCHEMA)
            conn.executescript(MEMBER_SCHEMA)
            if not had_fts_keys:
                conn.execute("INSERT OR IGNORE INTO message_fts_keys SELECT message_id,rowid FROM messages_fts")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fts_keys_rowid ON message_fts_keys(fts_rowid)")
            self._ensure_column(conn, "imports", "platform", "TEXT NOT NULL DEFAULT 'qq'")
            self._ensure_column(conn, "imports", "account_id", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "imports", "account_label", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "imports", "projection_version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "conversations", "platform", "TEXT NOT NULL DEFAULT 'qq'")
            self._ensure_column(conn, "conversations", "account_id", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "conversations", "peer_uid", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "conversations", "peer_qq", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "conversations", "display_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "conversations", "avatar_ref", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "platform", "TEXT NOT NULL DEFAULT 'qq'")
            self._ensure_column(conn, "messages", "account_id", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "messages", "sender_qq", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "sender_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "sender_nickname", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "sender_card", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "media_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "messages", "source_digest", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "sync_key", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "messages", "reply_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "conversations", "pinned", "INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sync ON messages(platform,account_id,sync_key) WHERE sync_key<>''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_pinned ON conversations(platform,account_id,pinned DESC,updated_at DESC,id DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_account_page ON conversations(platform,account_id,updated_at DESC,id DESC)")
            conn.execute("DROP INDEX IF EXISTS idx_conversations_account")
            conn.execute("DROP INDEX IF EXISTS idx_messages_account_time")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_account_page ON messages(platform, account_id, sent_at DESC, id DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_imports_account ON imports(platform, account_id, imported_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_imports_origin ON imports(platform,account_id,source_path,imported_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qq_profiles_qq ON qq_profiles(account_id, qq)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qq_profiles_uid ON qq_profiles(account_id, uid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qq_groups_qq ON qq_groups(account_id, group_qq)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender_key ON messages(account_id,sender_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender_qq ON messages(account_id,sender_qq)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_peer_uid ON conversations(account_id,kind,peer_uid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_peer_qq ON conversations(account_id,kind,peer_qq)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_message_changes_scope ON message_changes(platform,account_id,seq)")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        if column not in columns:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA cache_size=-32768")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def index_messages(conn: sqlite3.Connection, messages: list[tuple[str, str]]) -> None:
        """Batch indexed FTS replacements; preserve rowids and skip unchanged text."""
        if not messages:
            return
        values = dict(messages)
        marks = ','.join('?' for _ in values)
        old = {row[0]: (row[1], row[2]) for row in conn.execute(
            f"SELECT k.message_id,k.fts_rowid,f.text FROM message_fts_keys k "
            f"LEFT JOIN messages_fts f ON f.rowid=k.fts_rowid WHERE k.message_id IN ({marks})", list(values))}
        # Allocate from a real B-tree, not the FTS virtual table: reading FTS
        # here flushes its pending insert segments at every batch boundary.
        next_id = conn.execute("SELECT coalesce(max(fts_rowid),0) FROM message_fts_keys").fetchone()[0]
        next_id = max(next_id, *(entry[0] for entry in old.values())) if old else next_id
        inserts, keys = [], []
        for message_id, text in values.items():
            previous = old.get(message_id)
            if previous and previous[1] == text:
                continue
            if previous:
                rowid = previous[0]
            else:
                next_id += 1
                rowid = next_id
                keys.append((message_id, rowid))
            inserts.append((rowid, message_id, text))
        conn.executemany("INSERT OR REPLACE INTO messages_fts(rowid,message_id,text) VALUES(?,?,?)", inserts)
        conn.executemany("INSERT INTO message_fts_keys VALUES(?,?)", keys)
