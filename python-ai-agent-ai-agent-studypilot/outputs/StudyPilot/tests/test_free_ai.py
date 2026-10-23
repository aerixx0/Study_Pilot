"""免费国产模型接入的离线测试：适配器、故障切换、额度、模式与确认边界。

全部用假的 HTTP 层和临时 SQLite，不联网、不消耗真实免费额度。
"""

from dataclasses import asdict
from datetime import date
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from studypilot.agent import AIError, run_agent
from studypilot.ai import BACKUP, PRIMARY, FreeChatTransport, chat_messages, chat_payload, completion_output
from studypilot.auth import AuthError, AuthStore
from studypilot.database import ConfirmationRequired
from studypilot.models import StudyProfile, TaskInput, ValidationError
from studypilot.proposals import execute_proposal, list_proposals, stage_proposal
from studypilot.quota import QuotaExceeded
from studypilot.web import create_app

PASSWORD = "Temporary free model testing phrase 2026"
KEYS = {"zhipu": "test-zhipu-key-value", "siliconflow": "test-siliconflow-key-value"}


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def read(self, size=-1):
        return self.raw[:size] if size >= 0 else self.raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """按顺序返回预设响应或异常，并记录真正发出的请求。"""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "timeout": timeout,
                              "market": dict(request.headers), "body": json.loads(request.data)})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer if isinstance(answer, bytes) else json.dumps(answer, ensure_ascii=False).encode("utf-8"))


