"""Vercel FastAPI 入口。导入不连接数据库，云端不写临时 SQLite。"""
from dataclasses import asdict
from datetime import date
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .agent import AIError, DEFAULT_MODEL, run_agent
from .auth import AVATARS, AuthError
from .database import ConfirmationRequired, ConflictError
from .models import DAYS, DEVICES, LEVELS, PRIORITIES, SPEEDS, STATUSES, SUBJECTS, StudyProfile, TaskInput, ValidationError, iso_date
from .progress import get_progress
from .proposals import execute_proposal, list_proposals, reject_proposal

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "studypilot_session"


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Credentials(Body):
    username: str = Field(max_length=200)
    password: str = Field(max_length=256)


class Register(Credentials):
    password_again: str = Field(max_length=256)
    confirmed: bool = False


class Recovery(Body):
    username: str = Field(max_length=200)
    recovery_code: str = Field(max_length=128)
    new_password: str = Field(max_length=256)
    password_again: str = Field(max_length=256)
    confirmed: bool = False


class Confirm(Body):
    confirmed: bool = False


class TaskChange(Confirm):
    task: dict
    expected_version: int = Field(default=0, ge=0)


class ProfileChange(Confirm):
    profile: dict
    expected_version: int = Field(ge=0)


class Version(Confirm):
    expected_version: int = Field(ge=0)


class RecordChange(Confirm):
    task_id: int = Field(ge=1)
    study_date: str
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(default="", max_length=1000)


class PlanChange(Version):
    preview: dict


class PersonalChange(Version):
    nickname: str = Field(max_length=64)
    avatar: str
    bio: str = Field(default="", max_length=120)


class UsernameChange(Confirm):
    new_username: str = Field(max_length=200)
    current_password: str = Field(max_length=256)
    expected_username: str


class PasswordChange(Confirm):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)
    password_again: str = Field(max_length=256)


class Chat(Body):
    prompt: str = Field(min_length=1, max_length=3000)
    model: str = Field(default=DEFAULT_MODEL, max_length=100)
    history: list[dict] = Field(default_factory=list, max_length=12)
    consent: bool = False


def csrf(token):
    return hmac.new(token.encode(), b"StudyPilot web csrf v1", hashlib.sha256).hexdigest()


