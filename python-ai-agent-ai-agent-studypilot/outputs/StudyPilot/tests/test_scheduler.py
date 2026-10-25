"""规则边界、SQLite 提交冲突与完整计划页面流程；仅使用临时数据。"""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from studypilot.database import ConfirmationRequired, ConflictError, Database
from studypilot.models import DAYS, StudyProfile, TaskInput, ValidationError
from studypilot.progress import week_bounds
from studypilot.scheduler import generate_schedule
from tests.test_app import AppTests


MONDAY = date(2026, 10, 19)


def profile(hours=1, slots=None):
    result = StudyProfile(weekly_hours=hours, max_session_minutes=20)
    result.availability = {day: dict(minutes=0, devices=["纸笔"]) for day in DAYS}
    for day, (amount, devices) in (slots or {"周一": (30, ["纸笔"]), "周二": (30, ["电脑"])}).items():
        result.availability[day] = dict(minutes=amount, devices=devices)
    return result


def task(identifier=1, duration=90, *, computer=False, due="2026-10-25", priority="中", subject="数学", **extra):
    return dict(id=identifier, title=f"任务 {identifier}", subject=subject, due_date=due,
                estimated_minutes=duration, priority=priority, status="待开始", requires_computer=computer, **extra)


class SchedulerTests(unittest.TestCase):
    def generate(self, tasks, *, settings=None, sessions=(), today=MONDAY, reservations=()):
        return generate_schedule(settings or profile(), tasks, sessions, MONDAY, today=today, reservations=reservations)

    def test_budget_daily_capacity_sessions_and_partial_remainder(self):
        actual = [dict(task_id=99, study_date="2026-10-19", minutes=15)]
        result = self.generate([task()], sessions=actual)
        self.assertEqual(result["actual_minutes"], 15)
        self.assertEqual(result["planned_minutes"], 45)
        self.assertEqual(result["unscheduled"][0]["remaining_minutes"], 45)
        self.assertTrue(all(0 < entry["minutes"] <= 20 for entry in result["entries"]))
        self.assertTrue(all(day["actual_minutes"] + day["planned_minutes"] <= day["available_minutes"] for day in result["days"]))

    def test_computer_requirements_and_reserving_computer_days(self):
        result = self.generate([task(1, 30), task(2, 30, computer=True)])
        self.assertFalse(result["unscheduled"])
        for entry in result["entries"]:
            self.assertEqual(entry["date"], "2026-10-20" if entry["requires_computer"] else "2026-10-19")

    def test_missing_computer_and_deadline_are_explained(self):
        result = self.generate([task(1, 30, computer=True, due="2026-10-19"), task(2, due="2026-10-18")])
        reasons = {entry["task_id"]: entry["reason"] for entry in result["unscheduled"]}
        self.assertIn("电脑", reasons[1])
        self.assertIn("截止日期", reasons[2])
        self.assertEqual(result["entries"], [])

    def test_deadline_then_task_and_subject_priority_are_deterministic(self):
        tasks = [task(1, 60, priority="低", due="2026-10-20"), task(2, 60, priority="高"),
                 task(3, 60, priority="高", due="2026-10-20", subject="其他"),
                 task(4, 60, priority="高", due="2026-10-20", subject="数学")]
        result = self.generate(tasks)
        self.assertEqual({entry["task_id"] for entry in result["entries"]}, {4})
        self.assertEqual(result, self.generate(list(reversed(tasks))))

    def test_remaining_duration_uses_lifetime_actual_and_other_week_reservations(self):
        actual = [dict(task_id=1, study_date="2026-10-18", minutes=25)]
        reservations = [dict(task_id=1, date="2026-10-26", minutes=30)]
        # The reserved date must still be valid under the task's deadline.
        result = self.generate([task(1, 70, due="2026-11-01")], sessions=actual, reservations=reservations)
        self.assertEqual(result["actual_minutes"], 0)
        self.assertEqual(result["planned_minutes"], 15)

    def test_completed_deleted_and_fully_studied_tasks_are_not_added(self):
        completed = task(1)
        completed["status"] = "已完成"
        deleted = task(2, deleted_at="deleted")
        result = self.generate([completed, deleted, task(3, 30)],
                               sessions=[dict(task_id=3, study_date="2026-10-18", minutes=30)])
        self.assertFalse(result["entries"])
        self.assertEqual(len(result["notices"]), 1)

    def test_no_past_dates_and_over_budget_actual_does_not_generate_more(self):
        result = self.generate([task()], today=MONDAY + timedelta(days=1))
        self.assertTrue(all(entry["date"] >= "2026-10-20" for entry in result["entries"]))
        result = self.generate([task()], sessions=[dict(task_id=99, study_date="2026-10-19", minutes=80)])
        self.assertEqual(result["planned_minutes"], 0)
        self.assertEqual(result["actual_minutes"], 80)

    def test_past_week_invalid_profile_and_empty_tasks(self):
        with self.assertRaises(ValidationError):
            self.generate([task()], today=MONDAY + timedelta(days=7))
        with self.assertRaises(ValidationError):
            self.generate([task()], settings=profile(hours=2))
        self.assertEqual(self.generate([])["planned_minutes"], 0)


class ScheduleDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "first.db")
        self.week = week_bounds(date.today())[0] + timedelta(days=7)
        self.settings = profile(hours=1, slots={day: (60, ["纸笔", "电脑"]) for day in DAYS})
        self.db.save_profile(self.settings, expected_version=0, confirmed=True)
        self.input = TaskInput("规则排课任务", "Python", (self.week + timedelta(days=13)).isoformat(), 90, requires_computer=True)
        self.task_id = self.db.create_task(self.input, confirmed=True)

    def test_preview_readonly_confirmation_persistence_and_no_fake_actual(self):
        before = self.db.get_tasks(), self.db.get_sessions(), self.db.get_events()
        preview = self.db.preview_schedule(self.week)
        self.assertEqual(self.db.get_schedule(self.week), (None, 0))
        with self.assertRaises(ConfirmationRequired):
            self.db.save_schedule(preview, expected_version=0)
        self.db.save_schedule(preview, expected_version=0, confirmed=True)
        self.assertEqual(Database(self.db.path).get_schedule(self.week), (preview, 1))
        self.assertEqual(before, (self.db.get_tasks(), self.db.get_sessions(), self.db.get_events()))
        self.assertEqual(Database(self.root / "other.db").get_schedule(self.week), (None, 0))

    def test_replacement_conflict_and_tampered_preview_are_rejected(self):
        preview = self.db.preview_schedule(self.week)
        tampered = deepcopy(preview)
        tampered["entries"][0]["minutes"] += 1
        with self.assertRaises(ValidationError):
            self.db.save_schedule(tampered, expected_version=0, confirmed=True)
        self.db.save_schedule(preview, expected_version=0, confirmed=True)
        with self.assertRaises(ConflictError):
            self.db.save_schedule(preview, expected_version=0, confirmed=True)
        self.db.save_schedule(self.db.preview_schedule(self.week), expected_version=1, confirmed=True)
        self.assertEqual(self.db.get_schedule(self.week)[1], 2)

    def test_changed_tasks_profile_or_actual_invalidate_preview(self):
        actions = [lambda: self.db.update_task(self.task_id, replace(self.input, estimated_minutes=100), expected_version=1, confirmed=True),
                   lambda: self.db.save_profile(replace(self.settings, max_session_minutes=25), expected_version=1, confirmed=True),
                   lambda: self.db.log_session(self.task_id, date.today().isoformat(), 5, confirmed=True)]
        for action in actions:
            preview = self.db.preview_schedule(self.week)
            action()
            with self.assertRaises(ConflictError):
                self.db.save_schedule(preview, expected_version=0, confirmed=True)
        self.assertEqual(self.db.get_schedule(self.week), (None, 0))

    def test_other_week_reservations_prevent_double_planning_and_invalidate_previews(self):
        stale = self.db.preview_schedule(self.week + timedelta(days=7))
        first = self.db.preview_schedule(self.week)
        self.db.save_schedule(first, expected_version=0, confirmed=True)
        with self.assertRaises(ConflictError):
            self.db.save_schedule(stale, expected_version=0, confirmed=True)
        later = self.db.preview_schedule(self.week + timedelta(days=7))
        self.assertEqual(first["planned_minutes"], 60)
        self.assertEqual(later["planned_minutes"], 30)

    def test_delete_requires_confirmation_and_preserves_tasks_and_actual(self):
        preview = self.db.preview_schedule(self.week)
        self.db.save_schedule(preview, expected_version=0, confirmed=True)
        with self.assertRaises(ConfirmationRequired):
            self.db.delete_schedule(self.week, expected_version=1)
        with self.assertRaises(ConflictError):
            self.db.delete_schedule(self.week, expected_version=2, confirmed=True)
        self.db.delete_schedule(self.week, expected_version=1, confirmed=True)
        self.assertEqual(self.db.get_schedule(self.week), (None, 0))
        self.assertEqual(len(self.db.get_tasks()), 1)
        self.assertEqual(self.db.get_sessions(), [])

    def test_profile_must_be_saved_and_existing_v1_data_is_preserved(self):
        empty = Database(self.root / "empty.db")
        with self.assertRaises(ValidationError):
            empty.preview_schedule(self.week)
        with self.db.connection() as conn:
            conn.execute("DROP TABLE schedule_plans")
        upgraded = Database(self.db.path)
        self.assertEqual(upgraded.get_task(self.task_id)["title"], self.input.title)
        self.assertEqual(upgraded.get_study_profile()[1], 1)
        self.assertEqual(upgraded.get_schedule(self.week), (None, 0))