def completion(text=None, tool_calls=None):
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "chatcmpl-test", "object": "chat.completion",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def function_call(name, arguments, call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def http_error(code):
    return HTTPError("https://open.bigmodel.cn/api/paas/v4/chat/completions", code, "opaque upstream text", {}, None)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = AuthStore(Path(self.temp.name) / "accounts")
        self.auth.register("learner", PASSWORD, confirmed=True)
        self.token = self.auth.login("learner", PASSWORD)
        self.db = self.auth.study_database(self.token)
        self.task = asdict(TaskInput("复习数学", "数学", date.today().isoformat(), 30))
        env = patch.dict(os.environ, {"ZHIPU_API_KEY": "", "SILICONFLOW_API_KEY": "",
                                      "STUDYPILOT_AI_USER_LIMIT": "", "STUDYPILOT_AI_SITE_LIMIT": "",
                                      "STUDYPILOT_AI_WINDOW_SECONDS": ""})
        env.start()
        self.addCleanup(env.stop)

    def chat(self, *answers, keys=None):
        opener = FakeOpener(*answers)
        transport = FreeChatTransport(keys=KEYS if keys is None else keys, opener=opener)
        return opener, transport


class ProviderTests(Base):
    def test_failed_primary_is_not_retried_in_later_tool_round(self):
        opener, transport = self.chat(http_error(429), completion(tool_calls=[function_call("get_study_profile", {})]),
                                      completion("已读取，未修改。"))
        run_agent(self.auth, self.token, "看看档案", transport=transport)
        self.assertEqual([r["body"]["model"] for r in opener.requests], [PRIMARY.model, BACKUP.model, BACKUP.model])

    def test_fallback_shares_deadline_and_does_not_retry_auth_or_invalid_output(self):
        clock = [0.0]
        opener, transport = self.chat(http_error(429), completion("备用答复"))
        original = opener.open
        def timed_open(request, timeout):
            result = None
            try:
                result = original(request, timeout)
            finally:
                clock[0] += 7
            return result
        opener.open = timed_open
        transport._clock = lambda: clock[0]
        transport.create({}, timeout=20)
        self.assertEqual([r["timeout"] for r in opener.requests], [12, 13])
        for failure in (http_error(401), http_error(400),
                        {"choices": [{"finish_reason": "length", "message": {"content": "截断"}}]},
                        completion(tool_calls=[{"function": {"name": "get_study_profile", "arguments": "{}"}}])):
            with self.subTest(failure=type(failure).__name__):
                opener, transport = self.chat(failure, completion("不应该自动切换"))
                with self.assertRaises(AIError):
                    transport.create({}, timeout=20)
                self.assertEqual(len(opener.requests), 1)

    def test_only_free_allowlist_even_with_paid_environment_settings(self):
        opener, transport = self.chat(completion("好的"))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "never-use", "OPENAI_MODEL": "paid-model",
                                     "OPENAI_BASE_URL": "https://untrusted.example"}):
            run_agent(self.auth, self.token, "查询", transport=transport)
        self.assertEqual(opener.requests[0]["body"]["model"], PRIMARY.model)
        self.assertEqual(opener.requests[0]["url"], PRIMARY.base_url + "/chat/completions")
        with patch.dict(os.environ, {"STUDYPILOT_AI_ENABLED": "0"}):
            with self.assertRaisesRegex(AIError, "暂停"):
                transport.create({}, timeout=1)

    def test_primary_model_is_used_and_addresses_are_fixed(self):
        opener, transport = self.chat(completion("本周没有记录，先从一个小任务开始。"))
        result = run_agent(self.auth, self.token, "看看本周情况", transport=transport)
        self.assertEqual(result.rounds, 1)
        self.assertIn("先从一个小任务开始", result.text)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0]["url"], "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(opener.requests[0]["body"]["model"], "glm-4.7-flash")
        self.assertEqual(opener.requests[0]["market"]["Authorization"], "Bearer " + KEYS["zhipu"])
        self.assertFalse(opener.requests[0]["body"]["stream"])

    def test_request_payload_is_translated_and_never_carries_secrets(self):
        opener, transport = self.chat(completion("好的。"))
        run_agent(self.auth, self.token, "看看任务", history=[{"role": "user", "content": "早先的问题"},
                                                            {"role": "assistant", "content": "早先的答复"}], transport=transport)
        body = opener.requests[0]["body"]
        self.assertEqual([message["role"] for message in body["messages"]], ["system", "user", "assistant", "user"])
        self.assertEqual(body["messages"][-1]["content"], "看看任务")
        self.assertEqual(body["max_tokens"], 1800)
        self.assertTrue(all(tool["type"] == "function" and "parameters" in tool["function"] for tool in body["tools"]))
        sent = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(self.token, sent)
        self.assertNotIn(PASSWORD, sent)
        self.assertNotIn(KEYS["zhipu"], sent)

    def test_rate_limit_falls_back_to_backup(self):
        opener, transport = self.chat(http_error(429), completion("备用模型答复。"))
        with self.assertLogs("studypilot.ai", level="INFO") as logs:
            result = run_agent(self.auth, self.token, "看看本周情况", transport=transport)
        self.assertEqual(result.text, "备用模型答复。")
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(opener.requests[1]["url"], "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(opener.requests[1]["body"]["model"], "XingChenAGI/Xing4.0-29B")
        self.assertEqual(opener.requests[1]["market"]["Authorization"], "Bearer " + KEYS["siliconflow"])
        joined = "\n".join(logs.output)
        self.assertIn("provider=zhipu", joined)
        self.assertIn("rate_limit", joined)
        self.assertNotIn(KEYS["zhipu"], joined)
        self.assertNotIn("看看本周情况", joined)

    def test_timeout_and_server_error_also_fall_back(self):
        for failure in (URLError(socket.timeout("timed out")), socket.timeout("timed out"), http_error(503)):
            with self.subTest(failure=type(failure).__name__):
                opener, transport = self.chat(failure, completion("备用答复。"))
                self.assertEqual(run_agent(self.auth, self.token, "查询", transport=transport).text, "备用答复。")
                self.assertEqual(len(opener.requests), 2)

    def test_both_providers_failing_returns_friendly_error_without_secrets(self):
        opener, transport = self.chat(http_error(429), http_error(503))
        with self.assertLogs("studypilot.ai", level="INFO") as logs:
            with self.assertRaises(AIError) as caught:
                run_agent(self.auth, self.token, "看看本周情况", transport=transport)
        message = str(caught.exception)
        self.assertIn("免费模型暂时不可用", message)
        self.assertIn("智谱", message)
        self.assertIn("硅基流动", message)
        self.assertNotIn(KEYS["zhipu"], message)
        self.assertNotIn("opaque upstream text", message)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(len(logs.output), 2)

    def test_only_configured_providers_are_attempted(self):
        opener, transport = self.chat(completion("只配了备用。"), keys={"siliconflow": KEYS["siliconflow"]})
        run_agent(self.auth, self.token, "查询", transport=transport)
        self.assertEqual(len(opener.requests), 1)
        self.assertTrue(opener.requests[0]["url"].startswith("https://api.siliconflow.cn/v1"))
        with self.assertRaisesRegex(AIError, "未配置"):
            run_agent(self.auth, self.token, "查询", transport=FreeChatTransport(keys={}, opener=FakeOpener()))
        self.assertEqual(list_proposals(self.auth, self.token), [])

    def test_no_redirect_handler_and_unknown_shapes(self):
        malformed = {"choices": [{"index": 0, "message": {"role": "assistant", "content": None}}]}
        with self.assertRaises(AIError):
            run_agent(self.auth, self.token, "查询", transport=FreeChatTransport(
                keys={"zhipu": KEYS["zhipu"]}, opener=FakeOpener(malformed, malformed)))
        for value in ({"choices": []}, {"choices": "x"}, {"error": {"code": 1302}}, {"choices": [{"message": 5}]}):
            with self.subTest(value=value), self.assertRaises(Exception):
                completion_output(value)

    def test_tool_messages_group_into_one_assistant_turn(self):
        payload = dict(instructions="系统说明", input=[
            {"role": "user", "content": "查询"},
            {"type": "reasoning", "id": "r1", "encrypted_content": "opaque"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "先读取档案。"}]},
            {"type": "function_call", "name": "get_study_profile", "arguments": "{}", "call_id": "a"},
            {"type": "function_call", "name": "get_progress", "arguments": "{}", "call_id": "b"},
            {"type": "function_call_output", "call_id": "a", "output": "{\"ok\":true}"},
            {"type": "function_call_output", "call_id": "b", "output": "{\"ok\":true}"},
        ], tools=[])
        messages = chat_messages(payload["input"], payload["instructions"])
        self.assertEqual(messages[0], {"role": "system", "content": "系统说明"})
        self.assertEqual(messages[2]["role"], "assistant")
        self.assertEqual(messages[2]["content"], "先读取档案。")
        self.assertEqual([call["id"] for call in messages[2]["tool_calls"]], ["a", "b"])
        self.assertEqual([message["role"] for message in messages[3:]], ["tool", "tool"])
        self.assertNotIn("reasoning", json.dumps(messages))
        body = chat_payload(PRIMARY, dict(input=[{"role": "user", "content": "hi"}], tools=[], max_output_tokens=9999))
        self.assertEqual(body["max_tokens"], 1800)
        self.assertEqual(body["model"], PRIMARY.model)


