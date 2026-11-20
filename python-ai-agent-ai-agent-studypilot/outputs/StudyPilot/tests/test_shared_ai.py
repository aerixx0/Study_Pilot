import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from studypilot.ai import FreeChatTransport, RELAY_PROVIDERS
from studypilot.auth import AuthStore
from studypilot.web import create_app


class SharedAI(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.auth = AuthStore(root)
        self.auth.register("shared-ai", "test password only", confirmed=True)
        self.web = self.enterContext(TestClient(create_app(lambda: self.auth)))
        self.env = self.enterContext(patch.dict(os.environ, {
            "STUDYPILOT_SHARED_AI": "1",
            "STUDYPILOT_AI_ENABLED": "1",
            "STUDYPILOT_AI_USER_LIMIT": "2",
            "CLOUDFLARE_ACCOUNT_ID": "1" * 32,
            "CLOUDFLARE_API_TOKEN": "synthetic",
        }))
        self.headers = {"Origin": "http://testserver"}
        response = self.web.post("/api/login", headers=self.headers,
                                 json={"username": "shared-ai", "password": "test password only"})
        self.assertEqual(response.status_code, 200, response.text)
        self.headers["X-CSRF-Token"] = response.json()["csrf"]
        self.machine = self.enterContext(TestClient(create_app(lambda: self.auth)))

    def issue(self):
        response = self.web.post("/api/desktop-ai/issue", headers=self.headers, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["code"]

    def test_one_time_code_scoped_bearer_and_shared_quota(self):
        code = self.issue()
        url = "/api/desktop-ai/exchange"
        response = self.machine.post(url, json={"code": code})
        self.assertEqual(response.status_code, 200, response.text)
        bearer = {"Authorization": "Bearer " + response.json()["token"]}
        self.assertEqual(self.machine.post(url, json={"code": code}).status_code, 401)
        self.assertEqual(self.machine.get("/api/me", headers=bearer).status_code, 401)

        payload = {"family": "qwen", "payload": {"instructions": "Test instructions",
                   "input": [{"role": "user", "content": "Hi"}], "max_output_tokens": 128,
                   "tools": [{"name": "list_tasks", "description": "untrusted"}, {"name": "fake"}]}}
        url = "/api/desktop-ai/infer"
        with patch.object(FreeChatTransport, "create", autospec=True, return_value={"status": "completed", "output": []}) as call:
            self.assertEqual(self.machine.post(url, json=payload).status_code, 401)
            self.assertEqual(self.machine.post(url, headers=bearer, json=payload).status_code, 200)
            self.assertEqual(call.call_args.args[0]._family, "qwen")
            tools = call.call_args.args[1]["tools"]
            self.assertEqual([t["name"] for t in tools], ["list_tasks"])
            self.assertNotEqual(tools[0]["description"], "untrusted")
            session = self.web.cookies["studypilot_session"]
            self.auth.ai_meter().reserve(session)
            self.assertEqual(self.machine.post(url, headers=bearer, json=payload).status_code, 429)
            self.assertEqual(call.call_count, 1)
            revoked = self.web.post("/api/desktop-ai/revoke", headers=self.headers, json={"confirmed": True})
            self.assertEqual(revoked.status_code, 200)
            self.assertEqual(self.machine.post(url, headers=bearer, json=payload).status_code, 401)

    def test_fresh_desktop_without_keys_uses_both_relay_models(self):
        os.environ["CLOUDFLARE_API_TOKEN"] = ""
        with patch("studypilot.ai.model_ready", return_value=False), patch("studypilot.ai.local_credentials", return_value={}):
            self.assertEqual(FreeChatTransport(local=True, relay_token="local-device").available(),
                             [(provider, "local-device") for provider in RELAY_PROVIDERS.values()])
