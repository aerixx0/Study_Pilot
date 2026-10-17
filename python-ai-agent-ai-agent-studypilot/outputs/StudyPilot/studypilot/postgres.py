"""Vercel 的 PostgreSQL 存储，复用现有业务校验与事务。

账号表位于 sp_auth；学习表位于服务端 UUID 决定的独立 schema。
这里只转换项目使用的固定 SQL 方言，不接受 HTTP 或模型提交的 SQL。
"""
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import threading

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .auth import AuthStore, AuthError
from .database import Database, ConflictError
from .models import ValidationError


AUTH_DDL = """
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','developer')),
 created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 expires_at DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (
 bucket TEXT PRIMARY KEY, failures INTEGER NOT NULL,
 blocked_until DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS account_profiles (
 account_id TEXT PRIMARY KEY REFERENCES accounts(id), nickname TEXT NOT NULL,
 avatar TEXT NOT NULL, bio TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL
);
"""
STUDY_DDL = """
CREATE TABLE IF NOT EXISTS profile (
 id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
 id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL,
 due_date TEXT NOT NULL, estimated_minutes INTEGER NOT NULL CHECK(estimated_minutes>0),
 priority TEXT NOT NULL, status TEXT NOT NULL,
 requires_computer INTEGER NOT NULL CHECK(requires_computer IN (0,1)),
 notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 completed_at TEXT, deleted_at TEXT, version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS study_sessions (
 id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id),
 subject TEXT NOT NULL, study_date TEXT NOT NULL,
 minutes INTEGER NOT NULL CHECK(minutes>0), note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
 id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id),
 action TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_date ON study_sessions(study_date);
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(due_date);
CREATE TABLE IF NOT EXISTS schedule_plans (
 week_start TEXT PRIMARY KEY, payload TEXT NOT NULL,
 version INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_proposals (
 id TEXT PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL, reason TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','applied','rejected')),
 created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
 applied_at DOUBLE PRECISION, result TEXT, request_id TEXT NOT NULL, call_id TEXT NOT NULL,
 UNIQUE(request_id,call_id)
);
"""


class Record(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor=None, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid
        self.rowcount = cursor.rowcount if cursor else 0

    def fetchone(self):
        row = self.cursor.fetchone() if self.cursor else None
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(row) for row in self.cursor.fetchall()] if self.cursor else []

    def __iter__(self):
        return iter(self.fetchall())


def lock_key(schema):
    return int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)


class Connection:
    def __init__(self, raw, schema):
        self.raw, self.schema = raw, schema
        self.readonly = self.locked = False

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    def _lock(self):
        if not self.readonly and not self.locked:
            self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key(self.schema),))
            self.locked = True

    def execute(self, statement, parameters=()):
        normalized = " ".join(statement.strip().split())
        if normalized.upper() == "PRAGMA QUERY_ONLY=ON":
            if self.locked:
                raise sqlite3.OperationalError("只读模式必须在查询前设置。")
            self.raw.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.readonly = True
            return Cursor()
        if normalized.upper() == "BEGIN":
            return Cursor()
        if normalized.upper() == "BEGIN IMMEDIATE":
            self._lock()
            return Cursor()
        if not normalized.upper().startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
            raise sqlite3.OperationalError("云端存储不支持此操作。")
        self._lock()
        # 项目内固定语句的占位符；用户输入始终单独绑定，不进入 statement。
        converted = statement.replace("?", "%s")
        if normalized.upper().startswith("INSERT OR REPLACE INTO AUTH_ATTEMPTS "):
            converted = converted.replace("INSERT OR REPLACE", "INSERT", 1)
            converted += " ON CONFLICT (bucket) DO UPDATE SET failures=EXCLUDED.failures, blocked_until=EXCLUDED.blocked_until, updated_at=EXCLUDED.updated_at"
        generated = bool(re.match(r"INSERT INTO (tasks|study_sessions|task_events)\s*\(", normalized, re.I))
        if generated:
            converted += " RETURNING id"
        params = tuple(int(value) if type(value) is bool else value for value in parameters)
        try:
            cursor = self.raw.execute(converted, params)
            inserted = cursor.fetchone()["id"] if generated else None
            return Cursor(cursor, inserted)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError("数据约束冲突。") from None
        except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
            raise ConflictError("资料正在被其他操作更新，请刷新后重试。") from None
        except psycopg.Error:
            raise sqlite3.OperationalError("云端数据库操作失败，请稍后重试。") from None


class Postgres:
    def __init__(self, url=None):
        self.url = url or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
        if not self.url or not self.url.startswith(("postgres://", "postgresql://")):
            raise ValidationError("云端数据库未配置。请在 Vercel 设置 PostgreSQL DATABASE_URL 并重新部署。")
        self._ready = set()
        self._guard = threading.Lock()

    def connect(self):
        # 使用数据库提供方的池化连接 URL，连接使用后关闭，不依赖函数内存持久化。
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=8, prepare_threshold=None)

    def initialize(self, schema, ddl):
        if schema in self._ready:
            return
        with self._guard:
            if schema in self._ready:
                return
            try:
                with self.connect() as conn:
                    conn.execute("SET LOCAL statement_timeout='15s'")
                    conn.execute("SET LOCAL lock_timeout='10s'")
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key(schema),))
                    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
                    conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
                    version = conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
                    if version and version["version"] != 1:
                        raise ValidationError("云端数据版本较新，请使用匹配版本的程序。")
                    conn.execute(ddl)
                    conn.execute("INSERT INTO schema_meta VALUES (1,1) ON CONFLICT DO NOTHING")
            except psycopg.Error:
                raise sqlite3.OperationalError("无法连接或初始化云端数据库，请检查连接配置和数据库权限。") from None
            self._ready.add(schema)

    @contextmanager
    def connection(self, schema):
        try:
            with self.connect() as raw:
                raw.execute("SET LOCAL statement_timeout='15s'")
                raw.execute("SET LOCAL lock_timeout='10s'")
                raw.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                yield Connection(raw, schema)
        except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
            raise ConflictError("资料正在被其他操作更新，请刷新后重试。") from None
        except psycopg.Error:
            raise sqlite3.OperationalError("云端数据库暂时不可用，请稍后重试。") from None


class PostgresDatabase(Database):
    def __init__(self, source, account_id):
        if not isinstance(account_id, str) or not re.fullmatch("[0-9a-f]{32}", account_id):
            raise ValidationError("账号标识无效。")
        self.source, self.schema = source, "sp_u_" + account_id
        self.source.initialize(self.schema, STUDY_DDL)

    def connection(self):
        return self.source.connection(self.schema)


class PostgresAuthStore(AuthStore):
    def __init__(self, source=None):
        self.source = source or Postgres()
        self.source.initialize("sp_auth", AUTH_DDL)

    def connection(self):
        return self.source.connection("sp_auth")

    def study_database(self, token):
        if not isinstance(token, str) or len(token) > 128:
            raise AuthError("登录已失效，请重新登录。")
        with self.connection() as conn:
            account = self._active_account(conn, token)
        return PostgresDatabase(self.source, account.id)