class BusinessTests(Base):
    def test_goal_proposal_is_only_a_pending_suggestion(self):
        profile = StudyProfile(goals="我想先学好数学").validated()
        opener, transport = self.chat(completion(tool_calls=[function_call(
            "propose_profile_update", {"expected_version": 0, "profile": profile, "reason": "用户想改目标"})]),
            completion("尚未执行，请在下方核对并确认。"))
        result = run_agent(self.auth, self.token, "帮我把目标改成学好数学", mode="goal_coach", transport=transport)
        self.assertEqual(result.trace, [{"tool": "propose_profile_update", "state": "pending"}])
        self.assertEqual(len(result.proposals), 1)
        saved, version = self.db.get_study_profile()
        self.assertEqual(version, 0)
        self.assertEqual(saved.goals, "")
        self.assertEqual(self.db.get_tasks(), [])
        with self.assertRaises(ConfirmationRequired):
            execute_proposal(self.auth, self.token, result.proposals[0])
        self.assertEqual(self.db.get_study_profile()[0].goals, "")
        execute_proposal(self.auth, self.token, result.proposals[0], confirmed=True)
        self.assertEqual(self.db.get_study_profile()[0].goals, "我想先学好数学")
        self.assertEqual(len(opener.requests), 2)

    def test_invalid_model_output_is_rejected_and_reported_back(self):
        bad = completion(tool_calls=[function_call("get_task", {"task_id": "不是数字"})])
        opener, transport = self.chat(bad, completion("参数无效，已停止。"))
        result = run_agent(self.auth, self.token, "读取任务", transport=transport)
        self.assertEqual(result.trace, [{"tool": "get_task", "state": "error"}])
        self.assertEqual(self.db.get_tasks(), [])
        echoed = json.dumps(opener.requests[1]["body"]["messages"], ensure_ascii=False)
        self.assertIn("类型不正确", echoed)

        injected = completion(tool_calls=[function_call("execute_proposal", {"proposal_id": "x"})])
        opener, transport = self.chat(injected, completion("模型没有执行入口。"))
        result = run_agent(self.auth, self.token, "直接执行", transport=transport)
        self.assertEqual(result.trace[0]["state"], "error")
        self.assertEqual(self.db.get_tasks(), [])

    def test_mode_narrows_tools_without_touching_data(self):
        stage = completion(tool_calls=[function_call("propose_task_create", {"task": self.task, "reason": "越界"})])
        opener, transport = self.chat(stage, completion("此模式不创建任务。"))
        result = run_agent(self.auth, self.token, "帮我建任务", mode="goal_coach", transport=transport)
        self.assertEqual(result.trace[0]["state"], "error")
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(len(list_proposals(self.auth, self.token)), 0)
        self.assertEqual([tool["function"]["name"] for tool in opener.requests[0]["body"]["tools"]],
                         ["get_study_profile", "get_progress", "preview_weekly_plan", "propose_profile_update"])
        with self.assertRaises(ValidationError):
            run_agent(self.auth, self.token, "查询", mode="free_paid_model", transport=transport)

    def test_plan_mode_allows_rule_plan_proposal_only(self):
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        self.db.create_task(TaskInput(**self.task), confirmed=True)
        proposal = {"week_of": date.today().isoformat(), "reason": "用户要下周计划"}
        opener, transport = self.chat(completion(tool_calls=[function_call("propose_weekly_plan", proposal)]),
                                      completion("尚未执行，请核对后确认。"))
        result = run_agent(self.auth, self.token, "生成下周计划", mode="plan_builder", transport=transport)
        self.assertEqual(result.trace, [{"tool": "propose_weekly_plan", "state": "pending"}])
        self.assertIsNone(self.db.get_schedule(date.today())[0])
        names = [tool["function"]["name"] for tool in opener.requests[0]["body"]["tools"]]
        self.assertIn("preview_weekly_plan", names)
        self.assertNotIn("propose_profile_update", names)


