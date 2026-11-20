import argparse
from contextlib import redirect_stdout
from datetime import date, timedelta
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from studypilot import cli
from studypilot.auth import AuthStore
from studypilot.local_data import backup_accounts, migrate_accounts
from studypilot.local_paths import LocalPaths
from studypilot.local_service import LocalService, ServiceError
from studypilot.models import StudyProfile, TaskInput
from studypilot.proposals import stage_proposal, list_proposals


class LocalCLITests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        self.paths = LocalPaths(home, home / "data" / "accounts")
        self.auth = AuthStore(self.paths.accounts)
        self.password = "Disposable-local-password"
        self.auth.register("test-local", self.password, confirmed=True)
        self.token = self.auth.login("test-local", self.password)
        self.db = self.auth.study_database(self.token)
        self.due = (date.today() + timedelta(days=12)).isoformat()
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))

    def test_cli_task_plan_and_record_share_account_storage(self):
        self.db.save_profile(StudyProfile(), expected_version=0, confirmed=True)
        parser = cli.make_parser()
        with patch.object(cli, "login", side_effect=lambda auth, user: auth.login(user, self.password)), \
                patch("builtins.input", return_value="y"):
            cli.study_action(self.paths, parser.parse_args(["task", "--user", "test-local", "add",
                                                            "--title", "练习", "--subject", "Python",
                                                            "--due", self.due]))
            task = self.db.get_tasks()[0]
            cli.study_action(self.paths, parser.parse_args(["task", "--user", "test-local", "edit",
                                                            str(task["id"]), "--status", "进行中"]))
            week = (date.today() + timedelta(days=7)).isoformat()
            cli.study_action(self.paths, parser.parse_args(["plan", "--user", "test-local", "save",
                                                            "--week", week]))
            cli.study_action(self.paths, parser.parse_args(["record", "--user", "test-local", "add",
                                                            str(task["id"]), "15"]))
        self.assertEqual(self.db.get_task(task["id"])["status"], "进行中")
        self.assertEqual(self.db.get_schedule(date.fromisoformat(week))[1], 1)
        self.assertEqual(self.db.get_sessions()[0]["minutes"], 15)

    def test_cli_ai_cancellation_keeps_proposal_pending_and_data_unchanged(self):
        task = TaskInput("AI 建议", "Python", self.due)
        proposal = stage_proposal(self.auth, self.token, "create_task", {"task": task.validated()}, "test",
                                  request_id="test-req", call_id="test-call")
        args = argparse.Namespace(action="apply", id=proposal)
        with patch("builtins.input", return_value=""):
            with self.assertRaises(ServiceError):
                cli.ai_action(self.auth, self.token, args)
        self.assertEqual(self.db.get_tasks(), [])
        self.assertEqual(list_proposals(self.auth, self.token)[0]["state"], "pending")
        with patch("builtins.input", return_value="y"):
            cli.ai_action(self.auth, self.token, args)
        self.assertEqual(len(self.db.get_tasks()), 1)

    def test_backup_and_migrate_preserve_accounts_and_refuse_overwrite(self):
        self.db.create_task(TaskInput("需要保留", "Python", self.due), confirmed=True)
        backup = backup_accounts(self.paths)
        target = LocalPaths(self.paths.home / "other", self.paths.home / "other" / "accounts")
        AuthStore(target.accounts)  # Browser may already have initialized an empty account store.
        migrate_accounts(target, backup)
        auth = AuthStore(target.accounts)
        db = auth.study_database(auth.login("test-local", self.password))
        self.assertEqual(db.get_tasks()[0]["title"], "需要保留")
        self.assertTrue((backup / "accounts.db").is_file())
        with self.assertRaises(ServiceError):
            migrate_accounts(target, self.paths.accounts)

    def test_settings_validate_preferred_port(self):
        service = LocalService(self.paths)
        self.assertIsNone(service.configured_port())
        self.paths.settings.write_text('{"port": 19351}', encoding="utf-8")
        self.assertEqual(service.configured_port(), 19351)
        self.paths.settings.write_text('{"port": true}', encoding="utf-8")
        with self.assertRaises(ServiceError):
            service.configured_port()
