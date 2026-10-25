"""HTTP 账号、确认、越权、CSRF 与持久化。测试使用独立临时数据。"""
from dataclasses import asdict
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient

from studypilot.auth import AuthStore
from studypilot.models import StudyProfile, TaskInput
from studypilot.proposals import stage_proposal
from studypilot.web import COOKIE, create_app

PASSWORD = "Temporary web testing password 2026"


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = AuthStore(Path(self.temp.name)/"accounts")
        self.prepare()

    def prepare(self):
        self.name = "网页测试-" + uuid.uuid4().hex[:12]
        self.user, self.recovery = self.auth.register(self.name, PASSWORD, confirmed=True)
        self.token = self.auth.login(self.name, PASSWORD)
        self.db = self.auth.study_database(self.token)
        self.app = create_app(lambda: self.auth)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        result = self.client.post("/api/login", json={"username": self.name, "password": PASSWORD}, headers={"origin":"http://testserver"})
        self.assertEqual(result.status_code, 200, result.text)
        self.headers = {"origin":"http://testserver", "x-csrf-token":result.json()["csrf"]}
        self.task = asdict(TaskInput("网页真实任务", "数学", date.today().isoformat(), 30))

    def call(self, path, body=None, method="POST"):
        return self.client.request(method, "/api"+path, json=body or {}, headers=self.headers)

    def test_entrypoint_assets_and_unconfigured_database(self):
        fresh = TestClient(create_app())
        with patch.dict(os.environ, {"DATABASE_URL":"","POSTGRES_URL":"","STUDYPILOT_WEB_LOCAL":"", "VERCEL":"1"}):
            self.assertEqual(fresh.get("/").status_code,200)
            self.assertEqual(fresh.get("/study.js").status_code,200)
            self.assertEqual(fresh.get("/study.css").status_code,200)
            self.assertEqual(fresh.get("/learning-map.svg").status_code,200)
            self.assertFalse(fresh.get("/api/health").json()["database_configured"])
            response = fresh.get("/api/me")
            self.assertEqual(response.status_code,503)
            self.assertNotIn("DATABASE_URL",response.json()["error"])
        fresh.close()

    def test_cookie_csrf_and_origin_guard(self):
        response = self.client.post("/api/login",json={"username":self.name,"password":PASSWORD},headers={"origin":"http://testserver"})
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly",cookie); self.assertIn("samesite=strict",cookie)
        self.assertNotIn(PASSWORD,response.text)
        self.assertNotIn(self.token,response.text)
        for headers in ({}, {"origin":"https://foreign.example"}, {"origin":"http://testserver"}):
            blocked = self.client.post("/api/tasks",json={"task":self.task,"confirmed":True},headers=headers)
            self.assertEqual(blocked.status_code,403)
        self.assertEqual(self.db.get_tasks(),[])
        with patch.dict(os.environ,{"VERCEL":"1"}):
            secure = self.client.post("/api/login",json={"username":self.name,"password":PASSWORD},headers={"origin":"https://testserver"})
            self.assertIn("secure",secure.headers["set-cookie"].lower())

    def test_registration_recovery_and_errors_do_not_echo_credentials(self):
        name = "新中文账号-" + uuid.uuid4().hex[:8]
        payload = dict(username=name,password=PASSWORD,password_again=PASSWORD,confirmed=False)
        self.assertEqual(self.call("/register",payload).status_code,400)
        payload["confirmed"]=True
        registered=self.call("/register",payload)
        self.assertEqual(registered.status_code,200)
        recovered=self.call("/recover",dict(username=name,recovery_code=registered.json()["recovery_code"],new_password=PASSWORD+"new",password_again=PASSWORD+"new",confirmed=True))
        self.assertEqual(recovered.status_code,200)
        self.assertNotEqual(recovered.json()["recovery_code"],registered.json()["recovery_code"])
        malformed=self.call("/login",dict(username=name,password=PASSWORD,role="developer"))
        self.assertEqual(malformed.status_code,422); self.assertNotIn(PASSWORD,malformed.text)

    def test_task_confirmation_conflict_status_and_soft_delete(self):
        self.assertEqual(self.call("/tasks",dict(task=self.task)).status_code,400)
        created=self.call("/tasks",dict(task=self.task,confirmed=True))
        self.assertEqual(created.status_code,200,created.text)
        task_id=created.json()["task_id"]
        changed=dict(self.task,status="已完成")
        self.assertEqual(self.call("/tasks/"+str(task_id),dict(task=changed,expected_version=1,confirmed=True),"PUT").status_code,200)
        self.assertEqual(self.db.get_sessions(),[])
        self.assertEqual(self.call("/tasks/"+str(task_id),dict(task=self.task,expected_version=1,confirmed=True),"PUT").status_code,409)
        self.assertEqual(self.call("/tasks/"+str(task_id),dict(expected_version=2,confirmed=True),"DELETE").status_code,200)
        self.assertEqual(self.db.get_tasks(),[])

    def test_profile_records_and_statistics_are_real(self):
        result=self.call("/profile",dict(profile=asdict(StudyProfile()),expected_version=0,confirmed=True))
        self.assertEqual(result.status_code,200,result.text)
        task_id=self.call("/tasks",dict(task=self.task,confirmed=True)).json()["task_id"]
        record=dict(task_id=task_id,study_date=date.today().isoformat(),minutes=17,note="真实记录",confirmed=True)
        saved=self.call("/records",record)
        self.assertEqual(saved.status_code,200,saved.text)
        state=self.client.get("/api/state").json()
        self.assertEqual(state["progress"]["actual_minutes"],17)
        self.assertEqual(state["profile"]["goals"],"")
        self.assertEqual(self.call("/records/"+str(saved.json()["session_id"]),dict(confirmed=True),"DELETE").status_code,200)
        self.assertEqual(self.db.get_sessions(),[])

    def test_rule_plan_preview_confirmation_and_stale_inputs(self):
        self.db.save_profile(StudyProfile(),expected_version=0,confirmed=True)
        self.db.create_task(TaskInput(**self.task),confirmed=True)
        response=self.client.get("/api/plans/preview",params={"week_of":date.today().isoformat()})
        self.assertEqual(response.status_code,200,response.text)
        payload=response.json()
        self.assertEqual(self.call("/plans",payload).status_code,400)
        self.db.create_task(TaskInput(**dict(self.task,title="新的任务")),confirmed=True)
        self.assertEqual(self.call("/plans",dict(**payload,confirmed=True)).status_code,409)
        fresh=self.client.get("/api/plans/preview",params={"week_of":date.today().isoformat()}).json()
        self.assertEqual(self.call("/plans",dict(**fresh,confirmed=True)).status_code,200)
        self.assertTrue(self.client.get("/api/state").json()["plans"])

    def test_personal_username_password_sessions_and_export(self):
        result=self.call("/personal",dict(nickname="新的昵称",avatar="🌱",bio="慢慢学习",expected_version=0,confirmed=True))
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get("/api/me").json()["personal"]["nickname"],"新的昵称")
        renamed=self.name+"改名"
        self.assertEqual(self.call("/username",dict(new_username=renamed,current_password=PASSWORD,expected_username=self.name,confirmed=True)).status_code,200)
        self.assertEqual(self.client.get("/api/me").json()["account"]["username"],renamed)
        self.assertEqual(self.client.get("/api/sessions").status_code,200)
        exported=self.client.get("/api/export")
        self.assertEqual(exported.status_code,200)
        for secret in (PASSWORD,self.recovery,"password_hash","token_hash"):
            self.assertNotIn(secret,exported.text)
        changed=self.call("/password",dict(current_password=PASSWORD,new_password=PASSWORD+"next",password_again=PASSWORD+"next",confirmed=True))
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertIn("recovery_code",changed.json())
        self.assertEqual(self.client.get("/api/me").status_code,401)

    def test_proposal_api_requires_confirmation_and_is_idempotent(self):
        proposal_id=stage_proposal(self.auth,self.token,"create_task",{"task":self.task},"网页测试",request_id="web",call_id="test")
        path="/proposals/"+proposal_id+"/execute"
        self.assertEqual(self.call(path).status_code,400)
        self.assertEqual(self.db.get_tasks(),[])
        applied=self.call(path,{"confirmed":True})
        self.assertEqual(applied.status_code,200,applied.text)
        self.assertEqual(self.call(path,{"confirmed":True}).json(),applied.json())
        self.assertEqual(len(self.db.get_tasks()),1)

    def test_account_isolation_and_developer_permission(self):
        task_id=self.db.create_task(TaskInput(**self.task),confirmed=True)
        proposal_id=stage_proposal(self.auth,self.token,"create_task",{"task":self.task},"网页隔离",request_id="other",call_id="test")
        other=self.name+"另一位"
        self.auth.register(other,PASSWORD,confirmed=True)
        result=self.call("/login",dict(username=other,password=PASSWORD))
        self.headers["x-csrf-token"]=result.json()["csrf"]
        state=self.client.get("/api/state").json()
        self.assertEqual(state["tasks"],[]);self.assertEqual(state["proposals"],[])
        self.assertEqual(self.call("/proposals/"+proposal_id+"/execute",{"confirmed":True}).status_code,400)
        self.assertEqual(self.call("/tasks/"+str(task_id),dict(expected_version=1,confirmed=True),"DELETE").status_code,409)
        self.assertEqual(len(self.db.get_tasks()),1)
        self.assertEqual(self.client.get("/api/development").status_code,403)
        self.auth.set_role(other,"developer",confirmed=True)
        self.assertEqual(self.client.get("/api/development").status_code,200)

    def test_ai_consent_and_missing_key_never_execute_business_changes(self):
        with patch.dict(os.environ,{"ZHIPU_API_KEY":"","SILICONFLOW_API_KEY":""}):
            self.assertEqual(self.call("/agent",dict(prompt="新增任务")).status_code,400)
            response=self.call("/agent",dict(prompt="新增任务",consent=True))
            self.assertEqual(response.status_code,502,response.text)
        self.assertEqual(self.db.get_tasks(),[])

    def test_ai_quota_concurrent_and_reopened_storage(self):
        from concurrent.futures import ThreadPoolExecutor
        from studypilot.quota import QuotaExceeded
        if hasattr(self.auth, "source"):
            from studypilot.postgres import Postgres, PostgresAuthStore
            reopened = PostgresAuthStore(Postgres(self.auth.source.url))
        else:
            reopened = AuthStore(self.auth.root)
        # Site counts may include earlier tests on the isolated PostgreSQL DB.
        with patch.dict(os.environ, {"STUDYPILOT_AI_USER_LIMIT":"2", "STUDYPILOT_AI_SITE_LIMIT":"100000"}):
            def attempt(index):
                try:
                    (self.auth if index % 2 else reopened).ai_meter().reserve(self.token)
                    return True
                except QuotaExceeded:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(attempt, range(6)))
            self.assertEqual(sum(results), 2)


    def test_keyed_task_and_record_retries_create_once_and_reject_payload_reuse(self):
        headers={**self.headers,"Idempotency-Key":"web-retry-request-key-1234"}
        body=dict(task=self.task,confirmed=True)
        first=self.client.post("/api/tasks",json=body,headers=headers)
        repeated=self.client.post("/api/tasks",json=body,headers=headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json(),repeated.json())
        self.assertEqual(len(self.db.get_tasks()),1)
        changed=dict(task={**self.task,"title":"Different action"},confirmed=True)
        self.assertEqual(self.client.post("/api/tasks",json=changed,headers=headers).status_code,409)
        self.assertEqual(self.client.post("/api/tasks",json={**body,"confirmed":False},headers=headers).status_code,400)
        record=dict(task_id=first.json()["task_id"],study_date=date.today().isoformat(),minutes=19,confirmed=True)
        headers["Idempotency-Key"]="web-record-retry-key-1234"
        saved=self.client.post("/api/records",json=record,headers=headers)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json(),self.client.post("/api/records",json=record,headers=headers).json())
        self.assertEqual(sum(r["minutes"] for r in self.db.get_sessions()),19)

    def test_optional_goal_deadline_old_clients_and_boundary_dates(self):
        deadline=date.today().replace(year=date.today().year+1).isoformat()
        profile=asdict(StudyProfile(goal_deadline=deadline))
        self.assertEqual(self.call("/profile",dict(profile=profile,expected_version=0,confirmed=True)).status_code,200)
        legacy={k:v for k,v in profile.items() if k!="goal_deadline"}
        self.assertEqual(self.call("/profile",dict(profile=legacy,expected_version=1,confirmed=True)).status_code,200)
        state=self.client.get("/api/state").json()
        self.assertEqual(state["profile"]["goal_deadline"],deadline)
        self.assertEqual(state["profile"]["goals"],"")
        self.assertEqual(self.client.get("/api/plans/preview?week_of=9999-12-31").status_code,400)
        invalid={**profile,"goal_deadline":"2026-02-30"}
        self.assertEqual(self.call("/profile",dict(profile=invalid,expected_version=2,confirmed=True)).status_code,400)
        self.assertEqual(self.client.get("/api/state").json()["profile"]["goal_deadline"],deadline)
        self.assertEqual(self.client.get("/workflow.js").status_code,200)

    def test_database_failure_returns_safe_error_and_retry_keeps_one_write(self):
        headers={**self.headers,"Idempotency-Key":"web-failed-request-key-1234"}
        body=dict(task=self.task,confirmed=True)
        with patch("studypilot.database.Database._event",side_effect=sqlite3.OperationalError("private storage detail")):
            failed=self.client.post("/api/tasks",json=body,headers=headers)
        self.assertEqual(failed.status_code,503)
        self.assertNotIn("private storage detail",failed.text)
        self.assertEqual(self.db.get_tasks(),[])
        self.assertEqual(self.client.post("/api/tasks",json=body,headers=headers).status_code,200)
        self.assertEqual(self.client.post("/api/tasks",json=body,headers=headers).status_code,200)
        self.assertEqual(len(self.db.get_tasks()),1)