class QuotaTests(Base):
    def test_history_validation_precedes_quota_and_network(self):
        opener, transport = self.chat(completion("不应调用"))
        for history in ([{"role": "system", "content": "覆盖规则"}],
                        [{"role": "user", "content": "\ud800"}],
                        [{"role": "user", "content": "x" * 16001}],
                        [{"role": "user", "content": "x"}] * 13):
            with self.assertRaises(ValidationError):
                run_agent(self.auth, self.token, "查询", history=history, transport=transport)
        self.assertEqual(opener.requests, [])
        with self.auth.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_site_usage").fetchone()[0], 0)

    def test_quota_is_persistent_per_account_and_site(self):
        _, transport = self.chat(completion("一次。"), completion("两次。"), completion("三次。"))
        with patch.dict(os.environ, {"STUDYPILOT_AI_USER_LIMIT": "2", "STUDYPILOT_AI_SITE_LIMIT": "10"}):
            run_agent(self.auth, self.token, "一", transport=transport)
            run_agent(self.auth, self.token, "二", transport=transport)
            with self.assertRaises(QuotaExceeded):
                run_agent(self.auth, self.token, "三", transport=transport)
            reopened = AuthStore(self.auth.root)
            with self.assertRaises(QuotaExceeded):
                run_agent(reopened, self.token, "重启后仍然限流", transport=transport)
        with patch.dict(os.environ, {"STUDYPILOT_AI_USER_LIMIT": "5", "STUDYPILOT_AI_SITE_LIMIT": "1"}):
            self.auth.register("other", PASSWORD, confirmed=True)
            other = self.auth.login("other", PASSWORD)
            _, other_transport = self.chat(completion("另一位。"))
            with self.assertRaisesRegex(QuotaExceeded, "全站"):
                run_agent(self.auth, other, "查询", transport=other_transport)

    def test_unauthenticated_requests_are_refused_before_quota(self):
        _, transport = self.chat(completion("不应到达。"))
        with self.assertRaises(AuthError):
            run_agent(self.auth, "not-a-real-token", "查询", transport=transport)


