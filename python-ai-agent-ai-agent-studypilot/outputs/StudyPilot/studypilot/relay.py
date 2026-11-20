"""Account-scoped desktop access to the fixed StudyPilot inference service."""

import json
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .ai import ProviderFailure, RELAY_ORIGIN, RELAY_PROVIDERS, _NoRedirect
from .auth import Account, AuthError, fingerprint
from .windows_credentials import read_credentials, write_credentials

ISSUE_LIFETIME = 600
TOKEN_LIFETIME = 30 * 86400
LIMIT = 131072
FIELD = "STUDYPILOT_RELAY_TOKEN"
TOKEN_FORMAT = re.compile(r"spai1_[A-Za-z0-9_-]{43}")
DDL = """CREATE TABLE IF NOT EXISTS desktop_ai_tokens (
    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
    pending INTEGER NOT NULL, expires_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS desktop_ai_tokens_account ON desktop_ai_tokens(account_id);"""


def issue(auth, web_session):
    code = "spai1_" + secrets.token_urlsafe(32)
    now = time.time()
    with auth.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = auth._active_account(conn, web_session)
        conn.execute("DELETE FROM desktop_ai_tokens WHERE expires_at<=?", (now,))
        conn.execute("DELETE FROM desktop_ai_tokens WHERE account_id=? AND pending=1", (account.id,))
        conn.execute("INSERT INTO desktop_ai_tokens VALUES(?,?,1,?)",
                     (fingerprint(code), account.id, now + ISSUE_LIFETIME))
    return code


def exchange(auth, code):
    if not TOKEN_FORMAT.fullmatch(code):
        raise AuthError("连接码无效或已过期，请在网页版重新生成。")
    token = "spai1_" + secrets.token_urlsafe(32)
    now = time.time()
    with auth.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            "UPDATE desktop_ai_tokens SET token_hash=?,pending=0,expires_at=? WHERE token_hash=? AND pending=1 AND expires_at>?",
            (fingerprint(token), now + TOKEN_LIFETIME, fingerprint(code), now),
        ).rowcount
        if not changed:
            raise AuthError("连接码无效或已过期，请在网页版重新生成。")
    return token


def active_account(conn, token):
    row = conn.execute(
        """SELECT a.id,a.username,a.role FROM desktop_ai_tokens t JOIN accounts a ON a.id=t.account_id
           WHERE t.token_hash=? AND t.pending=0 AND t.expires_at>?""",
        (fingerprint(token), time.time()),
    ).fetchone() if TOKEN_FORMAT.fullmatch(token) else None
    if row is None:
        raise AuthError("云端 AI 授权已失效，请重新连接。")
    return Account(**dict(row))


def revoke(auth, web_session):
    with auth.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = auth._active_account(conn, web_session)
        conn.execute("DELETE FROM desktop_ai_tokens WHERE account_id=?", (account.id,))


def target(account_id):
    return "StudyPilot.CloudAI." + account_id


def local_token(account_id):
    return read_credentials(target=target(account_id)).get(FIELD)


def connect(account_id, code):
    if not TOKEN_FORMAT.fullmatch(code):
        raise ProviderFailure("auth", "连接码格式不正确，请重新复制。")
    data = post(build_opener(_NoRedirect()), "/api/desktop-ai/exchange", {"code": code}, 15)
    token = data.get("token", "")
    if not isinstance(token, str) or not TOKEN_FORMAT.fullmatch(token):
        raise ProviderFailure("protocol", "云端返回的授权格式不正确。")
    write_credentials({FIELD: token}, target=target(account_id))


def disconnect(account_id):
    write_credentials({}, target=target(account_id))


def infer(opener, provider, token, payload, timeout):
    family = next(name for name, choice in RELAY_PROVIDERS.items() if choice == provider)
    data = post(opener, "/api/desktop-ai/infer", {"family": family, "payload": payload}, timeout, token)
    if data.get("status") != "completed" or not isinstance(data.get("output"), list):
        raise ProviderFailure("protocol", "云端模型未返回完整结果。")
    return data


def post(opener, path, payload, timeout, token=None):
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > LIMIT:
        raise ProviderFailure("oversize", "对话内容过长，请清空对话或缩小查询范围。")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with opener.open(Request(RELAY_ORIGIN + path, data=data, headers=headers), timeout=timeout) as response:
            data = json.loads(response.read(LIMIT + 1))
    except HTTPError as exc:
        status = exc.code
        exc.close()
        kind = {401: "auth", 403: "auth", 404: "access", 413: "oversize", 429: "rate_limit",
                504: "timeout"}.get(status, "server_error" if status >= 500 else "request")
        raise ProviderFailure(kind, "StudyPilot 云端 AI 暂时无法完成请求。", status=status) from None
    except (URLError, OSError):
        raise ProviderFailure("network", "无法连接 StudyPilot 云端 AI。") from None
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderFailure("protocol", "云端响应无法解析。") from None
    if not isinstance(data, dict):
        raise ProviderFailure("protocol", "云端响应格式不正确。")
    return data
