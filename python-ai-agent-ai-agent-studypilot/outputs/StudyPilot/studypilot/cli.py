"""StudyPilot local service and authenticated study commands."""

import argparse
from datetime import date
from getpass import getpass
import json
import os
from pathlib import Path
import sqlite3
import sys
import webbrowser

from .auth import AuthStore
from .local_data import backup_accounts, data_lock, import_legacy, migrate_accounts
from .local_paths import LocalPaths
from .local_service import LocalService, ServiceError
from .models import PRIORITIES, STATUSES, SUBJECTS, TaskInput, iso_date
from .proposals import execute_proposal, list_proposals, reject_proposal, task_data


def port_number(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("端口必须是 1–65535 的整数。") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须是 1–65535 的整数。")
    return port


def make_parser():
    parser = argparse.ArgumentParser(prog="studypilot", description="StudyPilot 本地学习管理")
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")
    start = commands.add_parser("start", help="启动本地服务并打开默认浏览器")
    start.add_argument("--no-browser", action="store_true", help="只启动并显示访问地址")
    start.add_argument("--port", type=port_number, metavar="PORT",
                       help="指定端口。默认从 8501 开始查找可用端口")
    commands.add_parser("stop", help="停止当前用户的 StudyPilot 服务")
    commands.add_parser("status", help="检查本地服务状态")

    task = commands.add_parser("task", help="查看、创建、编辑或删除任务")
    tasks = task.add_subparsers(dest="action", required=True)
    tasks.add_parser("list", help="列出任务")
    for action, label in (("add", "创建任务"), ("edit", "编辑任务")):
        edit = action == "edit"
        change = tasks.add_parser(action, help=label)
        if edit:
            change.add_argument("id", type=int)
        change.add_argument("--title", required=not edit)
        change.add_argument("--subject", choices=SUBJECTS, required=not edit)
        change.add_argument("--due", dest="due_date", required=not edit, metavar="YYYY-MM-DD")
        change.add_argument("--minutes", dest="estimated_minutes", type=int, default=None if edit else 45)
        change.add_argument("--priority", choices=PRIORITIES, default=None if edit else "中")
        change.add_argument("--status", choices=STATUSES, default=None if edit else "待开始")
        change.add_argument("--computer", dest="requires_computer", action=argparse.BooleanOptionalAction,
                            default=None if edit else False)
        change.add_argument("--notes", default=None if edit else "")
    tasks.add_parser("delete", help="删除任务").add_argument("id", type=int)

    schedule = commands.add_parser("plan", help="预览、查看或保存每周学习计划")
    plans = schedule.add_subparsers(dest="action", required=True)
    for action, label in (("preview", "生成预览"), ("show", "查看已保存计划"), ("save", "预览并确认保存")):
        plans.add_parser(action, help=label).add_argument("--week", default=date.today().isoformat(),
                                                          metavar="YYYY-MM-DD", help="目标周任意日期")

    record = commands.add_parser("record", help="查看或记录真实学习时间")
    records = record.add_subparsers(dest="action", required=True)
    records.add_parser("list", help="列出学习记录")
    log = records.add_parser("add", help="记录学习时间")
    log.add_argument("task_id", type=int)
    log.add_argument("minutes", type=int)
    log.add_argument("--date", default=date.today().isoformat(), metavar="YYYY-MM-DD")
    log.add_argument("--note", default="")
    records.add_parser("delete", help="删除学习记录").add_argument("id", type=int)

    ai = commands.add_parser("ai", help="咨询 AI 或查看、执行和忽略提案")
    ai_actions = ai.add_subparsers(dest="action", required=True)
    ask = ai_actions.add_parser("ask", help="经同意后向已配置的 AI 服务商提问")
    ask.add_argument("prompt")
    ask.add_argument("--mode", choices=("chat", "goal_coach", "plan_builder"), default="chat")
    ask.add_argument("--model", choices=("qwen", "gpt-oss"), help="选择 AI 模型；省略时自动选择")
    ai_actions.add_parser("status", help="显示本机模型的凭据配置状态")
    ai_actions.add_parser("configure", help="将本机 API 密钥保存到 Windows 凭据管理器")
    ai_actions.add_parser("proposals", help="查看提案")
    ai_actions.add_parser("apply", help="核对并确认执行一项提案").add_argument("id")
    ai_actions.add_parser("reject", help="忽略一项提案").add_argument("id")

    data = commands.add_parser("data", help="查看数据位置、备份或导入旧版数据")
    actions = data.add_subparsers(dest="action", required=True)
    actions.add_parser("path", help="显示用户数据和日志位置")
    actions.add_parser("backup", help="备份账号及学习数据")
    actions.add_parser("migrate", help="从旧版项目、data 或 accounts 目录复制账号库").add_argument("source", type=Path)
    legacy = actions.add_parser("import-legacy", help="把单库旧版学习数据导入已注册的空账号")
    legacy.add_argument("source", type=Path)

    for command in (task, schedule, record, ai, legacy):
        command.add_argument("--user", help="本地账号名称。密码在交互式终端内输入")
    return parser


def show(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def confirm(prompt):
    if input(f"{prompt} [y/N] ").strip().casefold() != "y":
        raise ServiceError("已取消。")


def login(auth, username):
    if not sys.stdin.isatty():
        raise ServiceError("请在交互式终端内运行，密码不会回显。")
    return auth.login(username or input("本地用户名："), getpass("本地密码："))


def task_action(db, args):
    if args.action == "list":
        show(db.get_tasks())
        return
    current = db.get_task(args.id) if args.action in ("edit", "delete") else None
    if args.action == "delete":
        show(current)
        confirm("删除以上任务？")
        db.delete_task(args.id, expected_version=current["version"], confirmed=True)
        return
    changes = {name: getattr(args, name) for name in TaskInput.__dataclass_fields__
               if getattr(args, name) is not None}
    task = TaskInput(**((task_data(current) if current else {}) | changes))
    validated = task.validated()
    show({"原任务": task_data(current), "更新": validated} if current else validated)
    confirm("保存以上任务？")
    if current:
        db.update_task(args.id, task, expected_version=current["version"], confirmed=True)
    else:
        print(f"任务编号：{db.create_task(task, confirmed=True)}")


def plan_action(db, args):
    week = date.fromisoformat(iso_date(args.week, "日期"))
    saved, version = db.get_schedule(week)
    if args.action == "show":
        show(saved)
        return
    preview = db.preview_schedule(week)
    show(preview)
    if args.action == "save":
        confirm("替换本周已保存计划？" if version else "保存以上计划？")
        db.save_schedule(preview, expected_version=version, confirmed=True)


def record_action(db, args):
    if args.action == "list":
        show(db.get_sessions())
        return
    if args.action == "delete":
        entry = next((row for row in db.get_sessions() if row["id"] == args.id), None)
        if entry is None:
            raise ServiceError("学习记录不存在。")
        show(entry)
        confirm("删除以上学习记录？")
        db.delete_session(args.id, confirmed=True)
        return
    task = db.get_task(args.task_id)
    show({"任务": task["title"], "日期": args.date, "分钟": args.minutes, "备注": args.note})
    confirm("保存以上实际学习时间？")
    print(f"记录编号：{db.log_session(args.task_id, args.date, args.minutes, args.note, confirmed=True)}")


def ai_action(auth, token, args):
    if args.action == "ask":
        from .agent import run_agent
        from .ai import FreeChatTransport
        from .relay import local_token

        confirm("同意对话使用相关学习数据？使用云端模型时，相关内容会发送至模型服务。")
        account = auth.authenticate(token)
        if account is None:
            raise ServiceError("登录已失效，请重新登录。")
        transport = FreeChatTransport(local=True, relay_token=local_token(account.id), family=args.model)
        transport.available()
        result = run_agent(auth, token, args.prompt, mode=args.mode, local=True, transport=transport)
        print(result.text)
        if result.proposals:
            print("待确认提案：")
            show(result.proposals)
        return
    proposals = list_proposals(auth, token)
    if args.action == "proposals":
        show(proposals)
        return
    proposal = next((item for item in proposals if item["id"] == args.id), None)
    if proposal is None:
        raise ServiceError("提案不在当前账号的最近 40 项中。")
    show(proposal)
    if args.action == "apply":
        confirm("确认执行以上 AI 提案？")
        show(execute_proposal(auth, token, args.id, confirmed=True))
    else:
        confirm("忽略以上 AI 提案？")
        reject_proposal(auth, token, args.id)


def local_ai_setup(action):
    from .ai import credential, provider_status

    if action == "status":
        show(provider_status(local=True))
        if os.getenv("STUDYPILOT_AI_ENABLED", "1") != "1":
            print("AI 已被 STUDYPILOT_AI_ENABLED 暂停。")
        return
    if os.name != "nt" or not sys.stdin.isatty():
        raise ServiceError("请在 Windows 交互式终端中设置本机 AI。")

    from .windows_credentials import read_credentials, write_credentials

    previous = read_credentials()
    print("本机 Qwen 无需 API Key。以下为可选 Cloudflare 备用配置，留空保留原设置。")
    cf_id = input("Cloudflare Account ID：").strip()
    cf_key = getpass("Cloudflare Workers AI API Token：").strip()
    changes = {name: value for name, value in {
        "CLOUDFLARE_ACCOUNT_ID": cf_id,
        "CLOUDFLARE_API_TOKEN": cf_key,
    }.items() if value}
    if not changes:
        print("没有输入新的凭据。")
        return
    updated = previous | changes
    if cf_id or cf_key:
        account_id = changes.get("CLOUDFLARE_ACCOUNT_ID") or credential("CLOUDFLARE_ACCOUNT_ID", updated)
        token = changes.get("CLOUDFLARE_API_TOKEN") or credential("CLOUDFLARE_API_TOKEN", updated)
        if len(account_id) != 32 or any(c not in "0123456789abcdefABCDEF" for c in account_id) or not token:
            raise ServiceError("Cloudflare 需要 32 位十六进制 Account ID 和 Workers AI API Token。")
    write_credentials(updated)
    print("已保存到 Windows 凭据管理器。刷新 AI 助手即可查看状态。")


def study_action(paths, args):
    with data_lock(paths) as owned:
        if not owned:
            raise ServiceError("另一项本地数据操作正在进行，请稍后重试。")
        if not (paths.accounts / "accounts.db").is_file():
            raise ServiceError("请先打开 StudyPilot 并注册本地账号。")
        auth = AuthStore(paths.accounts)
        token = login(auth, args.user)
        try:
            if args.command == "ai":
                ai_action(auth, token, args)
            else:
                action = {"task": task_action, "plan": plan_action, "record": record_action}[args.command]
                action(auth.study_database(token), args)
        finally:
            auth.logout(token)


def data_action(service, args, gui):
    paths = service.paths
    if args.action == "path":
        print(f"学习数据：{paths.accounts}\n备份：{paths.backups}\n配置：{paths.settings}\n日志：{paths.log}")
        return
    if args.action == "migrate":
        if gui:
            from .windows_ui import choose_folder, message

            args.source = choose_folder()
            if not args.source or not message("请先关闭旧版 StudyPilot。现在复制旧版账号和学习记录吗？",
                                               confirm=True):
                return
        else:
            confirm("请先关闭旧版 StudyPilot。现在复制旧版账号和学习记录？")
    with service.operation(), data_lock(paths) as owned:
        if service.state() is not None or not owned:
            raise ServiceError("请先停止 StudyPilot 和其他数据操作，再备份或导入。")
        if args.action == "backup":
            print(f"已备份到：{backup_accounts(paths)}")
        elif args.action == "migrate":
            target = migrate_accounts(paths, args.source)
            if gui:
                message(f"导入完成。可以打开 StudyPilot，使用原来的账号登录。\n{target}")
            else:
                print(f"已复制到：{target}")
        else:
            auth = AuthStore(paths.accounts)
            token = login(auth, args.user)
            try:
                confirm("将旧版学习记录导入当前空账号？")
                print(f"已导入：{import_legacy(paths, auth, auth.authenticate(token).username, args.source)}")
            finally:
                auth.logout(token)


def open_browser(url):
    if os.name == "nt":
        os.startfile(url)
        return True
    return webbrowser.open(url, new=2)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    service = LocalService(LocalPaths.current())
    if len(argv) in (2, 3) and argv[0] == "_worker":
        return service.run_worker(argv[1], int(argv[2]) if len(argv) == 3 else None)

    gui = os.name == "nt" and argv in (["_open"], ["_stop"], ["_migrate"])
    gui_commands = {"_open": ["start"], "_stop": ["stop"], "_migrate": ["data", "migrate", "."]}
    args = make_parser().parse_args(gui_commands[argv[0]] if gui else argv)
    try:
        if args.command == "start":
            url = service.start(args.port if args.port is not None else service.configured_port())
            print(f"StudyPilot：{url}")
            if not args.no_browser:
                try:
                    opened = open_browser(url)
                except (OSError, webbrowser.Error):
                    opened = False
                if not opened:
                    raise ServiceError(f"StudyPilot 已启动。请手动在浏览器地址栏打开：\n{url}")
        elif args.command == "stop":
            notice = "StudyPilot 已停止。" if service.stop() else "StudyPilot 未运行。"
            print(notice)
            if gui:
                from .windows_ui import message

                message(notice)
        elif args.command == "status":
            notice, code = service.status()
            print(notice)
            return code
        elif args.command == "ai" and args.action in ("status", "configure"):
            local_ai_setup(args.action)
        elif args.command == "data":
            data_action(service, args, gui)
        else:
            study_action(service.paths, args)
    except (EOFError, KeyboardInterrupt):
        return 130
    except (OSError, sqlite3.Error, ValueError) as error:
        if gui:
            from .windows_ui import message

            message(str(error), error=True)
        else:
            print(f"StudyPilot：{error}", file=sys.stderr)
        return 1
    return 0
