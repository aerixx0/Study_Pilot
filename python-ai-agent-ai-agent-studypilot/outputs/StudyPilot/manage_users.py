"""本机维护命令；不提供网页接口，不读取或显示密码。"""

import argparse
import os
from pathlib import Path
import sqlite3

from studypilot.auth import AuthStore
from studypilot.models import ValidationError


def main():
    parser = argparse.ArgumentParser(description="StudyPilot 本机账号维护")
    parser.add_argument("action", choices=("grant-developer", "revoke-developer", "import-legacy"))
    parser.add_argument("username", help="已注册的用户名")
    parser.add_argument("--server-stopped", action="store_true", help="导入前确认已停止 StudyPilot 服务")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    legacy = Path(os.getenv("STUDYPILOT_DB") or root / "data" / "studypilot.db")
    auth = AuthStore(os.getenv("STUDYPILOT_AUTH_DIR") or legacy.parent / "accounts")
    try:
        if args.action == "import-legacy":
            if not args.server_stopped:
                parser.error("请先停止服务，然后加 --server-stopped 确认。原数据库会保留，非空账号不会被覆盖。")
            auth.import_legacy(args.username, legacy, confirmed=True)
            print("旧学习数据已导入指定账号；原数据库保留。")
        else:
            role = "developer" if args.action == "grant-developer" else "user"
            auth.set_role(args.username, role, confirmed=True)
            print(f"账号角色已更新为 {role}，下次页面操作时生效。")
        return 0
    except (ValidationError, sqlite3.Error, OSError) as exc:
        print(f"操作失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
