"""个人资料、改登录名、会话撤销和导出的隔离及页面回归。"""

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import streamlit as st

from studypilot.auth import AuthStore, AuthError
from studypilot.database import ConfirmationRequired, ConflictError
from studypilot.models import TaskInput, ValidationError
from tests.test_auth import PASSWORD
from tests.test_auth_ui import AuthUITests


class AccountSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = AuthStore(Path(self.temp.name) / "accounts")
        self.account, self.recovery = self.auth.register("peteer", PASSWORD, confirmed=True)
        self.token = self.auth.login("peteer", PASSWORD)

    def test_personal_profile_confirmation_conflict_persistence_and_isolation(self):
        self.assertEqual(self.auth.get_personal_profile(self.token)["nickname"], "peteer")
        with self.assertRaises(ConfirmationRequired):
            self.auth.save_personal_profile(self.token, "新昵称", "🌱", "每天一步", expected_version=0)
        self.auth.save_personal_profile(self.token, "新昵称", "🌱", "每天一步", expected_version=0, confirmed=True)
        personal = AuthStore(self.auth.root).get_personal_profile(self.token)
        self.assertEqual(personal, dict(nickname="新昵称", avatar="🌱", bio="每天一步", version=1))
        self.assertEqual(self.auth.authenticate(self.token).username, "peteer")
        with self.assertRaises(ConflictError):
            self.auth.save_personal_profile(self.token, "旧页面", "🌱", "", expected_version=0, confirmed=True)
        self.auth.register("other", PASSWORD, confirmed=True)
        other = self.auth.login("other", PASSWORD)
        self.assertEqual(self.auth.get_personal_profile(other)["nickname"], "other")
        with self.assertRaises(AuthError):
            self.auth.get_personal_profile("forged")

    def test_invalid_profile_does_not_write(self):
        for nickname, avatar, bio in (("", "📚", ""), ("名" * 65, "📚", ""),
                                     ("名字", "bad", ""), ("名字", "📚", "x" * 121),
                                     ("名\u202e字", "📚", "")):
            with self.subTest(nickname=nickname), self.assertRaises(ValidationError):
                self.auth.save_personal_profile(self.token, nickname, avatar, bio, expected_version=0, confirmed=True)
        self.assertEqual(self.auth.get_personal_profile(self.token)["version"], 0)

    def test_username_change_requires_password_preserves_id_data_role_and_revokes_others(self):
        self.auth.set_role("peteer", "developer", confirmed=True)
        other_session = self.auth.login("peteer", PASSWORD)
        db = self.auth.study_database(self.token)
        db.create_task(TaskInput("保留任务", "数学", date.today().isoformat()), confirmed=True)
        with self.assertRaises(ConfirmationRequired):
            self.auth.change_username(self.token, "新的登录名", PASSWORD, expected_username="peteer")
        with self.assertRaises(AuthError):
            self.auth.change_username(self.token, "新的登录名", "wrong", expected_username="peteer", confirmed=True)
        self.auth.change_username(self.token, "新的登录名", PASSWORD, expected_username="peteer", confirmed=True)
        renamed = self.auth.authenticate(self.token)
        self.assertEqual((renamed.id, renamed.username, renamed.role), (self.account.id, "新的登录名", "developer"))
        self.assertIsNone(self.auth.authenticate(other_session))
        self.assertEqual(self.auth.study_database(self.token).path, db.path)
        self.assertEqual(self.auth.study_database(self.token).get_tasks()[0]["title"], "保留任务")
        with self.assertRaises(AuthError):
            self.auth.login("peteer", PASSWORD)
        self.assertEqual(self.auth.authenticate(self.auth.login("新的登录名", PASSWORD)).id, self.account.id)
        # 原恢复码在新的用户名下仍可使用。
        self.auth.reset_password("新的登录名", self.recovery, PASSWORD, confirmed=True)

    def test_username_duplicate_stale_or_revoked_during_verification_is_not_changed(self):
        self.auth.register("other", PASSWORD, confirmed=True)
        with self.assertRaises(ValidationError):
            self.auth.change_username(self.token, "OTHER", PASSWORD, expected_username="peteer", confirmed=True)
        with self.assertRaises(ConflictError):
            self.auth.change_username(self.token, "new", PASSWORD, expected_username="stale", confirmed=True)
        original = self.auth.login
        def revoke_during_verification(username, password):
            checked = original(username, password)
            self.auth.logout(self.token)
            return checked
        with patch.object(self.auth, "login", side_effect=revoke_during_verification):
            with self.assertRaises(AuthError):
                self.auth.change_username(self.token, "new", PASSWORD, expected_username="peteer", confirmed=True)
        self.assertEqual(self.auth.authenticate(original("peteer", PASSWORD)).id, self.account.id)

    def test_session_management_only_revokes_own_other_sessions(self):
        other_session = self.auth.login("peteer", PASSWORD)
        self.auth.register("other", PASSWORD, confirmed=True)
        foreign_session = self.auth.login("other", PASSWORD)
        sessions = self.auth.get_sessions(self.token)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(session["current"] for session in sessions), 1)
        self.assertNotIn(self.token, json.dumps(sessions))
        with self.assertRaises(ConfirmationRequired):
            self.auth.revoke_other_sessions(self.token)
        self.assertEqual(self.auth.revoke_other_sessions(self.token, confirmed=True), 1)
        self.assertIsNone(self.auth.authenticate(other_session))
        self.assertIsNotNone(self.auth.authenticate(self.token))
        self.assertIsNotNone(self.auth.authenticate(foreign_session))

    def test_export_contains_only_own_data_and_no_credentials(self):
        db = self.auth.study_database(self.token)
        db.create_task(TaskInput("我的任务", "英语", date.today().isoformat()), confirmed=True)
        self.auth.register("other", PASSWORD, confirmed=True)
        foreign = self.auth.login("other", PASSWORD)
        self.auth.study_database(foreign).create_task(TaskInput("其他人的任务", "数学", date.today().isoformat()), confirmed=True)
        exported = self.auth.export_account(self.token)
        text = json.dumps(exported, ensure_ascii=False)
        self.assertIn("我的任务", text)
        for secret in ("其他人的任务", PASSWORD, self.recovery, self.token, "password_hash", "token_hash", "recovery_hash"):
            self.assertNotIn(secret, text)
        self.assertIn("schedule_plans", exported["learning"])

    def test_additive_profile_schema_preserves_legacy_accounts(self):
        with self.auth.connection() as conn:
            conn.execute("DROP TABLE account_profiles")
        reopened = AuthStore(self.auth.root)
        self.assertEqual(reopened.authenticate(self.token).id, self.account.id)
        self.assertEqual(reopened.get_personal_profile(self.token)["version"], 0)