class WebTests(Base):
    def setUp(self):
        super().setUp()
        self.app = create_app(lambda: self.auth)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        login = self.client.post("/api/login", json={"username": "learner", "password": PASSWORD},
                                 headers={"origin": "http://testserver"})
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"origin": "http://testserver", "x-csrf-token": login.json()["csrf"]}
        self.me = self.client.get("/api/me").json()

    def test_identity_reports_free_models_and_modes(self):
        self.assertFalse(self.me["ai_configured"])
        self.assertEqual(self.me["default_model"], "glm-4.7-flash")
        self.assertEqual(self.me["modes"]["values"], ["chat", "goal_coach", "plan_builder"])
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only"}):
            self.assertTrue(self.client.get("/api/me").json()["ai_configured"])

    def test_agent_requires_consent_and_ignores_client_model_and_address(self):
        self.assertEqual(self.call({"prompt": "看看本周情况"}).status_code, 400)
        opener = FakeOpener(completion("本周记录了 0 分钟。"))
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only"}), \
                patch("studypilot.ai.build_opener", lambda *handlers: opener):
            response = self.call({"prompt": "看看本周情况", "consent": True, "mode": "goal_coach",
                                  "model": "https://paid.example/v1/chat/completions"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], "本周记录了 0 分钟。")
        self.assertEqual(opener.requests[0]["url"], "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(opener.requests[0]["body"]["model"], PRIMARY.model)

    def test_unauthenticated_and_quota_exhausted_are_refused(self):
        anonymous = TestClient(create_app(lambda: self.auth))
        self.addCleanup(anonymous.close)
        refused = anonymous.post("/api/agent", json={"prompt": "查询", "consent": True},
                                 headers={"origin": "http://testserver", "x-csrf-token": "forged"})
        self.assertEqual(refused.status_code, 401)
        opener = FakeOpener(completion("第一次。"))
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only", "STUDYPILOT_AI_USER_LIMIT": "1"}), \
                patch("studypilot.ai.build_opener", lambda *handlers: opener):
            self.assertEqual(self.call({"prompt": "第一次", "consent": True}).status_code, 200)
            blocked = self.call({"prompt": "第二次", "consent": True})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("频繁", blocked.json()["error"])
        self.assertEqual(len(opener.requests), 1)

    def test_failed_upstream_returns_502_and_writes_nothing(self):
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only"}), \
                patch("studypilot.ai.build_opener", lambda *handlers: FakeOpener(http_error(429), http_error(500))):
            response = self.call({"prompt": "帮我新增任务", "consent": True, "mode": "chat"})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("免费模型暂时不可用", response.json()["error"])
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(list_proposals(self.auth, self.token), [])

    def test_server_revalidates_proposal_after_confirmation(self):
        proposal_id = stage_proposal(self.auth, self.token, "create_task", {"task": self.task},
                                    "网页测试", request_id="web", call_id="one")
        self.assertEqual(self.db.get_tasks(), [])
        executed = self.call({"confirmed": True}, path="/proposals/" + proposal_id + "/execute")
        self.assertEqual(executed.status_code, 200, executed.text)
        self.assertEqual(len(self.db.get_tasks()), 1)

    def call(self, body, path="/agent"):
        return self.client.post("/api" + path, json=body, headers=self.headers)


if __name__ == "__main__":
    unittest.main()
