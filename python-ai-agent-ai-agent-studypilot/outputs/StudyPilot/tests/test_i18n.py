"""English HTTP and model contracts, with disposable accounts and mocked models."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from studypilot.agent import run_agent
from studypilot.auth import AuthStore
from studypilot.i18n import error_text, request_language
from studypilot.models import StudyProfile, TaskInput
from studypilot.web import create_app

PASSWORD = "Temporary bilingual testing password 2026"


class LanguageTests(unittest.TestCase):
    def test_weighted_language_negotiation(self):
        for header, expected in (("en-US,en;q=0.9,zh;q=0.5", "en"),
                                 ("en;q=0.2,zh-CN;q=0.8", "zh-CN"),
                                 ("en;q=0,zh;q=1", "zh-CN"),
                                 ("fr,en-GB;q=0.8", "en"), ("fr", "zh-CN")):
            request = Request({"type": "http", "headers": [(b"accept-language", header.encode())]})
            self.assertEqual(request_language(request), expected)

    def test_dynamic_errors_are_localized_without_echoing_unknown_data(self):
        self.assertEqual(error_text("周一有可用时间，请至少选择一种设备。", "en"),
                         "Choose at least one device for Monday, or set its available time to zero.")
        self.assertIn("120", error_text("任务标题最多 120 字。", "en"))
        self.assertNotIn("private-user-content", error_text("未知错误 private-user-content", "en"))
        self.assertEqual(error_text("原始提示", "zh-CN"), "原始提示")


class EnglishWebTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.auth = AuthStore(Path(temp.name)/"accounts")
        self.auth.register("English learner", PASSWORD, confirmed=True)
        self.client = TestClient(create_app(lambda: self.auth))
        self.addCleanup(self.client.close)
        login = self.client.post("/api/login", json={"username": "English learner", "password": PASSWORD},
                                 headers={"origin": "http://testserver", "accept-language": "en-US"})
        self.headers = {"origin": "http://testserver", "accept-language": "en", "x-csrf-token": login.json()["csrf"]}

    def test_english_errors_keep_authentication_and_csrf(self):
        response = self.client.post("/api/tasks", json={}, headers={"accept-language": "en"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("origin", response.json()["error"])
        response = self.client.post("/api/tasks", json={}, headers={"origin": "http://testserver", "accept-language": "en"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("token", response.json()["detail"])
        self.client.cookies.clear()
        response = self.client.get("/api/me", headers={"accept-language": "en"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("sign in", response.json()["error"])
        self.assertEqual(response.headers["content-language"], "en")

    def test_english_registration_errors_do_not_echo_credentials(self):
        response = self.client.post("/api/register", json={"username": "new English user", "password": "short",
                                    "password_again": "short", "confirmed": True}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("15–128", response.json()["error"])
        self.assertNotIn("short", response.text)

    def test_english_draft_is_not_saved_and_canonical_options_stay_unchanged(self):
        english = self.client.get("/api/state", headers=self.headers).json()
        chinese = self.client.get("/api/state", headers={"accept-language": "zh-CN"}).json()
        self.assertEqual(english["profile_version"], 0)
        self.assertIn("English explanations", english["profile"]["preference"])
        self.assertEqual(chinese["profile"]["preference"], StudyProfile().preference)
        options = self.client.get("/api/me", headers=self.headers).json()["options"]
        self.assertIn("数学", options["subjects"])

    def test_language_never_rewrites_user_text_or_bypasses_confirmation(self):
        payload = asdict(TaskInput("学习目标 / Keep my exact title", "数学", date.today().isoformat()))
        response = self.client.post("/api/tasks", json={"task": payload, "confirmed": False}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("checkbox", response.json()["error"])
        self.assertEqual(self.client.get("/api/state", headers=self.headers).json()["tasks"], [])
        response = self.client.post("/api/tasks", json={"task": payload, "confirmed": True}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        for language in ("en", "zh-CN"):
            task = self.client.get("/api/state", headers={"accept-language": language}).json()["tasks"][0]
            self.assertEqual(task["title"], payload["title"])
            self.assertEqual(task["subject"], "数学")

    def test_provider_failure_categories_are_explained_without_echoing_unknown_text(self):
        from studypilot.i18n import error_text
        message="AI 服务暂时不可用（智谱 GLM-4.7-Flash 限流、硅基流动 Xing4.0-29B 超时），请稍后重试；已有建议仍需你核对确认。"
        text=error_text(message,"en")
        self.assertIn("rate limit",text)
        self.assertIn("timeout",text)
        message="AI 服务暂时不可用（private upstream detail），请稍后重试；已有建议仍需你核对确认。"
        self.assertNotIn("private upstream detail",error_text(message,"en"))
        for category, expected in (("模型繁忙", "model busy"),
                ("账号额度或余额受限", "account quota or balance restriction"),
                ("账号权限或套餐受限", "account access restriction")):
            message=f"AI 服务暂时不可用（智谱 GLM-4.7-Flash {category}），请稍后重试；已有建议仍需你核对确认。"
            self.assertIn(expected, error_text(message, "en"))

    def test_ai_language_is_validated_and_consent_is_required(self):
        with patch("studypilot.web.run_agent") as agent:
            for payload, status in (({"prompt": "Hello", "language": "en", "consent": False}, 400),
                                    ({"prompt": "Hello", "language": "arbitrary", "consent": True}, 422)):
                response = self.client.post("/api/agent", json=payload, headers=self.headers)
                self.assertEqual(response.status_code, status)
            agent.assert_not_called()

    def test_mocked_agent_uses_english_and_keeps_writes_as_proposals(self):
        token = self.auth.login("English learner", PASSWORD)
        transport = Mock()
        transport.create.return_value = {"status": "completed", "output": [{"type": "message", "role": "assistant",
                                             "content": [{"type": "output_text", "text": "Let's review your goals."}]}]}
        result = run_agent(self.auth, token, "Help me study", language="en", transport=transport)
        self.assertEqual(result.text, "Let's review your goals.")
        instructions = transport.create.call_args.args[0]["instructions"]
        self.assertIn("Respond in English", instructions)
        self.assertIn("canonical enum values", instructions)
        self.assertIn("提案", instructions)
        self.assertEqual(self.auth.study_database(token).get_tasks(), [])
        with patch("studypilot.web.run_agent", return_value=result) as agent:
            response = self.client.post("/api/agent", json={"prompt": "Hello", "language": "en", "consent": True}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(agent.call_args.kwargs["language"], "en")


if __name__ == "__main__":
    unittest.main()
