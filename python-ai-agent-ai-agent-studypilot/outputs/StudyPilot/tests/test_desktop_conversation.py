from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from studypilot.agent import AgentResult
from studypilot.auth import LocalAuthStore
from studypilot.desktop_conversation import ConversationHandoff
from studypilot.web import create_app


class DesktopConversationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.auth = LocalAuthStore(Path(directory) / "accounts")
        self.auth.register("desktop-test", "Ab12cd", confirmed=True)
        self.session = self.auth.login("desktop-test", "Ab12cd")
        self.handoff = ConversationHandoff(8508)
        app = create_app(lambda: self.auth, desktop_handoff=self.handoff)
        self.client = self.enterContext(TestClient(app, base_url=self.handoff.url))

    def test_handoff_preserves_account_and_redeems_once(self):
        link = self.handoff.issue(self.session)
        self.assertNotIn(self.session, link)
        response = self.client.get(link, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/conversation")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(self.client.get("/api/me").json()["account"]["username"], "desktop-test")
        self.client.cookies.clear()
        replay = self.client.get(link, follow_redirects=False)
        self.assertNotIn("set-cookie", replay.headers)
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_desktop_only_routes_reuse_web_assets(self):
        page = self.client.get("/conversation")
        site = self.client.get("/")
        self.assertEqual(page.text.replace('  <script src="/desktop-entry.js" defer></script>\n', ""),
                         site.text.replace("\r\n", "\n"))
        self.assertIn('page = "assistant"', self.client.get("/desktop-entry.js").text)
        root = Path(__file__).resolve().parents[1] / "public"
        for name in ("study.css", "study.js", "motion.js", "workflow.js", "i18n.js"):
            self.assertEqual(self.client.get(f"/{name}").content, (root / name).read_bytes())
        self.assertTrue(self.client.get("/api/health").json()["database_configured"])
        public = TestClient(create_app(lambda: self.auth))
        self.assertEqual(public.get("/conversation").status_code, 404)
        self.assertEqual(public.get("/desktop-login").status_code, 404)

    def test_desktop_chat_preserves_consent_and_uses_local_transport(self):
        self.client.get(self.handoff.issue(self.session))
        identity = self.client.get("/api/me").json()
        headers = {"origin": self.handoff.url, "x-csrf-token": identity["csrf"]}
        with patch("studypilot.web.run_agent", return_value=AgentResult("本机答复", [], [], 1)) as agent:
            response = self.client.post("/api/agent", headers=headers, json={"prompt": "你好"})
            self.assertEqual(response.status_code, 400)
            agent.assert_not_called()
            response = self.client.post("/api/agent", headers=headers, json={"prompt": "你好", "consent": True})
        self.assertEqual(response.json()["text"], "本机答复")
        self.assertTrue(agent.call_args.kwargs["local"])
