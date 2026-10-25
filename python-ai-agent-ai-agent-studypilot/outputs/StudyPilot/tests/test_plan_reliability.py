"""Phase 1: real constraints, old JSON compatibility and atomic retry receipts."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from studypilot.agent_tools import parse_arguments
from studypilot.database import ConfirmationRequired, ConflictError, Database
from studypilot.models import DAYS, SUBJECTS, StudyProfile, TaskInput, ValidationError
from studypilot.progress import week_bounds
from studypilot.scheduler import generate_schedule

MONDAY = date(2026, 10, 19)


def settings():
    return StudyProfile(weekly_hours=1, max_session_minutes=20,
        availability={d:dict(minutes=30,devices=["纸笔"] if i==0 else ["电脑"])
                      for i,d in enumerate(DAYS)})


def task(identifier=1, duration=90):
    return asdict(TaskInput("Concrete practice", "Python", "2026-11-01", duration)) | {"id":identifier}


class ConstraintTests(unittest.TestCase):
    def test_target_deadline_limits_sessions_and_explains_shortfall(self):
        profile=replace(settings(),goal_deadline="2026-10-19")
        result=generate_schedule(profile,[task()],[],MONDAY,today=MONDAY)
        self.assertEqual(result["planned_minutes"],30)
        self.assertTrue(all(e["date"]<=profile.goal_deadline for e in result["entries"]))
        self.assertEqual(result["unscheduled"][0]["remaining_minutes"],60)
        self.assertTrue(result["unscheduled"][0]["suggestion"])
        profile.goal_deadline="2026-10-18"
        result=generate_schedule(profile,[task()],[],MONDAY,today=MONDAY)
        self.assertEqual(result["entries"],[])
        self.assertIn("目标期限",result["unscheduled"][0]["reason"])

    def test_computer_and_task_deadline_remain_hard_limits(self):
        profile=replace(settings(),goal_deadline="2026-10-25")
        t=task() | {"requires_computer":True,"due_date":"2026-10-19"}
        result=generate_schedule(profile,[t],[],MONDAY,today=MONDAY)
        self.assertEqual(result["entries"],[])
        self.assertIn("电脑",result["unscheduled"][0]["reason"])

    def test_foundation_breaks_equal_priority_ties_without_inventing_estimates(self):
        profile=replace(settings(),weekly_hours=0.5)
        profile.levels={s:"基础" for s in SUBJECTS}
        profile.levels["数学"]="零基础"
        profile.priorities={s:"中" for s in SUBJECTS}
        result=generate_schedule(profile,[task(1,30),task(2,30)|{"subject":"数学"}],[],MONDAY,today=MONDAY)
        self.assertEqual({e["task_id"] for e in result["entries"]},{2})
        self.assertEqual(result["planned_minutes"],30)

    def test_actual_time_fulfilling_other_week_reservation_is_not_deducted_twice(self):
        sessions=[dict(task_id=1,study_date=MONDAY.isoformat(),minutes=20)]
        reservations=[dict(task_id=1,date=MONDAY.isoformat(),minutes=n) for n in [20,40]]
        result=generate_schedule(settings(),[task()],sessions,MONDAY+timedelta(days=7),
                                 today=MONDAY,reservations=reservations)
        self.assertEqual(result["planned_minutes"],30)

    def test_old_reservations_beyond_new_deadline_do_not_hide_shortfall(self):
        profile=replace(settings(),goal_deadline="2026-10-19")
        reservations=[dict(task_id=1,date="2026-10-26",minutes=90)]
        result=generate_schedule(profile,[task()],[],MONDAY,today=MONDAY,reservations=reservations)
        self.assertEqual(result["planned_minutes"],30)
        self.assertEqual(result["unscheduled"][0]["remaining_minutes"],60)
        task_limit=task() | {"due_date":"2026-10-19"}
        result=generate_schedule(settings(),[task_limit],[],MONDAY,today=MONDAY,reservations=reservations)
        self.assertEqual(result["planned_minutes"],30)
        self.assertEqual(result["unscheduled"][0]["remaining_minutes"],60)

    def test_date_boundary_and_invalid_structured_goal_deadline_are_rejected(self):
        with self.assertRaises(ValidationError):
            week_bounds(date.max)
        for value in [None,False,-1,"2026-02-30","tomorrow"]:
            with self.subTest(value=value),self.assertRaises(ValidationError):
                replace(settings(),goal_deadline=value).validated()
        raw=dict(expected_version=0,profile=asdict(settings())|{"goal_deadline":"2026-02-30"},reason="Review first")
        args=parse_arguments("propose_profile_update",json.dumps(raw))
        with self.assertRaises(ValidationError):
            StudyProfile(**args["profile"]).validated()
        with self.assertRaises(ValidationError):
            parse_arguments("propose_weekly_plan",'{"week_of":"2026-10-19","reason":"x","entries":[]}')

    def test_generated_schedules_obey_constraints_across_varied_inputs(self):
        rng=random.Random(2510)
        for case in range(75):
            availability={d:dict(minutes=rng.choice([0,15,30,60]),devices=["电脑"] if rng.randrange(2) else ["纸笔"])
                          for d in DAYS}
            total=sum(s["minutes"] for s in availability.values())
            if total==0:
                continue
            p=StudyProfile(weekly_hours=min(total,120)/60,max_session_minutes=rng.choice([10,20,30]),
                           availability=availability,goal_deadline="2026-10-23")
            tasks=[task(i+1,rng.randrange(1,121))|{"requires_computer":bool(rng.randrange(2)),
                     "due_date":(MONDAY+timedelta(days=rng.randrange(7))).isoformat()} for i in range(4)]
            sessions=[dict(task_id=99,study_date=MONDAY.isoformat(),minutes=10)]
            plan=generate_schedule(p,tasks,sessions,MONDAY,today=MONDAY)
            with self.subTest(case=case):
                self.assertLessEqual(plan["planned_minutes"],max(0,plan["budget_minutes"]-plan["actual_minutes"]))
                for day in plan["days"]:
                    self.assertLessEqual(day["planned_minutes"],max(0,day["available_minutes"]-day["actual_minutes"]))
                for e in plan["entries"]:
                    t=tasks[e["task_id"]-1]
                    self.assertTrue(0<e["minutes"]<=p.max_session_minutes)
                    self.assertLessEqual(e["date"],min(t["due_date"],p.goal_deadline))
                    slot=availability[DAYS[(date.fromisoformat(e["date"])-MONDAY).days]]
                    self.assertTrue(not t["requires_computer"] or "电脑" in slot["devices"])


class RetryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=Database(self.root/'study.db')
        self.task=TaskInput("Practise one exercise","数学",date.today().isoformat(),30)
        self.key="isolated-request-key-1234"

    def test_same_key_concurrent_and_reopened_requests_create_one_task(self):
        def create(_):
            return Database(self.db.path).create_task(self.task,confirmed=True,request_id=self.key)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(create,range(4)))
        self.assertEqual(len(set(results)),1)
        self.assertEqual(len(self.db.get_tasks()),1)
        self.assertEqual(len(self.db.get_events()),1)
        self.assertEqual(create(0),results[0])

    def test_unconfirmed_conflicting_and_invalid_keys_do_not_write(self):
        with self.assertRaises(ConfirmationRequired):
            self.db.create_task(self.task,request_id=self.key)
        self.db.create_task(self.task,confirmed=True,request_id=self.key)
        with self.assertRaises(ConflictError):
            self.db.create_task(replace(self.task,title="Different"),confirmed=True,request_id=self.key)
        with self.assertRaises(ValidationError):
            self.db.create_task(self.task,confirmed=True,request_id="bad")
        self.assertEqual(len(self.db.get_tasks()),1)

    def test_record_retries_do_not_double_actual_minutes_or_leak_across_accounts(self):
        task_id=self.db.create_task(self.task,confirmed=True)
        def log():
            return self.db.log_session(task_id,date.today().isoformat(),17,confirmed=True,request_id=self.key)
        self.assertEqual(log(),log())
        self.assertEqual(sum(r["minutes"] for r in self.db.get_sessions()),17)
        other=Database(self.root/'other.db')
        other.create_task(self.task,confirmed=True,request_id=self.key)
        self.assertEqual(len(other.get_tasks()),1)
        self.assertEqual(self.db.get_sessions()[0]["minutes"],17)

    def test_receipt_failure_rolls_back_task_and_event_then_retry_succeeds(self):
        with self.db.connection() as conn:
            conn.execute("CREATE TRIGGER fail_request BEFORE INSERT ON request_receipts BEGIN SELECT RAISE(ABORT,'isolated failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.db.create_task(self.task,confirmed=True,request_id=self.key)
        self.assertEqual(self.db.get_tasks(),[])
        self.assertEqual(self.db.get_events(),[])
        with self.db.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM request_receipts").fetchone()[0],0)
            conn.execute("DROP TRIGGER fail_request")
        self.db.create_task(self.task,confirmed=True,request_id=self.key)
        self.assertEqual(len(self.db.get_tasks()),1)

    def test_additive_initialization_preserves_legacy_profile_and_task_data(self):
        self.db.create_task(self.task,confirmed=True)
        legacy=asdict(StudyProfile(goals="Keep my exact goal"))
        legacy.pop("goal_deadline")
        with self.db.connection() as conn:
            conn.execute("INSERT INTO profile VALUES(1,?,1,'legacy')",(json.dumps(legacy),))
            conn.execute("DROP TABLE request_receipts")
        db=Database(self.db.path)
        profile,version=db.get_study_profile()
        self.assertEqual((profile.goals,profile.goal_deadline,version),("Keep my exact goal","",1))
        self.assertEqual(len(db.get_tasks()),1)
        with db.connection() as conn:
            self.assertEqual(json.loads(conn.execute("SELECT payload FROM profile").fetchone()[0]),legacy)
        future=week_bounds(date.today())[0]+timedelta(days=7)
        profile.goal_deadline=(future+timedelta(days=6)).isoformat()
        db.save_profile(profile,expected_version=1,confirmed=True)
        db.update_task(1,replace(self.task,due_date=profile.goal_deadline),expected_version=1,confirmed=True)
        preview=db.preview_schedule(future)
        bad=deepcopy(preview)
        bad["entries"][0]["minutes"]=-30
        with self.assertRaises(ValidationError):
            db.save_schedule(bad,expected_version=0,confirmed=True)
        self.assertEqual(db.get_schedule(future),(None,0))


if __name__=="__main__":
    unittest.main()