def create_app(auth_factory=None):
    app = FastAPI(title="StudyPilot", docs_url=None, redoc_url=None, openapi_url=None)
    cached_auth = None

    def store():
        nonlocal cached_auth
        if auth_factory:
            return auth_factory()
        if cached_auth is None:
            if os.getenv("STUDYPILOT_WEB_LOCAL") == "1" and not os.getenv("VERCEL"):
                from .auth import AuthStore
                cached_auth = AuthStore(os.getenv("STUDYPILOT_AUTH_DIR", str(ROOT/"data"/"accounts")))
            else:
                from .postgres import PostgresAuthStore
                cached_auth = PostgresAuthStore()
        return cached_auth

    @app.middleware("http")
    async def protection(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin", "")
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host") or (os.getenv("VERCEL") and parsed.scheme != "https"):
                return JSONResponse({"error": "请求来源无效，请从本站页面重新提交。"}, status_code=403)
            if "application/json" not in request.headers.get("content-type", "").lower():
                return JSONResponse({"error": "请使用 JSON 请求。"}, status_code=415)
            if len(await request.body()) > 131072:
                return JSONResponse({"error": "提交内容过大，请缩小范围。"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValidationError)
    async def invalid(request, error):
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(ConfirmationRequired)
    async def unconfirmed(request, error):
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(ConflictError)
    async def conflict(request, error):
        return JSONResponse({"error": str(error)}, status_code=409)

    @app.exception_handler(AuthError)
    async def unauthenticated(request, error):
        return JSONResponse({"error": str(error)}, status_code=401)

    @app.exception_handler(AIError)
    async def ai_error(request, error):
        return JSONResponse({"error": str(error)}, status_code=502)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, error):
        return JSONResponse({"error": "数据库暂时不可用，请检查云端连接配置或稍后重试。"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def body_error(request, error):
        # 不回显 Pydantic 的 input，避免密码或恢复码出现在错误响应。
        return JSONResponse({"error": "提交字段或类型不正确，请检查后重试。输入内容已保留。"}, status_code=422)

    def context(request: Request):
        auth = store()
        token = request.cookies.get(COOKIE, "")
        account = auth.authenticate(token)
        if account is None:
            raise AuthError("登录已失效，请重新登录。")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf(token)):
            raise HTTPException(403, "确认凭据无效，请刷新页面。")
        return auth, token, account

    def identity(auth, token, account):
        return dict(account=asdict(account), personal=auth.get_personal_profile(token), csrf=csrf(token),
                    ai_configured=bool(os.getenv("OPENAI_API_KEY", "").strip()),
                    default_model=os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL,
                    today=date.today().isoformat(),
                    options=dict(subjects=SUBJECTS, levels=LEVELS, speeds=SPEEDS, statuses=STATUSES,
                                 priorities=PRIORITIES, days=DAYS, devices=DEVICES, avatars=AVATARS))

    def learning(ctx):
        auth, token, _ = ctx
        return auth.study_database(token)

    def set_session(response, token):
        response.set_cookie(COOKIE, token, httponly=True, secure=bool(os.getenv("VERCEL")), samesite="strict", path="/")

    def matching(first, second):
        if first != second:
            raise ValidationError("两次密码不一致，输入内容已保留。")

    @app.get("/")
    def index():
        return FileResponse(ROOT/"public"/"index.html")

    @app.get("/study.css")
    def css_file():
        return FileResponse(ROOT/"public"/"study.css", media_type="text/css")

    @app.get("/study.js")
    def js_file():
        return FileResponse(ROOT/"public"/"study.js", media_type="text/javascript")

    @app.get("/learning-map.svg")
    def image_file():
        return FileResponse(ROOT/"assets"/"learning-map.svg", media_type="image/svg+xml")

    @app.get("/api/health")
    def health():
        return dict(ok=True, version="0.5.0", database_configured=bool(os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or (os.getenv("STUDYPILOT_WEB_LOCAL")=="1" and not os.getenv("VERCEL"))))

    @app.post("/api/register")
    def register(body: Register):
        matching(body.password, body.password_again)
        account, code = store().register(body.username, body.password, confirmed=body.confirmed)
        return dict(username=account.username, recovery_code=code)

    @app.post("/api/login")
    def login(body: Credentials):
        auth = store()
        token = auth.login(body.username, body.password)
        account = auth.authenticate(token)
        response = JSONResponse(identity(auth, token, account))
        set_session(response, token)
        return response

    @app.post("/api/recover")
    def recover(body: Recovery):
        matching(body.new_password, body.password_again)
        code = store().reset_password(body.username, body.recovery_code, body.new_password, confirmed=body.confirmed)
        return dict(recovery_code=code)

    @app.post("/api/logout")
    def logout(ctx=Depends(context)):
        auth, token, _ = ctx
        auth.logout(token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/me")
    def me(ctx=Depends(context)):
        return identity(*ctx)

    @app.get("/api/state")
    def state(ctx=Depends(context)):
        db = learning(ctx)
        profile, version = db.get_study_profile()
        tasks, sessions = db.get_tasks(), db.get_sessions()
        with db.connection() as conn:
            plans = [dict(row) for row in conn.execute("SELECT week_start,version,payload FROM schedule_plans ORDER BY week_start DESC")]
        for plan in plans:
            plan["payload"] = json.loads(plan["payload"])
        return dict(profile=asdict(profile), profile_version=version, tasks=tasks, records=sessions,
                    plans=plans, proposals=list_proposals(ctx[0], ctx[1]),
                    progress=get_progress(tasks, sessions, date.today()), personal=ctx[0].get_personal_profile(ctx[1]))

    @app.post("/api/profile")
    def profile(body: ProfileChange, ctx=Depends(context)):
        try:
            data = StudyProfile(**body.profile)
        except TypeError:
            raise ValidationError("学习档案字段不正确。") from None
        learning(ctx).save_profile(data, expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    def task_input(value):
        try:
            return TaskInput(**value)
        except TypeError:
            raise ValidationError("任务字段不正确。") from None

    @app.post("/api/tasks")
    def create_task(body: TaskChange, ctx=Depends(context)):
        return dict(task_id=learning(ctx).create_task(task_input(body.task), confirmed=body.confirmed))

    @app.put("/api/tasks/{task_id}")
    def update_task(task_id: int, body: TaskChange, ctx=Depends(context)):
        learning(ctx).update_task(task_id, task_input(body.task), expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int, body: Version, ctx=Depends(context)):
        learning(ctx).delete_task(task_id, expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    @app.post("/api/records")
    def record(body: RecordChange, ctx=Depends(context)):
        return dict(session_id=learning(ctx).log_session(body.task_id, body.study_date, body.minutes, body.note, confirmed=body.confirmed))

    @app.delete("/api/records/{record_id}")
    def delete_record(record_id: int, body: Confirm, ctx=Depends(context)):
        learning(ctx).delete_session(record_id, confirmed=body.confirmed)
        return {"ok": True}

    @app.get("/api/plans/preview")
    def preview(week_of: str, ctx=Depends(context)):
        selected = date.fromisoformat(iso_date(week_of, "计划周"))
        db = learning(ctx)
        _, version = db.get_schedule(selected)
        return dict(preview=db.preview_schedule(selected), expected_version=version)

    @app.post("/api/plans")
    def save_plan(body: PlanChange, ctx=Depends(context)):
        learning(ctx).save_schedule(body.preview, expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    @app.delete("/api/plans/{week_of}")
    def delete_plan(week_of: str, body: Version, ctx=Depends(context)):
        learning(ctx).delete_schedule(date.fromisoformat(iso_date(week_of, "计划周")), expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    @app.post("/api/personal")
    def personal(body: PersonalChange, ctx=Depends(context)):
        auth, token, _ = ctx
        auth.save_personal_profile(token, body.nickname, body.avatar, body.bio, expected_version=body.expected_version, confirmed=body.confirmed)
        return {"ok": True}

    @app.post("/api/username")
    def username(body: UsernameChange, ctx=Depends(context)):
        ctx[0].change_username(ctx[1], body.new_username, body.current_password, expected_username=body.expected_username, confirmed=body.confirmed)
        return {"ok": True}

    @app.post("/api/password")
    def password(body: PasswordChange, ctx=Depends(context)):
        matching(body.new_password, body.password_again)
        code = ctx[0].change_password(ctx[1], body.current_password, body.new_password, confirmed=body.confirmed)
        response = JSONResponse({"recovery_code": code})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/sessions")
    def sessions(ctx=Depends(context)):
        return ctx[0].get_sessions(ctx[1])

    @app.post("/api/sessions/revoke")
    def revoke(body: Confirm, ctx=Depends(context)):
        return dict(revoked=ctx[0].revoke_other_sessions(ctx[1], confirmed=body.confirmed))

    @app.get("/api/export")
    def export(ctx=Depends(context)):
        data = ctx[0].export_account(ctx[1])
        return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="StudyPilot-export.json"'})

    @app.post("/api/agent")
    def agent(body: Chat, ctx=Depends(context)):
        if body.consent is not True:
            raise ValidationError("请先同意向 OpenAI 发送本次问题、对话和工具读取的学习数据。")
        if len(json.dumps(body.history, ensure_ascii=False)) > 20000:
            raise ValidationError("对话上下文过长，请清空后重试。")
        result = run_agent(ctx[0], ctx[1], body.prompt, model=body.model, history=body.history)
        return asdict(result)

    @app.post("/api/proposals/{proposal_id}/execute")
    def execute(proposal_id: str, body: Confirm, ctx=Depends(context)):
        return execute_proposal(ctx[0], ctx[1], proposal_id, confirmed=body.confirmed)

    @app.post("/api/proposals/{proposal_id}/reject")
    def reject(proposal_id: str, ctx=Depends(context)):
        reject_proposal(ctx[0], ctx[1], proposal_id)
        return {"ok": True}

    @app.get("/api/development")
    def development(ctx=Depends(context)):
        if ctx[2].role != "developer":
            raise HTTPException(403, "仅开发者可查看。")
        return dict(completed=["本地账号和个人数据隔离", "规则式学习计划", "OpenAI 只读工具与提案确认", "Vercel Web 入口与 PostgreSQL 持久化"],
                    pending=["目标里程碑完成率", "考试优先级自动调整"])

    return app


app = create_app()