class AccountSettingsUITests(unittest.TestCase):
    setUp = AuthUITests.setUp
    click = AuthUITests.click
    login = AuthUITests.login

    def test_export_is_deferred_fresh_and_revalidates_at_download(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login()
        with patch("studypilot.auth_ui.st.download_button", wraps=st.download_button) as downloads:
            with patch.object(AuthStore, "export_account", side_effect=AssertionError("页面绘制不应提前导出")):
                self.app.radio(key="navigation").set_value("账号设置").run()
                self.assertEqual(len(self.app.exception), 0)
            call = next(call for call in downloads.call_args_list if call.args[0] == "导出我的数据（JSON）")
            generate = call.args[1]
        self.assertTrue(callable(generate))
        token = self.app.session_state["auth_token"]
        self.auth.study_database(token).create_task(TaskInput("下载前新增任务", "数学", date.today().isoformat()), confirmed=True)
        self.assertIn("下载前新增任务", generate().decode("utf-8"))
        self.auth.logout(token)
        with self.assertRaises(AuthError):
            generate()

    def test_edit_nickname_avatar_signature_preserves_username_and_shows_in_header(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login()
        self.app.radio(key="navigation").set_value("账号设置").run()
        self.app.text_input(key="personal_0_nickname").set_value("小树同学")
        self.app.selectbox(key="personal_0_avatar").set_value("🌱")
        self.app.text_input(key="personal_0_bio").set_value("每天进步一点")
        self.click("保存个人资料")
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.text_input(key="personal_0_nickname").value, "小树同学")
        self.app.checkbox(key="personal_0_confirm").check()
        self.click("保存个人资料")
        token = self.app.session_state["auth_token"]
        self.assertEqual(self.auth.get_personal_profile(token)["nickname"], "小树同学")
        self.assertEqual(self.auth.authenticate(token).username, "student")
        self.assertTrue(any("小树同学" in item.value for item in self.app.caption))
        self.assertEqual(self.app.text_input(key="personal_1_bio").value, "每天进步一点")

    def test_revoke_other_sessions_preserves_current_session(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login()
        token = self.app.session_state["auth_token"]
        next_session = self.auth.login("student", PASSWORD)
        self.app.radio(key="navigation").set_value("账号设置").run()
        self.click("退出其他会话")
        self.assertTrue(self.app.error)
        self.assertIsNotNone(self.auth.authenticate(next_session))
        self.app.checkbox(key="revoke_sessions_confirm").check()
        self.click("退出其他会话")
        self.assertIsNone(self.auth.authenticate(next_session))
        self.assertIsNotNone(self.auth.authenticate(token))


del AuthUITests


if __name__ == "__main__":
    unittest.main()