class ScheduleUITests(unittest.TestCase):
    setUp = AppTests.setUp
    fresh_app = AppTests.fresh_app
    click = AppTests.click
    navigate = AppTests.navigate

    def test_schedule_preview_confirm_reload_conflict_and_delete(self):
        db = Database(self.db_path)
        settings = profile(hours=2, slots={day: (60, ["纸笔", "电脑"]) for day in DAYS})
        db.save_profile(settings, expected_version=0, confirmed=True)
        selected = week_bounds(date.today())[0] + timedelta(days=7)
        db.create_task(TaskInput("页面排课验证", "Python", (selected + timedelta(days=6)).isoformat(), 90, requires_computer=True), confirmed=True)
        self.navigate("学习计划")
        self.app.date_input(key="schedule_week").set_value(selected).run()
        self.click("生成计划预览")
        self.assertEqual(db.get_schedule(selected), (None, 0))
        self.assertEqual(self.app.session_state["schedule_preview"]["data"]["planned_minutes"], 90)
        self.click("确认保存计划")
        self.assertTrue(any("确认" in item.value for item in self.app.error))
        self.app.checkbox(key="schedule_confirm").check()
        self.click("确认保存计划")
        self.assertEqual(db.get_schedule(selected)[1], 1)
        self.assertEqual(db.get_sessions(), [])
        self.app = self.fresh_app()
        self.navigate("学习计划")
        self.app.date_input(key="schedule_week").set_value(selected).run()
        self.assertTrue(any("已保存的本周计划" == item.label for item in self.app.expander))
        self.click("生成计划预览")
        task_id = db.get_tasks()[0]["id"]
        db.log_session(task_id, date.today().isoformat(), 10, confirmed=True)
        self.app.checkbox(key="schedule_confirm").check()
        self.click("确认保存计划")
        self.assertTrue(any("重新生成" in item.value for item in self.app.error))
        self.assertEqual(db.get_schedule(selected)[1], 1)
        self.click("删除本周计划")
        self.assertEqual(db.get_schedule(selected)[1], 1)
        self.app.checkbox(key=f"delete_schedule_confirm_{selected}_1").check()
        self.click("删除本周计划")
        self.assertEqual(db.get_schedule(selected), (None, 0))
        self.assertEqual(db.get_sessions()[0]["minutes"], 10)


del AppTests


if __name__ == "__main__":
    unittest.main()
