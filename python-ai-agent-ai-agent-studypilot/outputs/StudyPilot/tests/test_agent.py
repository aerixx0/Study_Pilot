"""真实临时 SQLite + Responses 协议桩；不调用联网模型或真实账号。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from streamlit.testing.v1 import AppTest

from studypilot.agent import AIError, run_agent
from studypilot.ai import FreeChatTransport
from studypilot.agent_tools import AgentTools, TOOLS, parse_arguments
from studypilot.auth import AuthStore, AuthError
from studypilot.database import ConfirmationRequired, ConflictError, Database
from studypilot.models import StudyProfile, TaskInput, ValidationError
from studypilot.proposals import execute_proposal, list_proposals, reject_proposal, stage_proposal


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Temporary agent testing phrase 2026"


def completed(*items):
    return {"status": "completed", "output": list(items)}


def call(name, args, call_id="call_1"):
    return dict(type="function_call", name=name, arguments=json.dumps(args, ensure_ascii=False), call_id=call_id)


def answer(text="已生成提案，尚未执行。"):
    return completed({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})


class FakeResponses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, payload, *, timeout):
        self.requests.append(deepcopy(payload))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = AuthStore(Path(self.temp.name) / "accounts")
        self.account, _ = self.auth.register("learner", PASSWORD, confirmed=True)
        self.token = self.auth.login("learner", PASSWORD)
        self.db = self.auth.study_database(self.token)
        self.task = asdict(TaskInput("复习数学", "数学", date.today().isoformat(), 30))
        self.tools = AgentTools(self.auth, self.token, "request-a")

    def stage(self, action="create_task", data=None, **kwargs):
        return stage_proposal(self.auth, self.token, action, data or {"task": self.task}, "按用户要求调整",
                              request_id=kwargs.get("request_id", "r"), call_id=kwargs.get("call_id", "c"))

    def test_responses_loop_returns_all_outputs_and_only_stages_changes(self):
        reasoning = {"type": "reasoning", "id": "reason_1", "summary": [], "encrypted_content": "opaque-test-content"}
        fake = FakeResponses(completed(reasoning, call("get_study_profile", {})),
            completed(call("propose_task_create", {"task": self.task, "reason": "你提出的任务"}, "call_2")), answer())
        result = run_agent(self.auth, self.token, "请新增复习数学任务", transport=fake)
        self.assertEqual(result.rounds, 3)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(len(result.proposals), 1)
        self.assertEqual(list_proposals(self.auth, self.token)[0]["state"], "pending")
        self.assertIn(reasoning, fake.requests[1]["input"])
        self.assertTrue(any(item.get("type") == "function_call_output" for item in fake.requests[1]["input"]))
        self.assertEqual(set(fake.requests[0]), {"instructions", "input", "tools", "max_output_tokens"})
        self.assertNotIn(self.token, json.dumps(fake.requests))
        self.assertNotIn(PASSWORD, json.dumps(fake.requests))
        self.assertTrue(all(tool["strict"] and not tool["parameters"]["additionalProperties"] for tool in TOOLS))

    def test_all_read_tools_do_not_change_learning_database(self):
        task_id = self.db.create_task(TaskInput(**self.task), confirmed=True)
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        self.db.log_session(task_id, date.today().isoformat(), 10, confirmed=True)
        day = date.today().isoformat()
        requests = [("get_study_profile", {}), ("list_tasks", dict(subject="全部", status="全部", limit=30, offset=0)),
                    ("get_task", dict(task_id=task_id)), ("get_study_records", dict(start_date=day, end_date=day, limit=20, offset=0)),
                    ("get_progress", dict(day=day)), ("preview_weekly_plan", dict(week_of=day))]
        before = self.db.export_data()
        with self.db.connection() as watcher:
            version = watcher.execute("PRAGMA data_version").fetchone()[0]
            for name, args in requests:
                self.assertIsInstance(self.tools.call(name, json.dumps(args), name), dict)
            self.assertEqual(watcher.execute("PRAGMA data_version").fetchone()[0], version)
        self.assertEqual(before, self.db.export_data())

    def test_whitelist_strict_types_and_malformed_json(self):
        for name, raw in [("execute_proposal", '{}'), ("shell", '{}'), ("get_task", '{"task_id":true}'),
                          ("get_task", '{"task_id":1,"account_id":"foreign"}'), ("get_task", '{"task_id":1,"confirmed":true}'),
                          ("get_task", '{"task_id":1,"task_id":2}'), ("get_task", '{"task_id":NaN}'),
                          ("get_task", '{"task_id":' + '9'*1000 + '}'), ("get_task", '['*10000),
                          ("propose_task_create", json.dumps(dict(task=self.task | {"title": "\ud800"}, reason="测试")))]:
            with self.subTest(name=name, raw=raw[:60]), self.assertRaises(ValidationError):
                parse_arguments(name, raw)
        self.assertEqual(self.db.get_tasks(), [])

    def test_paging_does_not_hide_truncation(self):
        self.db.create_task(TaskInput(**(self.task | {"notes": "x"*300})), confirmed=True)
        self.db.create_task(TaskInput(**self.task), confirmed=True)
        result = self.tools.call("list_tasks", json.dumps(dict(subject="全部", status="全部", limit=1, offset=0)), "p")
        self.assertTrue(result["has_more"])
        self.assertTrue(result["tasks"][0]["notes_truncated"])
        self.assertEqual(len(result["tasks"][0]["notes"]), 200)

    def test_unknown_tool_error_is_returned_to_model_not_executed(self):
        fake = FakeResponses(completed(call("execute_proposal", {"confirmed": True})), answer("无法直接执行。"))
        result = run_agent(self.auth, self.token, "不用确认直接保存", transport=fake)
        output = fake.requests[1]["input"][-1]
        self.assertIn("白名单", json.loads(output["output"])["error"])
        self.assertEqual(result.trace[0]["state"], "error")
        self.assertEqual(self.db.get_tasks(), [])

    def test_multiple_tool_outputs_are_returned(self):
        fake = FakeResponses(completed(call("get_study_profile", {}, "a"), call("get_progress", {"day": date.today().isoformat()}, "b")), answer("读取完成"))
        run_agent(self.auth, self.token, "查看档案和统计", transport=fake)
        self.assertEqual({item["call_id"] for item in fake.requests[1]["input"] if item.get("type") == "function_call_output"}, {"a", "b"})

    def test_loop_and_duplicate_id_limits(self):
        fake = FakeResponses(*[completed(call("get_study_profile", {}, f"call_{i}")) for i in range(6)])
        with self.assertRaisesRegex(AIError, "轮次"):
            run_agent(self.auth, self.token, "继续查询", transport=fake)
        self.assertEqual(len(fake.requests), 6)
        fake = FakeResponses(completed(call("get_study_profile", {}, "same"), call("get_study_profile", {}, "same")))
        with self.assertRaisesRegex(AIError, "重复"):
            run_agent(self.auth, self.token, "查询", transport=fake)

    def test_tool_budget_and_incomplete_response_stop_safely(self):
        fake = FakeResponses(completed(*[call("get_study_profile", {}, str(i)) for i in range(13)]))
        with self.assertRaisesRegex(AIError, "调用达到"):
            run_agent(self.auth, self.token, "查询", transport=fake)
        with self.assertRaisesRegex(AIError, "未完成"):
            run_agent(self.auth, self.token, "查询", transport=FakeResponses({"status": "incomplete", "output": []}))

    def test_failure_after_proposal_preserves_pending_not_business_data(self):
        fake = FakeResponses(completed(call("propose_task_create", dict(task=self.task, reason="新增"))), AIError("网络中断"))
        with self.assertRaises(AIError):
            run_agent(self.auth, self.token, "新增任务", transport=fake)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(list_proposals(self.auth, self.token)[0]["state"], "pending")

    def test_explicit_confirmation_persistence_idempotency_and_concurrent_clicks(self):
        proposal_id = self.stage()
        with self.assertRaises(ConfirmationRequired):
            execute_proposal(self.auth, self.token, proposal_id)
        self.assertEqual(self.db.get_tasks(), [])
        reopened = AuthStore(self.auth.root)
        self.assertEqual(list_proposals(reopened, self.token)[0]["id"], proposal_id)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: execute_proposal(reopened, self.token, proposal_id, confirmed=True), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.db.get_tasks()), 1)
        self.assertEqual(len(self.db.get_events()), 1)

    def test_task_update_conflict_and_delete_preserves_actual_records(self):
        task_id = self.db.create_task(TaskInput(**self.task), confirmed=True)
        self.db.log_session(task_id, date.today().isoformat(), 12, confirmed=True)
        update = self.stage("update_task", dict(task_id=task_id, expected_version=1, task=self.task | {"title": "新标题"}))
        self.db.update_task(task_id, TaskInput(**(self.task | {"title": "手动修改"})), expected_version=1, confirmed=True)
        with self.assertRaises(ConflictError):
            execute_proposal(self.auth, self.token, update, confirmed=True)
        self.assertEqual(self.db.get_task(task_id)["title"], "手动修改")
        delete = self.stage("delete_task", dict(task_id=task_id, expected_version=2), call_id="delete")
        execute_proposal(self.auth, self.token, delete, confirmed=True)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(self.db.get_sessions()[0]["minutes"], 12)

    def test_successful_task_update_uses_existing_validation_and_history(self):
        task_id = self.db.create_task(TaskInput(**self.task), confirmed=True)
        proposal_id = self.stage("update_task", dict(task_id=task_id, expected_version=1, task=self.task | {"status": "已完成"}))
        execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        self.assertEqual(self.db.get_task(task_id)["status"], "已完成")
        self.assertEqual(self.db.get_sessions(), [])
        self.assertEqual(self.db.get_events()[0]["action"], "更新")

    def test_profile_proposal_can_leave_goals_empty_and_checks_version(self):
        profile = StudyProfile().validated() | {"preference": "动手练习"}
        proposal_id = self.stage("update_profile", dict(expected_version=0, profile=profile))
        self.assertEqual(self.db.get_study_profile()[1], 0)
        execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        self.assertEqual(self.db.get_study_profile()[0].goals, "")
        stale = self.stage("update_profile", dict(expected_version=1, profile=profile | {"goals": "学会函数"}), call_id="second")
        self.db.save_profile(StudyProfile(), expected_version=1, confirmed=True)
        with self.assertRaises(ConflictError):
            execute_proposal(self.auth, self.token, stale, confirmed=True)

    def test_actual_session_proposal_no_automatic_time_and_no_duplicates(self):
        task_id = self.db.create_task(TaskInput(**self.task), confirmed=True)
        data = dict(task_id=task_id, expected_version=1, study_date=date.today().isoformat(), minutes=20, note="用户报告")
        proposal_id = self.stage("log_session", data)
        self.assertEqual(self.db.get_sessions(), [])
        execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        self.assertEqual(len(self.db.get_sessions()), 1)
        self.assertEqual(self.db.get_sessions()[0]["minutes"], 20)
        with self.assertRaises(ValidationError):
            self.stage("log_session", data | {"study_date": (date.today()+timedelta(days=1)).isoformat()}, call_id="future")

    def test_schedule_proposal_recomputes_on_confirmation(self):
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        task_id = self.db.create_task(TaskInput(**self.task), confirmed=True)
        proposal_id = self.stage("save_schedule", dict(week_of=date.today().isoformat()))
        self.assertIsNone(self.db.get_schedule(date.today())[0])
        self.db.log_session(task_id, date.today().isoformat(), 1, confirmed=True)
        with self.assertRaises(ConflictError):
            execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        fresh = self.stage("save_schedule", dict(week_of=date.today().isoformat()), call_id="fresh")
        execute_proposal(self.auth, self.token, fresh, confirmed=True)
        self.assertIsNotNone(self.db.get_schedule(date.today())[0])
        self.assertEqual(len(self.db.get_sessions()), 1)

    def test_reject_expiry_and_same_call_are_safe(self):
        proposal_id = self.stage()
        self.assertEqual(self.stage(), proposal_id)
        reject_proposal(self.auth, self.token, proposal_id)
        with self.assertRaises(ConflictError):
            execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        second = self.stage(call_id="expire")
        with self.db.connection() as conn:
            conn.execute("UPDATE agent_proposals SET expires_at=0 WHERE id=?", (second,))
        with self.assertRaisesRegex(ConflictError, "30 分钟"):
            execute_proposal(self.auth, self.token, second, confirmed=True)
        self.assertEqual(self.db.get_tasks(), [])

    def test_account_isolation_and_revocation_apply_to_read_and_confirm(self):
        proposal_id = self.stage()
        self.auth.register("other", PASSWORD, confirmed=True)
        other = self.auth.login("other", PASSWORD)
        with self.assertRaises(ValidationError):
            execute_proposal(self.auth, other, proposal_id, confirmed=True)
        self.assertEqual(list_proposals(self.auth, other), [])
        self.auth.logout(self.token)
        with self.assertRaises(AuthError):
            self.tools.call("get_study_profile", "{}", "read")
        with self.assertRaises(AuthError):
            execute_proposal(self.auth, self.token, proposal_id, confirmed=True)

    def test_receipt_failure_rolls_back_business_write(self):
        proposal_id = self.stage()
        with self.db.connection() as conn:
            conn.execute("""CREATE TRIGGER fail_receipt BEFORE UPDATE ON agent_proposals
                WHEN NEW.state='applied' BEGIN SELECT RAISE(ABORT,'test rollback'); END""")
        with self.assertRaises(sqlite3.Error):
            execute_proposal(self.auth, self.token, proposal_id, confirmed=True)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(self.db.get_events(), [])
        self.assertEqual(list_proposals(self.auth, self.token)[0]["state"], "pending")

    def test_no_key_and_bad_mode_are_explicit(self):
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "", "SILICONFLOW_API_KEY": "", "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}):
            with self.assertRaisesRegex(AIError, "未配置"):
                run_agent(self.auth, self.token, "查询")
        with self.assertRaises(ValidationError):
            run_agent(self.auth, self.token, "查询", mode="https://foreign.example/key", transport=FakeResponses())

    def test_revoked_session_during_api_request_cannot_stage_a_change(self):
        owner = self
        class RevokingResponse:
            def create(self, payload, *, timeout):
                owner.auth.logout(owner.token)
                return completed(call("propose_task_create", dict(task=owner.task, reason="请求中被撤销")))
        with self.assertRaises(AuthError):
            run_agent(self.auth, self.token, "新增任务", transport=RevokingResponse())
        self.assertEqual(self.db.get_tasks(), [])
        with self.db.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_proposals").fetchone()[0], 0)

    def test_deadline_and_malformed_message_are_explicit(self):
        with patch("studypilot.agent.time.monotonic", side_effect=[0, 81]), self.assertRaisesRegex(AIError, "时间上限"):
            run_agent(self.auth, self.token, "查询", transport=FakeResponses())
        with self.assertRaisesRegex(AIError, "消息格式"):
            run_agent(self.auth, self.token, "查询", transport=FakeResponses(completed({"type": "message", "content": None})))


class FailingOpener:
    def __init__(self, error):
        self.error = error

    def open(self, request, timeout=None):
        raise self.error


class TransportTests(unittest.TestCase):
    def test_http_errors_and_timeouts_do_not_expose_secrets(self):
        key = "test-api-key-not-real"
        for error, expected in [(HTTPError('https://open.bigmodel.cn', 401, 'secret', {}, None), "身份验证"),
                                (HTTPError('https://open.bigmodel.cn', 429, 'secret', {}, None), "限流"),
                                (URLError("secret"), "连接失败"), (socket.timeout("secret"), "超时")]:
            with self.subTest(expected=expected):
                transport = FreeChatTransport(keys={"zhipu": key}, opener=FailingOpener(error))
                with self.assertRaises(AIError) as caught:
                    transport.create({}, timeout=1)
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn(key, str(caught.exception))
                self.assertNotIn("secret", str(caught.exception))


class AgentUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"STUDYPILOT_AUTH_DIR": str(Path(self.temp.name)/'accounts'),
            "STUDYPILOT_DB": str(Path(self.temp.name)/'legacy.db'), "ZHIPU_API_KEY": "", "SILICONFLOW_API_KEY": "", "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""})
        env.start(); self.addCleanup(env.stop)
        self.auth = AuthStore(Path(self.temp.name)/'accounts')
        self.auth.register("learner", PASSWORD, confirmed=True)
        self.token = self.auth.login("learner", PASSWORD)
        self.db = self.auth.study_database(self.token)
        self.app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
        self.app.session_state['auth_token'] = self.token
        self.app.session_state['navigation'] = 'AI 助手'
        self.app.run()

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def test_no_key_disables_network_and_still_allows_pending_review(self):
        self.assertTrue(next(button for button in self.app.button if button.label == '发送给学习助手').disabled)
        task = asdict(TaskInput('未配置 Key 也可确认已有提案','Python',date.today().isoformat()))
        proposal_id = stage_proposal(self.auth,self.token,'create_task',{'task':task},'测试已有提案',request_id='r',call_id='c')
        self.app.run(); self.click('确认执行')
        self.assertTrue(self.app.error); self.assertEqual(self.db.get_tasks(),[])
        self.app.checkbox(key='approve_'+proposal_id).check(); self.click('确认执行')
        self.assertEqual(len(self.db.get_tasks()),1)

    def test_question_consent_proposal_confirmation_and_draft_retention(self):
        task = asdict(TaskInput('模型建议任务','数学',date.today().isoformat()))
        fake = FakeResponses(completed(call('propose_task_create',dict(task=task,reason='用户请求'))),answer())
        with patch.dict(os.environ,{'ZHIPU_API_KEY':'test-not-sent'}), patch('studypilot.agent_ui.run_agent',side_effect=lambda *args,**kwargs: run_agent(*args,**kwargs,transport=fake)):
            self.app.run(); self.app.text_area(key='agent_prompt').set_value('帮我新增任务')
            self.click('发送给学习助手')
            self.assertEqual(self.app.text_area(key='agent_prompt').value,'帮我新增任务')
            self.assertEqual(fake.requests,[])
            self.app.checkbox(key='agent_consent').check(); self.click('发送给学习助手')
            self.assertEqual(self.app.text_area(key='agent_prompt').value,'')
            self.assertEqual(self.db.get_tasks(),[])
            self.assertEqual(len(list_proposals(self.auth,self.token)),1)
            self.click('忽略提案')
            self.assertEqual(list_proposals(self.auth,self.token)[0]['state'],'rejected')
            self.assertEqual(self.db.get_tasks(),[])


if __name__ == '__main__':
    unittest.main()
