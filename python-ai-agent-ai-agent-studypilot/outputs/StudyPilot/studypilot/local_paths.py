"""Paths shared by the Windows launcher, CLI and maintenance tools."""

from dataclasses import dataclass
import os
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LocalPaths:
    home: Path
    accounts: Path

    @classmethod
    def current(cls):
        user_dir = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
        home = Path(os.environ.get("STUDYPILOT_HOME") or Path(user_dir) / "StudyPilot").resolve()
        old_db = os.environ.get("STUDYPILOT_DB")
        accounts = os.environ.get("STUDYPILOT_AUTH_DIR")
        default_data = Path(old_db).parent if old_db else home / "data"
        return cls(home, Path(accounts or default_data / "accounts").resolve())

    @property
    def run(self):
        return self.home / "run"

    @property
    def settings(self):
        return self.home / "settings.json"

    @property
    def log(self):
        return self.home / "logs" / "server.log"

    @property
    def backups(self):
        return self.home / "backups"
