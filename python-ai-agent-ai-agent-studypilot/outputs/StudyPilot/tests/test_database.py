"""用临时数据库验证真实行为，不触碰用户 data/ 目录。"""

from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from studypilot.database import ConfirmationRequired, ConflictError, Database
from studypilot.models import StudyProfile, TaskInput, ValidationError
from studypilot.progress import get_progress, week_bounds


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "study.db"
        self.db = Database(self.path)
        self.task = TaskInput("写一个问候程序", "Python", date.today().isoformat(), 45)

    def create(self, task=None):
        return self.db.create_task(task or self.task, confirmed=True)

    def test_first_run_is_empty_and_restart_preserves_data(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(self.db.get_sessions(), [])
        self.assertEqual(self.db.get_study_profile()[1], 0)
        task_id = self.create()
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        restarted = Database(self.path)
        self.assertEqual(restarted.get_task(task_id)["title"], self.task.title)
        self.assertEqual(restarted.get_study_profile()[0].weekly_hours, 8)

    def test_reopening_is_read_only_and_missing_schema_is_still_added(self):
        task_id = self.create()
        with self.db.connection() as watcher:
            before = watcher.execute("PRAGMA data_version").fetchone()[0]
            Database(self.path)
            self.assertEqual(watcher.execute("PRAGMA data_version").fetchone()[0], before)
        with self.db.connection() as conn:
            conn.execute("DROP TABLE schedule_plans")
            conn.execute("DROP INDEX sessions_date")
        reopened = Database(self.path)
        self.assertEqual(reopened.get_task(task_id)["title"], self.task.title)
        self.assertEqual(reopened.get_schedule(date.today()), (None, 0))
        with reopened.connection() as conn:
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='sessions_date'").fetchone())
        full, summary = reopened.get_events(), reopened.get_events(include_snapshot=False)
        self.assertIn("snapshot", full[0])
        self.assertEqual(summary, [{key: value for key, value in event.items() if key != "snapshot"} for event in full])

    def test_all_writes_require_explicit_confirmation(self):
        task_id = self.create()
        session_id = self.db.log_session(task_id, date.today().isoformat(), 30, confirmed=True)
        actions = [
            lambda: self.db.create_task(self.task),
            lambda: self.db.save_profile(StudyProfile(), expected_version=0),
            lambda: self.db.update_task(task_id, self.task, expected_version=1),
            lambda: self.db.delete_task(task_id, expected_version=1),
            lambda: self.db.log_session(task_id, date.today().isoformat(), 30),
            lambda: self.db.delete_session(session_id),
            lambda: self.db.create_task(self.task, confirmed="yes"),
        ]
        for action in actions:
            with self.subTest(action=action), self.assertRaises(ConfirmationRequired):
                action()
        self.assertEqual(len(self.db.get_tasks()), 1)
        self.assertEqual(len(self.db.get_sessions()), 1)
        self.assertEqual(self.db.get_study_profile()[1], 0)

    def test_invalid_tasks_leave_no_partial_data(self):
        invalid = [replace(self.task, title=" "), replace(self.task, title="x" * 121), replace(self.task, subject="物理"),
                   replace(self.task, estimated_minutes=0), replace(self.task, estimated_minutes=True),
                   replace(self.task, due_date="2026-02-30"), replace(self.task, due_date="20261011"),
                   replace(self.task, status="未知"), replace(self.task, requires_computer="yes")]
        for task in invalid:
            with self.subTest(task=task), self.assertRaises(ValidationError):
                self.create(task)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(self.db.get_events(), [])

    def test_profile_validation_budget_and_devices(self):
        for profile in [StudyProfile(weekly_hours=0), StudyProfile(weekly_hours=float("nan")), StudyProfile(weekly_hours=20),
                        StudyProfile(levels={}), StudyProfile(max_session_minutes=0)]:
            with self.subTest(profile=profile), self.assertRaises(ValidationError):
                self.db.save_profile(profile, expected_version=0, confirmed=True)
        profile = StudyProfile()
        profile.availability["周五"]["devices"] = []
        with self.assertRaises(ValidationError):
            profile.validated()

    def test_profile_conflicts_do_not_overwrite(self):
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        with self.assertRaises(ConflictError):
            self.db.save_profile(StudyProfile(goals="覆盖"), expected_version=0, confirmed=True)
        self.db.save_profile(StudyProfile(goals="我的目标"), expected_version=1, confirmed=True)
        with self.assertRaises(ConflictError):
            self.db.save_profile(StudyProfile(goals="旧页面"), expected_version=1, confirmed=True)
        self.assertEqual(self.db.get_study_profile()[0].goals, "我的目标")

    def test_goals_start_empty_and_reading_does_not_create_profile(self):
        for db in (self.db, Database(self.path)):
            profile, version = db.get_study_profile()
            self.assertEqual(profile.goals, "")
            self.assertEqual(version, 0)
        with self.db.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM profile").fetchone()[0], 0)

    def test_goal_edit_and_clear_require_confirmation_and_preserve_other_data(self):
        original = StudyProfile(goals="每周读一篇英文文章\n学习 Python 列表", preference="先看例子再练习")
        self.db.save_profile(original, expected_version=0, confirmed=True)
        task_id = self.create()
        self.db.log_session(task_id, date.today().isoformat(), 37, confirmed=True)
        sessions, tasks, events = self.db.get_sessions(), self.db.get_tasks(), self.db.get_events()
        for next_goals in ("专注英语阅读", ""):
            profile, version = self.db.get_study_profile()
            updated = replace(profile, goals=next_goals)
            with self.assertRaises(ConfirmationRequired):
                self.db.save_profile(updated, expected_version=version)
            self.assertEqual(self.db.get_study_profile()[0].goals, profile.goals)
            self.db.save_profile(updated, expected_version=version, confirmed=True)
            saved, _ = Database(self.path).get_study_profile()
            self.assertEqual(saved.goals, next_goals)
            self.assertEqual(replace(saved, goals=original.goals).validated(), original.validated())
        self.assertEqual(self.db.get_sessions(), sessions)
        self.assertEqual(self.db.get_tasks(), tasks)
        self.assertEqual(self.db.get_events(), events)
        with self.assertRaises(ConflictError):
            self.db.save_profile(original, expected_version=1, confirmed=True)
        self.assertEqual(self.db.get_study_profile()[0].goals, "")

    def test_legacy_example_and_custom_goals_are_preserved_without_provenance(self):
        # 模拟旧版 JSON 数据，没有目标来源字段。完全相同的示例也不能猜测删除。
        legacy = "学习 Python 基础；强化数学和英语；逐步了解 AI Agent。"
        for goals in (legacy, legacy + "\n我想研究游戏开发", "我自己的方向"):
            with self.subTest(goals=goals):
                payload = json.dumps(StudyProfile(goals=goals).validated(), ensure_ascii=False)
                with self.db.connection() as conn:
                    conn.execute("INSERT OR REPLACE INTO profile VALUES (1, ?, 7, 'legacy-time')", (payload,))
                restored, version = Database(self.path).get_study_profile()
                self.assertEqual(restored.goals, goals)
                self.assertEqual(version, 7)
                with self.db.connection() as conn:
                    row = conn.execute("SELECT payload, updated_at FROM profile").fetchone()
                self.assertEqual(row["payload"], payload)
                self.assertEqual(row["updated_at"], "legacy-time")

    def test_empty_goals_are_valid_but_invalid_values_are_rejected(self):
        self.assertEqual(StudyProfile(goals="  \n ").validated()["goals"], "")
        for goals in (None, [], "x" * 2001):
            with self.subTest(goals=goals), self.assertRaises(ValidationError):
                self.db.save_profile(StudyProfile(goals=goals), expected_version=0, confirmed=True)
        self.assertEqual(self.db.get_study_profile()[1], 0)

    def test_separate_local_databases_do_not_share_goals(self):
        other = Database(Path(self.temp.name) / "other-user.db")
        self.db.save_profile(StudyProfile(goals="我的目标"), expected_version=0, confirmed=True)
        self.assertEqual(other.get_study_profile()[0].goals, "")
        other.save_profile(StudyProfile(goals="另一位使用者的目标"), expected_version=0, confirmed=True)
        self.assertEqual(self.db.get_study_profile()[0].goals, "我的目标")

    def test_task_conflicts_and_completion_do_not_invent_time(self):
        task_id = self.create()
        self.db.update_task(task_id, replace(self.task, status="已完成"), expected_version=1, confirmed=True)
        self.assertIsNotNone(self.db.get_task(task_id)["completed_at"])
        self.assertEqual(self.db.get_sessions(), [])
        with self.assertRaises(ConflictError):
            self.db.update_task(task_id, replace(self.task, title="旧页面"), expected_version=1, confirmed=True)
        with self.assertRaises(ConflictError):
            self.db.delete_task(task_id, expected_version=1, confirmed=True)
        self.db.update_task(task_id, self.task, expected_version=2, confirmed=True)
        self.assertIsNone(self.db.get_task(task_id)["completed_at"])

    def test_delete_preserves_sessions_and_events(self):
        task_id = self.create()
        self.db.log_session(task_id, date.today().isoformat(), 37, confirmed=True)
        self.db.delete_task(task_id, expected_version=1, confirmed=True)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(len(self.db.get_tasks(include_deleted=True)), 1)
        self.assertEqual(self.db.get_sessions()[0]["minutes"], 37)
        self.assertEqual([e["action"] for e in self.db.get_events()], ["删除", "创建"])
        with self.assertRaises(ValidationError):
            self.db.log_session(task_id, date.today().isoformat(), 30, confirmed=True)

    def test_sessions_validate_future_date_and_can_be_corrected(self):
        task_id = self.create()
        cases = [(date.today().isoformat(), 0), ((date.today() + timedelta(days=1)).isoformat(), 30), ("bad-date", 30)]
        for day, duration in cases:
            with self.subTest(day=day, duration=duration), self.assertRaises(ValidationError):
                self.db.log_session(task_id, day, duration, confirmed=True)
        with self.assertRaises(ValidationError):
            self.db.log_session(999, date.today().isoformat(), 30, confirmed=True)
        session_id = self.db.log_session(task_id, date.today().isoformat(), 37, confirmed=True)
        self.db.delete_session(session_id, confirmed=True)
        self.assertEqual(self.db.get_sessions(), [])

    def test_old_sessions_keep_original_subject(self):
        task_id = self.create()
        self.db.log_session(task_id, date.today().isoformat(), 30, confirmed=True)
        self.db.update_task(task_id, replace(self.task, subject="数学"), expected_version=1, confirmed=True)
        self.db.log_session(task_id, date.today().isoformat(), 45, confirmed=True)
        self.assertEqual({s["subject"]: s["minutes"] for s in self.db.get_sessions()}, {"Python": 30, "数学": 45})

    def test_sql_values_are_treated_as_data(self):
        title = "'; DROP TABLE tasks; --"
        task_id = self.create(replace(self.task, title=title))
        self.assertEqual(self.db.get_task(task_id)["title"], title)
        self.assertEqual(len(self.db.get_tasks()), 1)

    def test_unrecognized_database_version_is_not_overwritten(self):
        with self.db.connection() as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(ValidationError):
            Database(self.path)
        with self.db.connection() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 99)


