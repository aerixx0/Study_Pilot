"""本地账号服务：密码慢哈希、短期会话、恢复码及每账号独立数据库。"""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import time
import unicodedata
import uuid

from .database import Database, ConflictError, require_confirmation
from .models import ValidationError, clean_text


SESSION_SECONDS = 12 * 60 * 60
IDLE_SECONDS = 30 * 60
SCRYPT_N = 2 ** 17
USERNAME_MAX_LENGTH = 64
AVATARS = ("📚", "🌱", "🚀", "🐱", "🐼", "🎨", "⭐", "🌻")
LOGIN_ERROR = "用户名、密码或恢复码不正确，或尝试过于频繁，请稍后重试。"


class AuthError(ValueError):
    """可向用户展示的认证错误，不泄露账号是否存在。"""


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    role: str


def normalize_username(value):
    """统一 Unicode 组合形式和大小写；用户名不用于数据库文件路径。"""
    if not isinstance(value, str):
        raise ValidationError("请输入用户名。")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
        raise ValidationError("用户名不能包含换行、控制字符或不可见格式字符。")
    username = unicodedata.normalize("NFC", value.strip().lower())
    if not 1 <= len(username) <= USERNAME_MAX_LENGTH:
        raise ValidationError(f"用户名须为 1–{USERNAME_MAX_LENGTH} 个字符，可使用中文、字母、数字、空格和常用符号。")
    return username


def validate_password(password):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ValidationError("密码须为 15–128 个字符，可以使用较长的短语。")
    if not password.strip() or len(set(password)) == 1:
        raise ValidationError("请使用较难猜测的密码，避免空白或重复的单个字符。")


