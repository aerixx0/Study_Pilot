"""Streamlit AppTest 实际提交表单，验证从 UI 到 SQLite 的完整路径。"""

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from studypilot.database import Database
from studypilot.auth import AuthStore
from studypilot.models import StudyProfile


ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        auth_root = Path(self.temp.name) / "accounts"
        env = patch.dict(os.environ, {"STUDYPILOT_DB": str(Path(self.temp.name) / "legacy.db"), "STUDYPILOT_AUTH_DIR": str(auth_root), "ZHIPU_API_KEY": "", "SILICONFLOW_API_KEY": "", "STUDYPILOT_DEV_MODE": ""})
        env.start()
        self.addCleanup(env.stop)
        self.auth = AuthStore(auth_root)
        self.auth.register("learner", "A private study password 2026", confirmed=True)
        self.token = self.auth.login("learner", "A private study password 2026")
        self.db_path = self.auth.study_database(self.token).path
        self.app = self.fresh_app()

    def fresh_app(self, *, run=True):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
        app.session_state["auth_token"] = self.token
        return app.run() if run else app

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def navigate(self, page):
        self.app.radio(key="navigation").set_value(page).run()
        self.assertEqual(len(self.app.exception), 0)

    def test_empty_app_and_all_pages_render(self):
        self.assertEqual(len(self.app.exception), 0)
        for page in ("学习档案", "学习任务", "学习记录", "账号设置", "学习概览"):
            self.navigate(page)
        self.assertEqual(Database(self.db_path).get_tasks(), [])
        self.assertTrue(any("AI 未启用" in message.value for message in self.app.info))

    def test_development_page_is_hidden_and_stale_navigation_is_rejected(self):
        self.assertNotIn("开发进度", self.app.radio(key="navigation").options)
        # 在首次绘制前注入旧会话值，避免测试框架先序列化一个不在选项中的值。
        self.app = self.fresh_app(run=False)
        self.app.session_state["navigation"] = "开发进度"
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.radio(key="navigation").value, "学习概览")
        self.assertFalse(any("功能与维护" in item.value for item in self.app.markdown))

    def test_developer_mode_enables_page_and_revocation_returns_to_overview(self):
        self.auth.set_role("learner", "developer", confirmed=True)
        self.app.run()
        self.assertIn("开发进度", self.app.radio(key="navigation").options)
        self.navigate("开发进度")
        self.assertTrue(any("功能与维护" in item.value for item in self.app.markdown))
        self.auth.set_role("learner", "user", confirmed=True)
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.radio(key="navigation").value, "学习概览")
        self.assertNotIn("开发进度", self.app.radio(key="navigation").options)
        self.assertFalse(any("功能与维护" in item.value for item in self.app.markdown))

    def test_development_mode_requires_explicit_server_configuration(self):
        for value in ("0", "1", "false", "true", "developer"):
            with self.subTest(value=value), patch.dict(os.environ, {"STUDYPILOT_DEV_MODE": value}):
                self.app.run()
                self.assertNotIn("开发进度", self.app.radio(key="navigation").options)

    def test_task_record_edit_and_delete_flow(self):
        db = Database(self.db_path)
        self.navigate("学习任务")
        self.app.text_input(key="new_title").set_value("周末 Python 练习")
        self.click("创建任务")
        self.assertTrue(any("确认" in error.value for error in self.app.error))
        self.assertEqual(db.get_tasks(), [])
        self.app.text_input(key="new_title").set_value("周末 Python 练习")
        self.app.checkbox(key="create_confirm").check()
        self.click("创建任务")
        task = db.get_tasks()[0]
        task_id = task["id"]
        self.app.selectbox(key=f"edit_{task_id}_1_status").set_value("已完成")
        self.click("保存任务修改")
        self.assertEqual(db.get_task(task_id)["status"], "待开始")
        self.app.selectbox(key=f"edit_{task_id}_1_status").set_value("已完成")
        self.app.checkbox(key=f"edit_{task_id}_1_confirm").check()
        self.click("保存任务修改")
        self.assertEqual(db.get_task(task_id)["status"], "已完成")
        self.assertEqual(db.get_sessions(), [])
        self.navigate("学习记录")
        self.app.number_input(key="record_minutes").set_value(37)
        self.click("保存学习记录")
        self.assertEqual(db.get_sessions(), [])
        self.app.number_input(key="record_minutes").set_value(37)
        self.app.checkbox(key="record_confirm").check()
        self.click("保存学习记录")
        self.assertEqual(db.get_sessions()[0]["minutes"], 37)
        self.navigate("学习概览")
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.get("vega_lite_chart")), 2)
        self.navigate("学习任务")
        self.click("删除任务")
        self.assertEqual(len(db.get_tasks()), 1)
        self.app.checkbox(key=f"edit_{task_id}_2_delete_confirm").check()
        self.click("删除任务")
        self.assertEqual(db.get_tasks(), [])
        self.assertEqual(len(db.get_sessions()), 1)
        self.navigate("学习记录")
        session_id = db.get_sessions()[0]["id"]
        self.click("删除学习记录")
        self.assertEqual(len(db.get_sessions()), 1)
        self.app.checkbox(key=f"session_delete_confirm_{session_id}").check()
        self.click("删除学习记录")
        self.assertEqual(db.get_sessions(), [])

    def test_task_and_record_failures_preserve_inputs_and_success_resets(self):
        db = Database(self.db_path)
        self.navigate("学习任务")
        form = next(form for form in self.app.get("form") if form.proto.form.form_id == "create_task")
        self.assertFalse(form.proto.form.clear_on_submit)
        self.app.text_input(key="new_title").set_value("   ")
        self.app.text_area(key="new_notes").set_value("保留这段备注")
        self.app.checkbox(key="create_confirm").check()
        self.click("创建任务")
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.text_area(key="new_notes").value, "保留这段备注")
        self.assertTrue(self.app.checkbox(key="create_confirm").value)
        self.assertEqual(db.get_tasks(), [])
        self.app.text_input(key="new_title").set_value("修正后的任务")
        self.click("创建任务")
        self.assertEqual(len(db.get_tasks()), 1)
        self.assertEqual(self.app.text_input(key="new_title").value, "")
        self.assertFalse(self.app.checkbox(key="create_confirm").value)
        self.navigate("学习记录")
        form = next(form for form in self.app.get("form") if form.proto.form.form_id == "record_session")
        self.assertFalse(form.proto.form.clear_on_submit)
        self.app.number_input(key="record_minutes").set_value(47)
        self.app.text_input(key="record_note").set_value("保留学习备注")
        self.click("保存学习记录")
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.number_input(key="record_minutes").value, 47)
        self.assertEqual(self.app.text_input(key="record_note").value, "保留学习备注")
        self.assertEqual(db.get_sessions(), [])
        self.app.checkbox(key="record_confirm").check()
        self.click("保存学习记录")
        self.assertEqual(len(db.get_sessions()), 1)
        self.assertEqual(db.get_sessions()[0]["minutes"], 47)
        self.assertEqual(self.app.text_input(key="record_note").value, "")
        self.assertFalse(self.app.checkbox(key="record_confirm").value)

    def test_profile_save_requires_confirmation_and_survives_new_app(self):
        self.navigate("学习档案")
        self.click("保存档案")
        self.assertEqual(Database(self.db_path).get_study_profile()[1], 0)
        next(box for box in self.app.checkbox if box.label == "我确认保存以上学习档案").check()
        self.click("保存档案")
        self.assertEqual(Database(self.db_path).get_study_profile()[1], 1)
        fresh = self.fresh_app()
        fresh.radio(key="navigation").set_value("学习档案").run()
        self.assertEqual(len(fresh.exception), 0)
        self.assertFalse(any("默认草稿" in item.value for item in fresh.info))

    def confirm_profile(self):
        next(box for box in self.app.checkbox if box.label == "我确认保存以上学习档案").check()
        self.click("保存档案")

    def test_goal_placeholder_is_not_real_data_and_empty_save_is_allowed(self):
        self.assertTrue(any("目标，等你来决定" in item.value for item in self.app.markdown))
        self.navigate("学习档案")
        goal_input = self.app.text_area(key="profile_goals_0")
        self.assertEqual(goal_input.value, "")
        self.assertIn("学习目标", goal_input.proto.placeholder)
        self.assertEqual(Database(self.db_path).get_study_profile()[1], 0)
        self.confirm_profile()
        profile, version = Database(self.db_path).get_study_profile()
        self.assertEqual(profile.goals, "")
        self.assertEqual(version, 1)
        self.navigate("学习概览")
        self.assertTrue(any("目标，等你来决定" in item.value for item in self.app.markdown))
        self.app.button(key="overview_to_goals").click().run()
        self.assertEqual(self.app.radio(key="navigation").value, "学习档案")
        self.assertEqual(self.app.text_area(key="profile_goals_1").value, "")

    def test_goals_create_edit_clear_and_reload_with_explicit_confirmation(self):
        db = Database(self.db_path)
        self.navigate("学习档案")
        self.app.text_area(key="profile_goals_0").set_value("提高阅读速度\n学会写 Python 函数")
        self.click("保存档案")
        self.assertEqual(db.get_study_profile()[1], 0)
        self.assertTrue(any("确认" in error.value for error in self.app.error))
        self.confirm_profile()
        self.assertEqual(db.get_study_profile()[0].goals, "提高阅读速度\n学会写 Python 函数")
        # 用全新会话模拟重新打开网站，验证展示的是 SQLite 中的目标。
        self.app = self.fresh_app()
        self.navigate("学习档案")
        self.assertEqual(self.app.text_area(key="profile_goals_1").value, "提高阅读速度\n学会写 Python 函数")
        self.app.text_area(key="profile_goals_1").set_value("每周读两篇文章")
        self.confirm_profile()
        self.assertEqual(db.get_study_profile()[0].goals, "每周读两篇文章")
        self.app.text_area(key="profile_goals_2").set_value("")
        self.click("保存档案")
        self.assertEqual(db.get_study_profile()[0].goals, "每周读两篇文章")
        self.confirm_profile()
        self.assertEqual(db.get_study_profile()[0].goals, "")
        fresh = self.fresh_app()
        fresh.radio(key="navigation").set_value("学习档案").run()
        self.assertEqual(fresh.text_area(key="profile_goals_3").value, "")
        self.assertEqual(len(fresh.exception), 0)

    def test_saved_legacy_goal_is_preserved_and_explained(self):
        legacy = "学习 Python 基础；强化数学和英语；逐步了解 AI Agent。"
        db = Database(self.db_path)
        db.save_profile(StudyProfile(goals=legacy), expected_version=0, confirmed=True)
        self.navigate("学习档案")
        self.assertEqual(self.app.text_area(key="profile_goals_1").value, legacy)
        self.assertTrue(any("目标由你决定" in item.value for item in self.app.caption))
        self.assertEqual(db.get_study_profile()[1], 1)
        self.assertEqual(db.get_study_profile()[0].goals, legacy)

    def test_ai_goal_entry_explains_assistant_without_writing_goals(self):
        db = Database(self.db_path)
        db.save_profile(StudyProfile(goals="我的自主目标"), expected_version=0, confirmed=True)
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only-secret-marker"}):
            self.navigate("学习档案")
            self.assertTrue(any(expander.label == "AI 帮我制定目标" for expander in self.app.expander))
            self.assertTrue(any("请切换到“AI 助手”" in item.value for item in self.app.info))
            self.app.text_area(key="profile_goals_1").set_value("尚未确认的修改")
            self.assertEqual(self.app.text_area(key="profile_goals_1").value, "尚未确认的修改")
            # 表单未提交的文字只在浏览器草稿中；刷新可以丢弃草稿，但不能写入数据库。
            self.app.run()
            self.assertEqual(db.get_study_profile()[0].goals, "我的自主目标")
            self.assertEqual(db.get_study_profile()[1], 1)
            self.assertFalse(any(button.label in ("采纳", "生成目标建议") for button in self.app.button))

    def test_invalid_title_is_rejected_with_chinese_message(self):
        self.navigate("学习任务")
        self.app.checkbox(key="create_confirm").check()
        self.click("创建任务")
        self.assertTrue(any("任务标题" in item.value for item in self.app.error))
        self.assertEqual(Database(self.db_path).get_tasks(), [])

    def test_homepage_shortcuts_navigate_without_writing_data(self):
        self.app.button(key="hero_create").click().run()
        self.assertEqual(self.app.radio(key="navigation").value, "学习任务")
        self.assertEqual(len(self.app.exception), 0)
        self.navigate("学习概览")
        self.app.button(key="hero_profile").click().run()
        self.assertEqual(self.app.radio(key="navigation").value, "学习档案")
        self.assertEqual(len(self.app.exception), 0)
        db = Database(self.db_path)
        self.assertEqual(db.get_tasks(), [])
        self.assertEqual(db.get_study_profile()[1], 0)

    def test_configured_key_is_never_displayed_or_called(self):
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only-secret-marker"}):
            self.app.run()
        self.assertTrue(any("AI 助手已开放" in item.value for item in self.app.info))
        visible_text = " ".join(item.value for collection in (self.app.info, self.app.markdown, self.app.caption) for item in collection)
        self.assertNotIn("test-only-secret-marker", visible_text)


if __name__ == "__main__":
    unittest.main()
