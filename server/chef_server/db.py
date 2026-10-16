"""SQLite-хранилище приложения: аккаунты, сессии, личные чаты, журнал и диагностика.

Выбор SQLite: один файл без отдельного сервера БД — проект запускается одной командой на
ноутбуке каждого участника. Внешние ключи с ON DELETE CASCADE дают атомарное удаление чата
вместе с подбором, разговорами и сообщениями (CHAT-02).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2

# Колонки, добавленные после первой версии схемы: (таблица, колонка, тип)
ADDED_COLUMNS = [
    ("selections", "base_key", "TEXT"), ("selections", "catalog_revision", "INTEGER"),
    ("selections", "candidates", "BLOB"), ("events", "recipe_id", "INTEGER"),
    ("events", "count", "INTEGER"), ("events", "corpus_version", "TEXT"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT PRIMARY KEY,             -- SHA-256 токена; сам токен хранится только в cookie
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS chats (
    chat_id                TEXT PRIMARY KEY,
    user_id                TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title                  TEXT NOT NULL,
    products_text          TEXT NOT NULL,
    active_conversation_id TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_user ON chats(user_id, updated_at);

CREATE TABLE IF NOT EXISTS selections (
    selection_id   TEXT PRIMARY KEY,
    chat_id        TEXT NOT NULL UNIQUE REFERENCES chats(chat_id) ON DELETE CASCADE,
    corpus_version TEXT,
    filters_json   TEXT NOT NULL,
    items_json     TEXT NOT NULL,              -- показанные карточки (снимок для истории)
    total          INTEGER NOT NULL,
    base_key       TEXT,                       -- база каталога (версия и файл корпуса)
    catalog_revision INTEGER,                  -- ревизия каталога на момент подбора
    candidates     BLOB,                       -- ранжированные ID всех кандидатов (zlib)
    request_id     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    chat_id         TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    recipe_id       INTEGER NOT NULL,
    corpus_version  TEXT,
    recipe_json     TEXT NOT NULL,             -- снимок выбранного рецепта: состав, шаги, параметры
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_chat ON conversations(chat_id);

CREATE TABLE IF NOT EXISTS messages (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT NOT NULL,
    chat_id         TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text            TEXT NOT NULL,
    recipe_id       INTEGER,
    sources_json    TEXT,
    status          TEXT,                      -- answered | insufficient_context для ответов LLM
    reply_to        TEXT,                      -- message_id вопроса, на который это ответ
    created_at      TEXT NOT NULL,
    UNIQUE (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, seq);

-- Журнал активности: без паролей, токенов, текста продуктов, вопросов и ответов.
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at    TEXT NOT NULL,
    user_id        TEXT,
    event_type     TEXT NOT NULL,
    status         TEXT NOT NULL,
    duration_ms    INTEGER,
    request_id     TEXT NOT NULL,
    target_user_id TEXT,
    assigned_role  TEXT,
    recipe_id      INTEGER,                    -- для rag_update/rag_delete/rag_add
    count          INTEGER,                    -- число записей каталога в операции
    corpus_version TEXT                        -- версия каталога после операции
);
CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at);

CREATE TABLE IF NOT EXISTS diagnostics (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS diagnostics_time ON diagnostics(created_at);

-- Изменения каталога администратором (история версий записей; базовый корпус не меняется)
CREATE TABLE IF NOT EXISTS rag_changes (
    base_key    TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    recipe_id   INTEGER NOT NULL,
    op          TEXT NOT NULL CHECK (op IN ('upsert', 'delete')),
    record_json TEXT,
    user_id     TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (base_key, revision, recipe_id)
);
CREATE TABLE IF NOT EXISTS rag_state (
    base_key TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    next_id  INTEGER NOT NULL                  -- ID не переиспользуются после удаления
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    """Время UTC в ISO 8601 с миллисекундами и суффиксом Z."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, column, kind in ADDED_COLUMNS:  # миграция БД первой версии
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))
    finally:
        conn.close()


class Tx:
    """Транзакция BEGIN IMMEDIATE: проверка владельца и запись выполняются атомарно,
    поэтому запоздалый ответ не может восстановить удалённый чат."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("COMMIT" if exc_type is None else "ROLLBACK")
        return False