def password_hash(password, salt=None):
    """随机盐使相同密码得到不同摘要；scrypt 提高离线猜测成本。"""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=8, p=1, dklen=64, maxmem=256 * 1024 * 1024)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 128:
        return False
    try:
        algorithm, salt, _ = encoded.split("$")
        if algorithm != "scrypt":
            return False
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), encoded)
    except (ValueError, TypeError):
        return False


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "accounts.db"
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValidationError("账号数据库版本较新，请使用匹配版本的 StudyPilot。")
            required = {"accounts", "auth_sessions", "auth_attempts", "account_profiles", "ai_usage", "ai_site_usage"}
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # 已有完整结构只读检查；旧版缺表仍进入兼容建表路径。
            if version == 1 and required <= existing:
                return
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','developer')),
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    expires_at REAL NOT NULL, last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    bucket TEXT PRIMARY KEY, failures INTEGER NOT NULL,
                    blocked_until REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_profiles (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                    nickname TEXT NOT NULL, avatar TEXT NOT NULL,
                    bio TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL
                );
                -- 免费 AI 额度：账号窗口计数和全站当日计数，只有数字，不含对话内容。
                CREATE TABLE IF NOT EXISTS ai_usage (
                    account_id TEXT NOT NULL, window_start INTEGER NOT NULL,
                    used INTEGER NOT NULL, PRIMARY KEY (account_id, window_start)
                );
                CREATE TABLE IF NOT EXISTS ai_site_usage (
                    day TEXT PRIMARY KEY, used INTEGER NOT NULL
                );
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def register(self, username, password, *, confirmed=False):
        require_confirmation(confirmed)
        username = normalize_username(username)
        validate_password(password)
        recovery = secrets.token_urlsafe(32)
        encoded = password_hash(password)
        account = Account(uuid.uuid4().hex, username, "user")
        try:
            with self.connection() as conn:
                conn.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, 'user', ?)",
                             (account.id, username, encoded, fingerprint(recovery), time.time()))
        except sqlite3.IntegrityError:
            raise ValidationError("该用户名已被使用，请换一个用户名。") from None
        # 恢复码只返回一次；数据库只存摘要，不存明文密码或恢复码。
        return account, recovery

    @staticmethod
    def _allowed(conn, bucket, now):
        row = conn.execute("SELECT * FROM auth_attempts WHERE bucket=?", (bucket,)).fetchone()
        return row is None or row["blocked_until"] <= now

    @staticmethod
    def _failure(conn, bucket, now, limit=5):
        row = conn.execute("SELECT * FROM auth_attempts WHERE bucket=?", (bucket,)).fetchone()
        failures = row["failures"] + 1 if row and now - row["updated_at"] < 300 else 1
        blocked = now + 60 if failures >= limit else 0
        conn.execute("INSERT OR REPLACE INTO auth_attempts VALUES (?, ?, ?, ?)",
                     (bucket, failures, blocked, now))

    def _credentials(self, username, credential, *, recovery=False, new_password=None):
        """验证和失败计数放在同一事务；错误在提交计数后抛出，避免回滚限流。"""
        try:
            username = normalize_username(username)
        except ValidationError:
            raise AuthError(LOGIN_ERROR) from None
        now = time.time()
        bucket = ("recover:" if recovery else "login:") + fingerprint(username)
        outcome = None
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM auth_attempts WHERE updated_at < ?", (now - 86400,))
            if not self._allowed(conn, bucket, now) or not self._allowed(conn, "global", now):
                raise AuthError(LOGIN_ERROR)
            row = conn.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            if recovery:
                valid = isinstance(credential, str) and len(credential) <= 128 and hmac.compare_digest(
                    fingerprint(credential.strip()), row["recovery_hash"] if row else "0" * 64)
            elif row:
                valid = verify_password(credential, row["password_hash"])
            else:
                # 不存在的账号也做慢哈希，避免明显的时间差暴露用户名。
                password_hash((credential if isinstance(credential, str) else "")[:128])
                valid = False
            if valid and row:
                conn.execute("DELETE FROM auth_attempts WHERE bucket=?", (bucket,))
                if recovery:
                    next_code = secrets.token_urlsafe(32)
                    conn.execute("UPDATE accounts SET password_hash=?, recovery_hash=? WHERE id=?",
                                 (password_hash(new_password), fingerprint(next_code), row["id"]))
                    conn.execute("DELETE FROM auth_sessions WHERE account_id=?", (row["id"],))
                    outcome = next_code
                else:
                    token = secrets.token_urlsafe(32)
                    conn.execute("DELETE FROM auth_sessions WHERE expires_at<=? OR last_seen<=?", (now, now-IDLE_SECONDS))
                    conn.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?)",
                                 (fingerprint(token), row["id"], now + SESSION_SECONDS, now))
                    outcome = token
            else:
                self._failure(conn, bucket, now)
                self._failure(conn, "global", now, limit=50)
        if outcome is None:
            raise AuthError(LOGIN_ERROR)
        return outcome

    def login(self, username, password):
        return self._credentials(username, password)

    def reset_password(self, username, recovery_code, new_password, *, confirmed=False):
        require_confirmation(confirmed)
        validate_password(new_password)
        return self._credentials(username, recovery_code, recovery=True, new_password=new_password)

    def authenticate(self, token):
        """每次页面执行都重新验证会话和角色，不能相信浏览器自报的用户 ID。"""
        if not isinstance(token, str) or len(token) > 128:
            return None
        now = time.time()
        with self.connection() as conn:
            row = conn.execute("""SELECT a.id,a.username,a.role FROM auth_sessions s
                JOIN accounts a ON a.id=s.account_id
                WHERE s.token_hash=? AND s.expires_at>? AND s.last_seen>?""",
                (fingerprint(token), now, now-IDLE_SECONDS)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE auth_sessions SET last_seen=? WHERE token_hash=?", (now, fingerprint(token)))
            return Account(**dict(row))

    def logout(self, token):
        if isinstance(token, str):
            with self.connection() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (fingerprint(token),))

    @staticmethod
    def _active_account(conn, token):
        now = time.time()
        row = conn.execute("""SELECT a.id,a.username,a.role FROM auth_sessions s
            JOIN accounts a ON a.id=s.account_id
            WHERE s.token_hash=? AND s.expires_at>? AND s.last_seen>?""",
            (fingerprint(token) if isinstance(token, str) else "", now, now-IDLE_SECONDS)).fetchone()
        if row is None:
            raise AuthError("登录已失效，请重新登录。")
        return Account(**dict(row))

    def get_personal_profile(self, token):
        with self.connection() as conn:
            account = self._active_account(conn, token)
            row = conn.execute("SELECT nickname,avatar,bio,version FROM account_profiles WHERE account_id=?", (account.id,)).fetchone()
        return dict(row) if row else dict(nickname=account.username, avatar=AVATARS[0], bio="", version=0)

    def save_personal_profile(self, token, nickname, avatar, bio, *, expected_version, confirmed=False):
        require_confirmation(confirmed)
        nickname = clean_text(nickname, "昵称", 64)
        bio = clean_text(bio, "个性签名", 120, False)
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in nickname + bio):
            raise ValidationError("昵称和个性签名不能包含控制字符或不可见格式字符。")
        if avatar not in AVATARS:
            raise ValidationError("请选择提供的头像标识。")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            account = self._active_account(conn, token)
            if expected_version == 0:
                try:
                    conn.execute("INSERT INTO account_profiles VALUES (?, ?, ?, ?, 1)", (account.id, nickname, avatar, bio))
                except sqlite3.IntegrityError:
                    raise ConflictError("个人资料已在其他页面保存，请刷新。") from None
            else:
                changed = conn.execute("UPDATE account_profiles SET nickname=?,avatar=?,bio=?,version=version+1 WHERE account_id=? AND version=?",
                                       (nickname, avatar, bio, account.id, expected_version))
                if changed.rowcount != 1:
                    raise ConflictError("个人资料已发生变化，请刷新后重新确认。")

    def change_username(self, token, new_username, current_password, *, expected_username, confirmed=False):
        require_confirmation(confirmed)
        new_username = normalize_username(new_username)
        account = self.authenticate(token)
        if account is None:
            raise AuthError("登录已失效，请重新登录。")
        if account.username != expected_username:
            raise ConflictError("登录用户名已发生变化，请刷新。")
        checked_token = self.login(account.username, current_password)
        try:
            with self.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                active = self._active_account(conn, token)
                if active.id != account.id or active.username != expected_username:
                    raise ConflictError("账号状态已发生变化，请刷新。")
                try:
                    conn.execute("UPDATE accounts SET username=? WHERE id=?", (new_username, account.id))
                except sqlite3.IntegrityError:
                    raise ValidationError("该用户名已被使用，请换一个用户名。") from None
                conn.execute("DELETE FROM auth_sessions WHERE account_id=? AND token_hash<>?", (account.id, fingerprint(token)))
        finally:
            self.logout(checked_token)

    def get_sessions(self, token):
        with self.connection() as conn:
            account = self._active_account(conn, token)
            now = time.time()
            rows = conn.execute("SELECT token_hash,expires_at,last_seen FROM auth_sessions WHERE account_id=? AND expires_at>? AND last_seen>? ORDER BY last_seen DESC",
                                (account.id, now, now-IDLE_SECONDS)).fetchall()
        return [dict(session_id=fingerprint(row["token_hash"]),
                     current=hmac.compare_digest(row["token_hash"], fingerprint(token)),
                     created_at=row["expires_at"] - SESSION_SECONDS,
                     last_seen=row["last_seen"], expires_at=row["expires_at"]) for row in rows]

    def revoke_other_sessions(self, token, *, confirmed=False):
        require_confirmation(confirmed)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            account = self._active_account(conn, token)
            return conn.execute("DELETE FROM auth_sessions WHERE account_id=? AND token_hash<>?",
                                (account.id, fingerprint(token))).rowcount

    def export_account(self, token):
        account = self.authenticate(token)
        if account is None:
            raise AuthError("登录已失效，请重新登录。")
        return dict(format="StudyPilot personal export v1", exported_at=time.time(),
                    account=dict(username=account.username, role=account.role,
                                 profile=self.get_personal_profile(token)),
                    learning=self.study_database(token).export_data())

    def change_password(self, token, current_password, new_password, *, confirmed=False):
        require_confirmation(confirmed)
        validate_password(new_password)
        account = self.authenticate(token)
        if account is None:
            raise AuthError("登录已失效，请重新登录。")
        # 当前密码验证复用限流；该临时会话将在改密事务中一同失效。
        checked_token = self.login(account.username, current_password)
        next_code = secrets.token_urlsafe(32)
        try:
            with self.connection() as conn:
                # 再次检查原会话，防止验证期间另一个会话已经重置密码。
                conn.execute("BEGIN IMMEDIATE")
                now = time.time()
                active = conn.execute("SELECT 1 FROM auth_sessions WHERE token_hash=? AND expires_at>? AND last_seen>?",
                                      (fingerprint(token), now, now-IDLE_SECONDS)).fetchone()
                if active is None:
                    raise AuthError("登录已失效，请重新登录。")
                conn.execute("UPDATE accounts SET password_hash=?, recovery_hash=? WHERE id=?",
                             (password_hash(new_password), fingerprint(next_code), account.id))
                conn.execute("DELETE FROM auth_sessions WHERE account_id=?", (account.id,))
        finally:
            # 验证用的临时会话无论成功失败都撤销，不留下多余凭据。
            self.logout(checked_token)
        return next_code

    def ai_meter(self):
        """免费模型额度计数器；与账号同一份持久化存储。"""
        from .quota import AIMeter
        return AIMeter(self)

    def study_database(self, token):
        # 登录入口已刷新活动时间；打开学习库仍实时验证，但不重复写心跳。
        if not isinstance(token, str) or len(token) > 128:
            raise AuthError("登录已失效，请重新登录。")
        with self.connection() as conn:
            account = self._active_account(conn, token)
        # 文件名只来自服务生成的 UUID；用户不能指定他人的文件或任意路径。
        return Database(self.root / "users" / f"{account.id}.db")

    def set_role(self, username, role, *, confirmed=False):
        """仅供本机管理命令调用；注册和网页没有设置角色的参数。"""
        require_confirmation(confirmed)
        if role not in ("user", "developer"):
            raise ValidationError("角色无效。")
        with self.connection() as conn:
            if conn.execute("UPDATE accounts SET role=? WHERE username=?", (role, normalize_username(username))).rowcount != 1:
                raise ValidationError("账号不存在，请先注册。")

    def import_legacy(self, username, source, *, confirmed=False):
        """本机显式导入：只复制到空账号，保留原文件，并拒绝覆盖已有学习数据。"""
        require_confirmation(confirmed)
        source = Path(source).resolve()
        if not source.is_file():
            raise ValidationError("旧数据库不存在。")
        with self.connection() as conn:
            row = conn.execute("SELECT id FROM accounts WHERE username=?", (normalize_username(username),)).fetchone()
        if row is None:
            raise ValidationError("账号不存在，请先注册。")
        target = self.root / "users" / f"{row['id']}.db"
        if source == target.resolve():
            raise ValidationError("不能把数据库导入自身。")
        table_names = ("profile", "tasks", "study_sessions", "task_events")
        # sqlite3 的 with 只管理事务，不会关闭连接；显式 closing 避免 Windows 文件锁。
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            if src.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValidationError("旧数据库版本不受支持。")
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValidationError("旧数据库校验失败，未导入。")
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(table_names) <= tables:
                raise ValidationError("不是有效的旧学习数据库。")
            # 同一个只读事务取得一致快照；表名是代码内固定白名单。
            src.execute("BEGIN")
            snapshots = {}
            for table in table_names:
                cursor = src.execute(f"SELECT * FROM {table}")
                snapshots[table] = ([column[0] for column in cursor.description], cursor.fetchall())
            db = Database(target)
            with db.connection() as dst:
                # 检查为空和导入在同一写事务内，避免并发写入被覆盖。
                dst.execute("BEGIN IMMEDIATE")
                if any(dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in table_names):
                    raise ValidationError("该账号已有学习数据，拒绝覆盖。请使用一个空账号。")
                for table, (columns, rows) in snapshots.items():
                    expected = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
                    if columns != expected:
                        raise ValidationError("旧表结构不兼容，导入已回滚。")
                    placeholders = ','.join('?' for _ in columns)
                    dst.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        return target
