"""注册→恢复码→登录→退出，以及密码重置的页面级回归。"""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from studypilot.auth import AuthStore
from studypilot.models import StudyProfile
from tests.test_auth import PASSWORD, NEW_PASSWORD


ROOT = Path(__file__).resolve().parents[1]


class AuthUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth_root = Path(self.temp.name) / "accounts"
        environment = patch.dict(os.environ, {"STUDYPILOT_AUTH_DIR": str(self.auth_root),
            "STUDYPILOT_DB": str(Path(self.temp.name) / "legacy.db"), "STUDYPILOT_DEV_MODE": "1"})
        environment.start()
        self.addCleanup(environment.stop)
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.auth = AuthStore(self.auth_root)

    def click(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def login(self, username="student", password=PASSWORD):
        self.app.text_input(key="login_username").set_value(username)
        self.app.text_input(key="login_password").set_value(password)
        self.click("登录")

    def assert_preserved_form(self, form_id, values):
        form = next(form for form in self.app.get("form") if form.proto.form.form_id == form_id)
        # AppTest 不模拟浏览器的自动清空，须同时检查发送给浏览器的配置。
        self.assertFalse(form.proto.form.clear_on_submit)
        for key, value in values.items():
            widget = self.app.checkbox(key=key) if isinstance(value, bool) else self.app.text_input(key=key)
            self.assertEqual(widget.value, value)

    def test_registration_errors_preserve_fields_until_success(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.app.radio(key="auth_mode").set_value("注册账号").run()
        for username, password, repeat, confirmed, error in (
            ("", PASSWORD, PASSWORD, True, "用户名"),
            ("新同学", "short", "short", True, "密码须"),
            ("新同学", PASSWORD, "different", True, "不一致"),
            ("新同学", PASSWORD, PASSWORD, False, "确认"),
            ("student", PASSWORD, PASSWORD, True, "已被使用"),
        ):
            with self.subTest(error=error):
                values = dict(register_username=username, register_password=password,
                              register_repeat=repeat, register_confirm=confirmed)
                for key, value in values.items():
                    if isinstance(value, bool):
                        self.app.checkbox(key=key).set_value(value)
                    else:
                        self.app.text_input(key=key).set_value(value)
                self.click("创建账号")
                self.assertTrue(any(error in item.value for item in self.app.error))
                self.assert_preserved_form("registration_form", values)
        self.app.text_input(key="register_username").set_value("新同学")
        self.click("创建账号")
        self.assertEqual(self.app.session_state["recovery_receipt"]["username"], "新同学")
        for key in values:
            self.assertNotIn(key, self.app.session_state)

    def test_login_error_preserves_fields_until_success(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login(password="incorrect")
        self.assertTrue(self.app.error)
        self.assert_preserved_form("login_form", dict(login_username="student", login_password="incorrect"))
        self.app.text_input(key="login_password").set_value(PASSWORD)
        self.click("登录")
        self.assertEqual(self.app.radio(key="navigation").value, "学习概览")
        self.assertNotIn("login_password", self.app.session_state)

    def test_reset_errors_preserve_fields_until_success(self):
        _, code = self.auth.register("student", PASSWORD, confirmed=True)
        self.app.radio(key="auth_mode").set_value("找回密码").run()
        for recovery, password, repeat, confirmed in (
            (code, "short", "short", True),
            (code, NEW_PASSWORD, "different", True),
            ("wrong-code", NEW_PASSWORD, NEW_PASSWORD, True),
            (code, NEW_PASSWORD, NEW_PASSWORD, False),
        ):
            values = dict(reset_username="student", reset_code=recovery, reset_password=password,
                          reset_repeat=repeat, reset_confirm=confirmed)
            for key, value in values.items():
                if isinstance(value, bool):
                    self.app.checkbox(key=key).set_value(value)
                else:
                    self.app.text_input(key=key).set_value(value)
            self.click("重置密码")
            self.assertTrue(self.app.error)
            self.assert_preserved_form("reset_form", values)
        self.app.checkbox(key="reset_confirm").check()
        self.click("重置密码")
        self.assertTrue(self.app.session_state["recovery_receipt"]["code"])
        for key in values:
            self.assertNotIn(key, self.app.session_state)

    def test_password_change_errors_preserve_fields_until_success(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login()
        self.app.radio(key="navigation").set_value("账号设置").run()
        for current, password, repeat, confirmed in (
            (PASSWORD, "short", "short", True),
            (PASSWORD, NEW_PASSWORD, "different", True),
            ("wrong-password", NEW_PASSWORD, NEW_PASSWORD, True),
            (PASSWORD, NEW_PASSWORD, NEW_PASSWORD, False),
        ):
            values = dict(change_current=current, change_password=password,
                          change_repeat=repeat, change_confirm=confirmed)
            for key, value in values.items():
                if isinstance(value, bool):
                    self.app.checkbox(key=key).set_value(value)
                else:
                    self.app.text_input(key=key).set_value(value)
            self.click("更新密码")
            self.assertTrue(self.app.error)
            self.assert_preserved_form("change_password_form", values)
        self.app.checkbox(key="change_confirm").check()
        self.click("更新密码")
        self.assertTrue(self.app.session_state["recovery_receipt"]["code"])
        for key in values:
            self.assertNotIn(key, self.app.session_state)

    def test_anonymous_and_forged_session_cannot_render_learning_pages(self):
        self.assertEqual([r.label for r in self.app.radio], ["账号操作"])
        self.assertFalse((self.auth_root / "users").exists())
        self.app.session_state["auth_token"] = "not-a-real-session"
        self.app.session_state["role"] = "developer"
        self.app.session_state["navigation"] = "开发进度"
        self.app.run()
        self.assertEqual([r.label for r in self.app.radio], ["账号操作"])
        self.assertFalse(any("一步一步，成为 Agent" in m.value for m in self.app.markdown))

    def test_registration_confirmation_password_match_and_full_login_logout_flow(self):
        self.app.radio(key="auth_mode").set_value("注册账号").run()
        def fill(repeat=PASSWORD):
            self.app.text_input(key="register_username").set_value("Student")
            self.app.text_input(key="register_password").set_value(PASSWORD)
            self.app.text_input(key="register_repeat").set_value(repeat)
        fill("a mismatching long password")
        self.click("创建账号")
        self.assertTrue(any("不一致" in e.value for e in self.app.error))
        fill()
        self.click("创建账号")
        self.assertTrue(any("确认" in e.value for e in self.app.error))
        fill()
        self.app.checkbox(key="register_confirm").check()
        self.click("创建账号")
        self.assertTrue(self.app.session_state["recovery_receipt"]["code"])
        self.assertFalse((self.auth_root / "users").exists())
        self.click("我已妥善保存，去登录")
        self.login(password="incorrect")
        self.assertEqual([r.label for r in self.app.radio], ["账号操作"])
        self.login()
        self.assertIn("账号设置", self.app.radio(key="navigation").options)
        self.assertNotIn("开发进度", self.app.radio(key="navigation").options)
        token = self.app.session_state["auth_token"]
        self.assertEqual(self.auth.study_database(token).get_study_profile()[0].goals, "")
        self.assertNotIn("login_password", self.app.session_state)
        self.click("退出登录")
        self.assertIsNone(self.auth.authenticate(token))
        self.assertNotIn("auth_token", self.app.session_state)
        self.assertEqual([r.label for r in self.app.radio], ["账号操作"])

    def test_switch_account_clears_previous_user_profile_and_drafts(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.auth.register("second", PASSWORD, confirmed=True)
        self.login()
        token = self.app.session_state["auth_token"]
        self.auth.study_database(token).save_profile(StudyProfile(goals="第一个人的私有目标"), expected_version=0, confirmed=True)
        self.app.radio(key="navigation").set_value("学习档案").run()
        self.assertEqual(self.app.text_area(key="profile_goals_1").value, "第一个人的私有目标")
        self.app.text_area(key="profile_goals_1").set_value("第一个人的临时草稿")
        self.click("退出登录")
        self.login("second")
        self.app.radio(key="navigation").set_value("学习档案").run()
        self.assertEqual(self.app.text_area(key="profile_goals_0").value, "")
        self.assertNotIn("profile_goals_1", self.app.session_state)

    def test_long_chinese_username_registration_login_and_recovery(self):
        username = "学" * 40 + " Café-01！"
        alternate = "学" * 40 + " CAFE\u0301-01！"
        self.app.radio(key="auth_mode").set_value("注册账号").run()
        field = self.app.text_input(key="register_username")
        self.assertEqual(field.max_chars, 64)
        self.assertIn("中文", field.help)
        field.set_value(username)
        self.app.text_input(key="register_password").set_value(PASSWORD)
        self.app.text_input(key="register_repeat").set_value(PASSWORD)
        self.app.checkbox(key="register_confirm").check()
        self.click("创建账号")
        receipt = self.app.session_state["recovery_receipt"]
        self.assertEqual(receipt["username"], username.lower())
        code = receipt["code"]
        self.click("我已妥善保存，去登录")
        self.assertEqual(self.app.text_input(key="login_username").max_chars, 64)
        self.login(alternate)
        token = self.app.session_state["auth_token"]
        self.assertEqual(self.auth.authenticate(token).username, username.lower())
        self.click("退出登录")
        self.app.radio(key="auth_mode").set_value("找回密码").run()
        self.assertEqual(self.app.text_input(key="reset_username").max_chars, 64)
        self.app.text_input(key="reset_username").set_value(alternate)
        self.app.text_input(key="reset_code").set_value(code)
        self.app.text_input(key="reset_password").set_value(NEW_PASSWORD)
        self.app.text_input(key="reset_repeat").set_value(NEW_PASSWORD)
        self.app.checkbox(key="reset_confirm").check()
        self.click("重置密码")
        self.assertEqual(self.app.session_state["recovery_receipt"]["username"], username.lower())
        self.click("我已妥善保存，去登录")
        self.login(username, NEW_PASSWORD)
        self.assertEqual(self.app.radio(key="navigation").value, "学习概览")

    def test_recovery_reset_and_new_login(self):
        _, code = self.auth.register("student", PASSWORD, confirmed=True)
        token = self.auth.login("student", PASSWORD)
        self.app.radio(key="auth_mode").set_value("找回密码").run()
        self.app.text_input(key="reset_username").set_value("student")
        self.app.text_input(key="reset_code").set_value(code)
        self.app.text_input(key="reset_password").set_value(NEW_PASSWORD)
        self.app.text_input(key="reset_repeat").set_value(NEW_PASSWORD)
        self.app.checkbox(key="reset_confirm").check()
        self.click("重置密码")
        self.assertIsNone(self.auth.authenticate(token))
        self.assertNotEqual(self.app.session_state["recovery_receipt"]["code"], code)
        self.click("我已妥善保存，去登录")
        self.login(password=NEW_PASSWORD)
        self.assertEqual(self.app.radio(key="navigation").value, "学习概览")

    def test_password_change_signs_out_and_session_revocation_blocks_next_action(self):
        self.auth.register("student", PASSWORD, confirmed=True)
        self.login()
        token = self.app.session_state["auth_token"]
        self.app.radio(key="navigation").set_value("账号设置").run()
        self.app.text_input(key="change_current").set_value(PASSWORD)
        self.app.text_input(key="change_password").set_value(NEW_PASSWORD)
        self.app.text_input(key="change_repeat").set_value(NEW_PASSWORD)
        self.app.checkbox(key="change_confirm").check()
        self.click("更新密码")
        self.assertIsNone(self.auth.authenticate(token))
        self.assertNotIn("auth_token", self.app.session_state)
        self.click("我已妥善保存，去登录")
        self.login(password=NEW_PASSWORD)
        self.auth.logout(self.app.session_state["auth_token"])
        self.app.run()
        self.assertEqual([r.label for r in self.app.radio], ["账号操作"])
        self.assertNotIn("auth_token", self.app.session_state)


if __name__ == "__main__":
    unittest.main()