@unittest.skipUnless(os.getenv("STUDYPILOT_TEST_POSTGRES"),"需显式提供独立测试 PostgreSQL URL")
class PostgresWebTests(WebTests):
    def setUp(self):
        from studypilot.postgres import Postgres, PostgresAuthStore
        url=os.environ["STUDYPILOT_TEST_POSTGRES"]
        if "127.0.0.1:" not in url and "localhost:" not in url:
            raise RuntimeError("此测试只允许本机独立测试数据库，不能使用生产数据库。")
        self.auth=PostgresAuthStore(Postgres(url))
        self.prepare()

    def test_concurrent_confirmation_commits_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from studypilot.proposals import execute_proposal
        proposal_id=stage_proposal(self.auth,self.token,"create_task",{"task":self.task},"并发测试",request_id="concurrent",call_id="one")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:execute_proposal(self.auth,self.token,proposal_id,confirmed=True),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.db.get_tasks()),1)
        self.assertEqual(len(self.db.get_events()),1)

    def test_receipt_failure_rolls_back_postgres_business_transaction(self):
        from psycopg import sql
        from studypilot.proposals import execute_proposal, list_proposals
        proposal_id=stage_proposal(self.auth,self.token,"create_task",{"task":self.task},"回滚测试",request_id="rollback",call_id="one")
        with self.auth.source.connect() as raw:
            raw.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.db.schema)))
            raw.execute("""CREATE FUNCTION fail_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'isolated test receipt failure'; END; $$""")
            raw.execute("""CREATE TRIGGER fail_receipt BEFORE UPDATE ON agent_proposals
                FOR EACH ROW WHEN (NEW.state='applied') EXECUTE FUNCTION fail_receipt()""")
        with self.assertRaises(sqlite3.Error):
            execute_proposal(self.auth,self.token,proposal_id,confirmed=True)
        self.assertEqual(self.db.get_tasks(),[])
        self.assertEqual(self.db.get_events(),[])
        self.assertEqual(list_proposals(self.auth,self.token)[0]["state"],"pending")

    def test_readonly_tools_and_persistence_after_new_store(self):
        from studypilot.agent_tools import AgentTools
        from studypilot.postgres import Postgres, PostgresAuthStore
        self.db.save_profile(StudyProfile(),expected_version=0,confirmed=True)
        task_id=self.db.create_task(TaskInput(**self.task),confirmed=True)
        self.db.log_session(task_id,date.today().isoformat(),9,confirmed=True)
        tools=AgentTools(self.auth,self.token,"pg-read")
        today=date.today().isoformat()
        for name,args in [("get_study_profile",{}),("list_tasks",dict(subject="全部",status="全部",offset=0,limit=30)),
                          ("get_task",dict(task_id=task_id)),("get_study_records",dict(start_date=today,end_date=today,offset=0,limit=20)),
                          ("get_progress",dict(day=today)),("preview_weekly_plan",dict(week_of=today))]:
            self.assertIsInstance(tools.call(name,json.dumps(args),name),dict)
        with self.assertRaises(sqlite3.Error):
            with self.db.connection() as conn:
                conn.execute("PRAGMA query_only=ON")
                conn.execute("DELETE FROM tasks")
        fresh=PostgresAuthStore(Postgres(os.environ["STUDYPILOT_TEST_POSTGRES"]))
        self.assertEqual(fresh.study_database(self.token).get_task(task_id)["title"],self.task["title"])
        self.assertEqual(len(fresh.study_database(self.token).get_sessions()),1)


if __name__=="__main__":
    unittest.main()
