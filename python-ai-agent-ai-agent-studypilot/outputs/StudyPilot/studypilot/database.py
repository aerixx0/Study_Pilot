"""SQLite 数据层：参数化 SQL、显式确认、事务和版本检查。"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import hashlib
import re
from pathlib import Path
import sqlite3

from .models import StudyProfile, TaskInput, ValidationError, clean_text, iso_date, minutes


class ConfirmationRequired(ValueError):
    pass


class ConflictError(ValueError):
    pass


def require_confirmation(confirmed):
    # 普通表单与独立提案确认入口必须显式传入 True；不是登录或安全权限系统。
    if confirmed is not True:
        raise ConfirmationRequired("请先勾选确认，再提交更改。")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self):
        """with 块成功时提交，出错时回滚，最终关闭连接，避免 Windows 文件锁。"""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def _write_connection(self, connection=None):
        """提案执行复用同一事务，使业务变更和执行凭据一起提交或回滚。"""
        if connection is not None:
            if not connection.in_transaction:
                raise ValidationError("修改必须在事务中执行。")
            yield connection
        else:
            with self.connection() as conn:
                yield conn

    def initialize(self):
        """首次运行创建空表；重复启动不会重置已有数据。"""
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValidationError("数据库版本较新，请使用匹配版本的 StudyPilot。")
            required = {"profile", "tasks", "study_sessions", "task_events", "schedule_plans", "sessions_date", "tasks_due", "agent_proposals", "request_receipts"}
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
            if version == 1 and required <= existing:
                return
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    payload TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL, subject TEXT NOT NULL, due_date TEXT NOT NULL,
                    estimated_minutes INTEGER NOT NULL CHECK(estimated_minutes > 0),
                    priority TEXT NOT NULL, status TEXT NOT NULL,
                    requires_computer INTEGER NOT NULL CHECK(requires_computer IN (0, 1)),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    completed_at TEXT, deleted_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS study_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES tasks(id),
                    subject TEXT NOT NULL,
                    study_date TEXT NOT NULL,
                    minutes INTEGER NOT NULL CHECK(minutes > 0),
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES tasks(id),
                    action TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_date ON study_sessions(study_date);
                CREATE INDEX IF NOT EXISTS tasks_due ON tasks(due_date);
                CREATE TABLE IF NOT EXISTS schedule_plans (
                    week_start TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    version INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_proposals (
                    id TEXT PRIMARY KEY, action TEXT NOT NULL,
                    payload TEXT NOT NULL, reason TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','applied','rejected')),
                    created_at REAL NOT NULL, expires_at REAL NOT NULL,
                    applied_at REAL, result TEXT,
                    request_id TEXT NOT NULL, call_id TEXT NOT NULL,
                    UNIQUE(request_id,call_id)
                );
                CREATE TABLE IF NOT EXISTS request_receipts (
                    request_id TEXT PRIMARY KEY, action TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL
                );
                PRAGMA user_version = 1;
            """)

    def get_study_profile(self):
        """新档案目标为空；旧数据无来源标记，读取时不按文字猜测或删除目标。"""
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if row is None:
            return StudyProfile(), 0
        try:
            profile = StudyProfile(**json.loads(row["payload"]))
            profile.validated()
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ValidationError("学习档案数据无法读取，请从备份恢复数据库。") from None
        return profile, row["version"]

    def save_profile(self, profile: StudyProfile, *, expected_version: int, confirmed=False, _connection=None):
        require_confirmation(confirmed)
        payload = json.dumps(profile.validated(), ensure_ascii=False)
        with self._write_connection(_connection) as conn:
            if expected_version == 0:
                try:
                    conn.execute("INSERT INTO profile VALUES (1, ?, 1, ?)", (payload, now_utc()))
                except sqlite3.IntegrityError:
                    raise ConflictError("档案已在其他页面保存，请刷新后重试。") from None
            else:
                result = conn.execute("UPDATE profile SET payload=?, version=version+1, updated_at=? WHERE id=1 AND version=?", (payload, now_utc(), expected_version))
                if result.rowcount != 1:
                    raise ConflictError("档案已发生变化，请刷新后重新确认。")

    def get_tasks(self, *, include_deleted=False):
        with self.connection() as conn:
            sql = "SELECT * FROM tasks" + ("" if include_deleted else " WHERE deleted_at IS NULL")
            return [dict(row) for row in conn.execute(sql + " ORDER BY due_date, id")]

    def get_task(self, task_id, *, include_deleted=False):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?" + ("" if include_deleted else " AND deleted_at IS NULL"), (task_id,)).fetchone()
        if row is None:
            raise ValidationError("任务不存在或已删除，请刷新页面。")
        return dict(row)

    @staticmethod
    def _event(conn, task_id, action):
        snapshot = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        conn.execute("INSERT INTO task_events(task_id, action, snapshot, created_at) VALUES (?, ?, ?, ?)", (task_id, action, json.dumps(snapshot, ensure_ascii=False), now_utc()))

    def _idempotent_write(self, request_id, action, data, write):
        """Account-scoped receipt and business write commit or roll back together."""
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
            raise ValidationError("重试标识无效，请刷新后重新提交。")
        digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                          allow_nan=False).encode("utf-8")).hexdigest()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            receipt = conn.execute("SELECT * FROM request_receipts WHERE request_id=?", (request_id,)).fetchone()
            if receipt:
                if receipt["action"] != action or receipt["payload_hash"] != digest:
                    raise ConflictError("此重试标识已用于不同内容，请重新提交。")
                return json.loads(receipt["result"])
            result = write(conn)
            conn.execute("INSERT INTO request_receipts VALUES (?,?,?,?,?)",
                         (request_id, action, digest, json.dumps(result), now_utc()))
            return result

    def create_task(self, task: TaskInput, *, confirmed=False, request_id=None, _connection=None):
        require_confirmation(confirmed)
        data = task.validated()
        if request_id is not None:
            return self._idempotent_write(request_id, "create_task", data,
                lambda conn: self.create_task(task, confirmed=True, _connection=conn))
        timestamp = now_utc()
        with self._write_connection(_connection) as conn:
            result = conn.execute("""INSERT INTO tasks
                (title,subject,due_date,estimated_minutes,priority,status,requires_computer,notes,created_at,updated_at,completed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (*data.values(), timestamp, timestamp, timestamp if task.status == "已完成" else None))
            task_id = result.lastrowid
            self._event(conn, task_id, "创建")
        return task_id

    def update_task(self, task_id, task: TaskInput, *, expected_version: int, confirmed=False, _connection=None):
        require_confirmation(confirmed)
        data = task.validated()
        timestamp = now_utc()
        with self._write_connection(_connection) as conn:
            result = conn.execute("""UPDATE tasks SET title=?,subject=?,due_date=?,estimated_minutes=?,priority=?,status=?,requires_computer=?,notes=?,
                updated_at=?, completed_at=CASE WHEN ? != '已完成' THEN NULL ELSE COALESCE(completed_at, ?) END,
                version=version+1 WHERE id=? AND version=? AND deleted_at IS NULL""", (*data.values(), timestamp, task.status, timestamp, task_id, expected_version))
            if result.rowcount != 1:
                raise ConflictError("任务已被修改或删除，请刷新后重新确认。")
            self._event(conn, task_id, "更新")

    def delete_task(self, task_id, *, expected_version: int, confirmed=False, _connection=None):
        """软删除任务，保留学习时长和变更历史，避免统计凭空减少。"""
        require_confirmation(confirmed)
        with self._write_connection(_connection) as conn:
            result = conn.execute("UPDATE tasks SET deleted_at=?,updated_at=?,version=version+1 WHERE id=? AND version=? AND deleted_at IS NULL", (now_utc(), now_utc(), task_id, expected_version))
            if result.rowcount != 1:
                raise ConflictError("任务已被修改或删除，请刷新后重新确认。")
            self._event(conn, task_id, "删除")

    def log_session(self, task_id, study_date, duration, note="", *, confirmed=False, request_id=None, _connection=None):
        """按实际发生的日期记录时长；不会自动完成任务，也不填造历史。"""
        require_confirmation(confirmed)
        iso_date(study_date, "学习日期")
        if date.fromisoformat(study_date) > date.today():
            raise ValidationError("实际学习日期不能在未来。")
        minutes(duration, "实际学习时长")
        note = clean_text(note, "学习记录备注", 1000, False)
        if request_id is not None:
            data = dict(task_id=task_id, study_date=study_date, duration=duration, note=note)
            return self._idempotent_write(request_id, "log_session", data,
                lambda conn: self.log_session(task_id, study_date, duration, note, confirmed=True, _connection=conn))
        with self._write_connection(_connection) as conn:
            row = conn.execute("SELECT subject FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,)).fetchone()
            if row is None:
                raise ValidationError("任务不存在或已删除，请刷新页面。")
            result = conn.execute("INSERT INTO study_sessions(task_id,subject,study_date,minutes,note,created_at) VALUES (?,?,?,?,?,?)", (task_id, row["subject"], study_date, duration, note, now_utc()))
        return result.lastrowid

    def delete_session(self, session_id, *, confirmed=False):
        require_confirmation(confirmed)
        with self.connection() as conn:
            if conn.execute("DELETE FROM study_sessions WHERE id=?", (session_id,)).rowcount != 1:
                raise ValidationError("学习记录不存在，请刷新页面。")

    def get_sessions(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("""SELECT s.*, t.title AS task_title, t.deleted_at FROM study_sessions s
                JOIN tasks t ON t.id=s.task_id ORDER BY s.study_date DESC, s.id DESC""")]

    def get_events(self, *, include_snapshot=True):
        with self.connection() as conn:
            columns = "*" if include_snapshot else "id,task_id,action,created_at"
            return [dict(row) for row in conn.execute(f"SELECT {columns} FROM task_events ORDER BY id DESC")]

    def _schedule_preview(self, conn, selected_day):
        from .scheduler import generate_schedule
        from .progress import week_bounds
        row = conn.execute("SELECT * FROM profile WHERE id=1").fetchone()
        if row is None:
            raise ValidationError("请先确认保存学习档案，再生成计划。")
        profile = StudyProfile(**json.loads(row["payload"]))
        tasks = [dict(row) for row in conn.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY id")]
        sessions = [dict(row) for row in conn.execute("SELECT * FROM study_sessions ORDER BY id")]
        week = week_bounds(selected_day)[0].isoformat()
        other_plans = [dict(row) for row in conn.execute(
            "SELECT * FROM schedule_plans WHERE week_start<>? ORDER BY week_start", (week,))]
        reservations = [entry for plan in other_plans for entry in json.loads(plan["payload"])["entries"]]
        result = generate_schedule(profile, tasks, sessions, selected_day, reservations=reservations)
        snapshot = dict(profile=dict(row), tasks=tasks, sessions=sessions, other_plans=other_plans)
        result["source_hash"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return result

    def preview_schedule(self, selected_day):
        """同一个只读事务中获取排课输入；预览不创建计划记录。"""
        with self.connection() as conn:
            conn.execute("BEGIN")
            return self._schedule_preview(conn, selected_day)

    def get_schedule(self, selected_day):
        from .progress import week_bounds
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM schedule_plans WHERE week_start=?", (week_bounds(selected_day)[0].isoformat(),)).fetchone()
        return (json.loads(row["payload"]), row["version"]) if row else (None, 0)

    def save_schedule(self, preview, *, expected_version, confirmed=False, _connection=None):
        """保存前重算并比对输入与内容，拒绝过期预览、篡改和并发覆盖。"""
        require_confirmation(confirmed)
        if not isinstance(preview, dict):
            raise ValidationError("计划预览无效，请重新生成。")
        selected = date.fromisoformat(iso_date(preview.get("week_start"), "计划周"))
        with self._write_connection(_connection) as conn:
            if _connection is None:
                conn.execute("BEGIN IMMEDIATE")
            current = self._schedule_preview(conn, selected)
            if preview.get("source_hash") != current["source_hash"] or preview.get("as_of") != current["as_of"]:
                raise ConflictError("档案、任务、学习记录或其他周计划已变化，请重新生成预览。")
            if preview != current:
                raise ValidationError("计划内容与规则计算结果不一致，请重新生成。")
            payload = json.dumps(current, ensure_ascii=False)
            if expected_version == 0:
                try:
                    conn.execute("INSERT INTO schedule_plans VALUES (?, ?, 1, ?)", (current["week_start"], payload, now_utc()))
                except sqlite3.IntegrityError:
                    raise ConflictError("本周计划已在其他页面保存，请重新生成。") from None
            else:
                changed = conn.execute("UPDATE schedule_plans SET payload=?,version=version+1,updated_at=? WHERE week_start=? AND version=?",
                                       (payload, now_utc(), current["week_start"], expected_version))
                if changed.rowcount != 1:
                    raise ConflictError("本周计划已被修改或删除，请重新生成。")

    def delete_schedule(self, selected_day, *, expected_version, confirmed=False):
        from .progress import week_bounds
        require_confirmation(confirmed)
        with self.connection() as conn:
            changed = conn.execute("DELETE FROM schedule_plans WHERE week_start=? AND version=?",
                                   (week_bounds(selected_day)[0].isoformat(), expected_version))
            if changed.rowcount != 1:
                raise ConflictError("本周计划已被修改或删除，请刷新。")

    def export_data(self):
        """本实例所属账号的学习数据；不会读取账号凭据或其他个人数据库。"""
        with self.connection() as conn:
            conn.execute("BEGIN")
            profile = conn.execute("SELECT payload FROM profile WHERE id=1").fetchone()
            result = {"study_profile": json.loads(profile["payload"]) if profile else None}
            for table in ("tasks", "study_sessions", "task_events", "schedule_plans", "agent_proposals"):
                result[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        return result
