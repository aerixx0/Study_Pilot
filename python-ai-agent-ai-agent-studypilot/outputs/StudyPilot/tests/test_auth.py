"""使用临时目录验证真实密码哈希、会话撤销、角色与学习数据隔离。"""

from datetime import date
from contextlib import closing
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from studypilot.auth import AuthStore, AuthError, IDLE_SECONDS, SESSION_SECONDS, verify_password
from studypilot.database import Database, ConfirmationRequired
from studypilot.models import StudyProfile, TaskInput, ValidationError


PASSWORD = "My private learning phrase 2026"
NEW_PASSWORD = "A different long study phrase 2027"


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.auth = AuthStore(self.root / "accounts")
        self.account, self.recovery = self.auth.register("Student_1", PASSWORD, confirmed=True)

    def test_opening_study_database_revalidates_without_duplicate_activity_write(self):
        token = self.auth.login("Student_1", PASSWORD)
        with self.auth.connection() as watcher:
            before = watcher.execute("PRAGMA data_version").fetchone()[0]
            AuthStore(self.auth.root)
            self.assertEqual(watcher.execute("PRAGMA data_version").fetchone()[0], before)
            last_seen = watcher.execute("SELECT last_seen FROM auth_sessions").fetchone()[0]
        with patch("studypilot.auth.time.time", return_value=last_seen + 10):
            self.assertEqual(self.auth.study_database(token).get_tasks(), [])
        with self.auth.connection() as conn:
            self.assertEqual(conn.execute("SELECT last_seen FROM auth_sessions").fetchone()[0], last_seen)
        self.auth.logout(token)
        for invalid in (token, None, "x" * 129):
            with self.subTest(invalid_type=type(invalid).__name__), self.assertRaises(AuthError):
                self.auth.study_database(invalid)

    def test_registration_confirmation_validation_duplicate_and_default_role(self):
        with self.assertRaises(ConfirmationRequired):
            self.auth.register("another", PASSWORD)
        for username, password in (("", PASSWORD), ("   ", PASSWORD), ("中" * 65, PASSWORD),
                                   (None, PASSWORD), ("学\n生", PASSWORD), ("学\t生", PASSWORD),
                                   ("\x00学生", PASSWORD), ("学生\u200b", PASSWORD),
                                   ("\u202e学生", PASSWORD), ("学生\u2028", PASSWORD),
                                   ("\ud800", PASSWORD), ("valid", "short"),
                                   ("valid", "x"*15), ("valid", "x"*129)):
            with self.subTest(username=username), self.assertRaises(ValidationError):
                self.auth.register(username, password, confirmed=True)
        with self.assertRaises(ValidationError):
            self.auth.register("STUDENT_1", PASSWORD, confirmed=True)
        self.assertEqual(self.account.role, "user")
        self.assertEqual(self.account.username, "student_1")
        self.assertFalse((self.auth.root / "users").exists())

    def test_flexible_usernames_persist_login_and_use_uuid_database_paths(self):
        for username in ("学", "ab", "小明 同学-01！", "学习📚", "中" * 64,
                         "../user", "'; DROP TABLE accounts;--"):
            with self.subTest(username=username):
                account, _ = self.auth.register(username, PASSWORD, confirmed=True)
                restarted = AuthStore(self.auth.root)
                token = restarted.login(username, PASSWORD)
                self.assertEqual(restarted.authenticate(token), account)
                self.assertEqual(restarted.study_database(token).path,
                                 self.auth.root / "users" / f"{account.id}.db")

    def test_unicode_equivalence_duplicate_recovery_and_role_management(self):
        account, recovery = self.auth.register("  小明 Café-01  ", PASSWORD, confirmed=True)
        self.assertEqual(account.username, "小明 café-01")
        alternate = "小明 CAFE\u0301-01"
        with self.assertRaises(ValidationError):
            self.auth.register(alternate, PASSWORD, confirmed=True)
        token = self.auth.login(alternate, PASSWORD)
        self.assertEqual(self.auth.authenticate(token).id, account.id)
        self.auth.set_role(alternate, "developer", confirmed=True)
        self.assertEqual(self.auth.authenticate(token).role, "developer")
        self.auth.reset_password(alternate, recovery, NEW_PASSWORD, confirmed=True)
        self.assertIsNone(self.auth.authenticate(token))
        self.assertEqual(self.auth.authenticate(self.auth.login(account.username, NEW_PASSWORD)).id, account.id)

    def test_hashes_are_salted_and_no_plaintext_credentials_are_stored(self):
        self.auth.register("another", PASSWORD, confirmed=True)
        with self.auth.connection() as conn:
            rows = conn.execute("SELECT password_hash,recovery_hash FROM accounts").fetchall()
        self.assertNotEqual(rows[0]["password_hash"], rows[1]["password_hash"])
        self.assertTrue(verify_password(PASSWORD, rows[0]["password_hash"]))
        self.assertFalse(verify_password("wrong", rows[0]["password_hash"]))
        raw = self.auth.path.read_bytes()
        self.assertNotIn(PASSWORD.encode(), raw)
        self.assertNotIn(self.recovery.encode(), raw)

    def test_session_restart_logout_and_invalid_tokens(self):
        token = self.auth.login("STUDENT_1", PASSWORD)
        self.assertEqual(AuthStore(self.auth.root).authenticate(token).id, self.account.id)
        self.assertNotIn(token.encode(), self.auth.path.read_bytes())
        for invalid in (None, "", "forged-token", 123, "x" * 129):
            self.assertIsNone(self.auth.authenticate(invalid))
            with self.assertRaises(AuthError):
                self.auth.study_database(invalid)
        self.auth.logout(token)
        self.assertIsNone(self.auth.authenticate(token))

    def test_idle_and_absolute_session_expiry(self):
        now = time.time()
        with patch("studypilot.auth.time.time", return_value=now):
            token = self.auth.login("student_1", PASSWORD)
        with patch("studypilot.auth.time.time", return_value=now + IDLE_SECONDS + 1):
            self.assertIsNone(self.auth.authenticate(token))
        with self.auth.connection() as conn:
            conn.execute("UPDATE auth_sessions SET last_seen=?", (now + SESSION_SECONDS,))
        with patch("studypilot.auth.time.time", return_value=now + SESSION_SECONDS + 1):
            self.assertIsNone(self.auth.authenticate(token))

    def test_failed_attempt_limit_persists_and_has_generic_errors(self):
        now = time.time()
        with patch("studypilot.auth.time.time", return_value=now):
            messages = []
            for username in ["missing_user", "student_1"]:
                with self.assertRaises(AuthError) as error:
                    self.auth.login(username, "wrong")
                messages.append(str(error.exception))
            self.assertEqual(messages[0], messages[1])
            for _ in range(4):
                with self.assertRaises(AuthError):
                    self.auth.login("student_1", "wrong")
            with self.assertRaises(AuthError):
                AuthStore(self.auth.root).login("student_1", PASSWORD)
        with patch("studypilot.auth.time.time", return_value=now + 61):
            self.assertIsNotNone(self.auth.authenticate(self.auth.login("student_1", PASSWORD)))

    def test_recovery_is_one_time_and_revokes_all_sessions(self):
        first = self.auth.login("student_1", PASSWORD)
        second = self.auth.login("student_1", PASSWORD)
        with self.assertRaises(ConfirmationRequired):
            self.auth.reset_password("student_1", self.recovery, NEW_PASSWORD)
        with self.assertRaises(AuthError):
            self.auth.reset_password("student_1", "wrong-code", NEW_PASSWORD, confirmed=True)
        next_code = self.auth.reset_password("student_1", self.recovery, NEW_PASSWORD, confirmed=True)
        self.assertNotEqual(next_code, self.recovery)
        self.assertIsNone(self.auth.authenticate(first))
        self.assertIsNone(self.auth.authenticate(second))
        with self.assertRaises(AuthError):
            self.auth.login("student_1", PASSWORD)
        self.assertIsNotNone(self.auth.authenticate(self.auth.login("student_1", NEW_PASSWORD)))
        with self.assertRaises(AuthError):
            self.auth.reset_password("student_1", self.recovery, PASSWORD, confirmed=True)

    def test_change_password_requires_current_password_and_rotates_recovery(self):
        token = self.auth.login("student_1", PASSWORD)
        with self.assertRaises(ConfirmationRequired):
            self.auth.change_password(token, PASSWORD, NEW_PASSWORD)
        with self.assertRaises(AuthError):
            self.auth.change_password(token, "incorrect", NEW_PASSWORD, confirmed=True)
        self.assertIsNotNone(self.auth.authenticate(token))
        next_code = self.auth.change_password(token, PASSWORD, NEW_PASSWORD, confirmed=True)
        self.assertIsNone(self.auth.authenticate(token))
        with self.assertRaises(AuthError):
            self.auth.reset_password("student_1", self.recovery, PASSWORD, confirmed=True)
        self.auth.reset_password("student_1", next_code, PASSWORD, confirmed=True)
        self.assertIsNotNone(self.auth.authenticate(self.auth.login("student_1", PASSWORD)))

    def test_role_is_read_from_database_and_registration_cannot_grant_it(self):
        token = self.auth.login("student_1", PASSWORD)
        with patch.dict("os.environ", {"STUDYPILOT_DEV_MODE": "1"}):
            self.assertEqual(self.auth.authenticate(token).role, "user")
        with self.assertRaises(ConfirmationRequired):
            self.auth.set_role("student_1", "developer")
        self.auth.set_role("student_1", "developer", confirmed=True)
        self.assertEqual(self.auth.authenticate(token).role, "developer")
        self.auth.set_role("student_1", "user", confirmed=True)
        self.assertEqual(self.auth.authenticate(token).role, "user")

    def test_password_change_race_does_not_leave_temporary_session(self):
        token = self.auth.login("student_1", PASSWORD)
        original_login = self.auth.login
        def revoke_during_verification(username, password):
            checked = original_login(username, password)
            self.auth.logout(token)
            return checked
        with patch.object(self.auth, "login", side_effect=revoke_during_verification):
            with self.assertRaises(AuthError):
                self.auth.change_password(token, PASSWORD, NEW_PASSWORD, confirmed=True)
        with self.auth.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0], 0)
        self.assertIsNotNone(self.auth.authenticate(self.auth.login("student_1", PASSWORD)))

    def test_local_management_command_grants_revokes_and_requires_import_confirmation(self):
        project = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, STUDYPILOT_AUTH_DIR=str(self.auth.root), STUDYPILOT_DB=str(self.root / "legacy.db"))
        token = self.auth.login("student_1", PASSWORD)
        for command, role in (("grant-developer", "developer"), ("revoke-developer", "user")):
            result = subprocess.run([sys.executable, str(project / "manage_users.py"), command, "student_1"],
                                    env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(self.auth.authenticate(token).role, role)
        result = subprocess.run([sys.executable, str(project / "manage_users.py"), "import-legacy", "student_1"],
                                env=environment, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 2)

    def test_profile_task_session_and_event_isolation(self):
        token_a = self.auth.login("student_1", PASSWORD)
        self.auth.register("student_2", PASSWORD, confirmed=True)
        token_b = self.auth.login("student_2", PASSWORD)
        a, b = self.auth.study_database(token_a), self.auth.study_database(token_b)
        a.save_profile(StudyProfile(goals="A 的目标"), expected_version=0, confirmed=True)
        first = a.create_task(TaskInput("A 的任务", "Python", date.today().isoformat()), confirmed=True)
        a.log_session(first, date.today().isoformat(), 37, confirmed=True)
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(b.get_study_profile()[0].goals, "")
        self.assertEqual(b.get_tasks(), [])
        self.assertEqual(b.get_sessions(), [])
        self.assertEqual(b.get_events(), [])
        with self.assertRaises(ValidationError):
            b.get_task(first)
        with self.assertRaises(ValidationError):
            b.log_session(first, date.today().isoformat(), 10, confirmed=True)
        b.save_profile(StudyProfile(goals="B 的目标"), expected_version=0, confirmed=True)
        self.assertEqual(a.get_study_profile()[0].goals, "A 的目标")
        self.assertEqual(a.get_sessions()[0]["minutes"], 37)

    def test_legacy_import_preserves_source_and_refuses_overwrite(self):
        source = self.root / "legacy.db"
        old = Database(source)
        old.save_profile(StudyProfile(goals="我的旧目标"), expected_version=0, confirmed=True)
        task = old.create_task(TaskInput("旧任务", "数学", date.today().isoformat()), confirmed=True)
        old.log_session(task, date.today().isoformat(), 42, confirmed=True)
        original = source.read_bytes()
        token = self.auth.login("student_1", PASSWORD)
        target = self.auth.study_database(token)  # 已创建但仍为空的账号也可导入。
        with self.assertRaises(ConfirmationRequired):
            self.auth.import_legacy("student_1", source)
        self.auth.import_legacy("student_1", source, confirmed=True)
        self.assertEqual(target.get_study_profile()[0].goals, "我的旧目标")
        self.assertEqual(target.get_sessions()[0]["minutes"], 42)
        self.assertEqual(target.get_events(), old.get_events())
        self.assertEqual(source.read_bytes(), original)
        with self.assertRaises(ValidationError):
            self.auth.import_legacy("student_1", source, confirmed=True)
        self.assertEqual(target.get_sessions()[0]["minutes"], 42)

    def test_invalid_import_rolls_back_entire_snapshot(self):
        source = self.root / "broken.db"
        old = Database(source)
        old.save_profile(StudyProfile(goals="不应部分导入"), expected_version=0, confirmed=True)
        with closing(sqlite3.connect(source)) as conn:
            with conn:
                conn.execute("INSERT INTO study_sessions(task_id,subject,study_date,minutes,note,created_at) VALUES(99,'数学','2026-01-01',5,'','test')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.auth.import_legacy("student_1", source, confirmed=True)
        target = self.auth.study_database(self.auth.login("student_1", PASSWORD))
        self.assertEqual(target.get_study_profile()[1], 0)
        self.assertEqual(target.get_sessions(), [])


if __name__ == "__main__":
    unittest.main()
