"""Non-destructive local backups and imports using SQLite's online backup API."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from .local_service import ServiceError, file_lock


def database_files(root):
    accounts = root / "accounts.db"
    if not accounts.is_file():
        raise ServiceError(f"找不到 accounts.db：{root}")
    with closing(sqlite3.connect(accounts.as_uri() + "?mode=ro", uri=True)) as source:
        ids = [row[0] for row in source.execute("SELECT id FROM accounts")]
    yield accounts
    for account in ids:
        if not isinstance(account, str) or account not in (UUID(account).hex, str(UUID(account))):
            raise ServiceError("旧版账号编号格式无效。")
        db = root / "users" / f"{account}.db"
        if db.is_file():
            yield db


def snapshot_database(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
          closing(sqlite3.connect(destination)) as backup):
        original.backup(backup)
        if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ServiceError("SQLite 数据校验失败，未完成复制。")


def snapshot_accounts(source, destination):
    for database in database_files(source):
        snapshot_database(database, destination / database.relative_to(source))


def find_accounts(path):
    path = path.resolve()
    for candidate in (
        path, path / "accounts", path / "data" / "accounts",
        path / "python-ai-agent-ai-agent-studypilot" / "outputs" / "StudyPilot" / "data" / "accounts",
    ):
        if (candidate / "accounts.db").is_file():
            return candidate
    raise ServiceError("找不到旧版账号数据库。请选择旧项目、data 或 accounts 文件夹。")


def backup_path(paths):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return paths.backups / f"{stamp}-{uuid4().hex[:8]}"


def backup_accounts(paths):
    destination = backup_path(paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        staged = Path(temp) / "accounts"
        snapshot_accounts(paths.accounts, staged)
        staged.rename(destination)
    return destination


def migrate_accounts(paths, source):
    target = paths.accounts
    source = find_accounts(source)
    if source == target or target in source.parents or source in target.parents:
        raise ServiceError("请选择与当前数据目录分开的旧版账号库或备份。")
    if target.exists():
        if any(item.name not in {"accounts.db", "accounts.db-wal", "accounts.db-shm", "users"}
               for item in target.iterdir()):
            raise ServiceError("目标已有文件，未覆盖。")
        if (target / "users").exists() and any((target / "users").iterdir()):
            raise ServiceError("当前已有学习记录，未覆盖。")
        database = target / "accounts.db"
        if database.exists():
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
                if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                    raise ServiceError("当前已有账号。为保留数据，不能合并或覆盖账号库。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as temp:
        staged = Path(temp) / "accounts"
        snapshot_accounts(source, staged)
        previous = target.with_name(f"{target.name}-before-import-{uuid4().hex[:8]}")
        if target.exists():
            target.rename(previous)
        try:
            staged.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
    return target


def import_legacy(paths, auth, username, source):
    source = source.resolve()
    if not source.is_file():
        raise ServiceError("找不到旧版 studypilot.db。")
    destination = backup_path(paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        staged = Path(temp) / "legacy"
        snapshot_database(source, staged / "studypilot.db")
        staged.rename(destination)
    return auth.import_legacy(username, destination / "studypilot.db", confirmed=True)


def data_lock(paths):
    return file_lock(paths.run / "data.lock", wait=5)