class ProgressTests(unittest.TestCase):
    def test_empty_progress_does_not_claim_zero_completion(self):
        result = get_progress([], [], date(2026, 10, 11))
        self.assertIsNone(result["completion_rate"])
        self.assertEqual(result["actual_minutes"], 0)
        self.assertEqual(result["subject_shares"], {})

    def test_week_boundary_real_time_shares_and_deleted_task(self):
        tasks = [
            {"due_date": "2026-10-05", "status": "已完成"},
            {"due_date": "2026-10-11", "status": "进行中"},
            {"due_date": "2026-10-12", "status": "待开始"},
            {"due_date": "2026-10-06", "status": "已完成", "deleted_at": "deleted"},
        ]
        sessions = [
            {"study_date": "2026-10-04", "subject": "Python", "minutes": 10},
            {"study_date": "2026-10-05", "subject": "Python", "minutes": 30},
            {"study_date": "2026-10-11", "subject": "数学", "minutes": 90},
            {"study_date": "2026-10-12", "subject": "数学", "minutes": 60},
        ]
        result = get_progress(tasks, sessions, date(2026, 10, 11))
        self.assertEqual(result["completion_rate"], 0.5)
        self.assertEqual(result["actual_minutes"], 120)
        self.assertEqual(result["subject_shares"], {"Python": 0.25, "数学": 0.75})
        self.assertEqual(len(result["incomplete"]), 1)
        self.assertEqual(result["weekly_history"]["2026-10-05"], 120)

    def test_week_bounds_across_year(self):
        self.assertEqual(week_bounds(date(2027, 1, 1)), (date(2026, 12, 28), date(2027, 1, 4)))


if __name__ == "__main__":
    unittest.main()
