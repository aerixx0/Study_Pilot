"""持久化的 AI 请求限流与全站免费额度。

免费模型的额度属于服务提供方，全站共用，所以计数器必须落在服务端存储里：
本地版写在账号 SQLite，云端写在 sp_auth schema，重启和冷启动都不会清零。
只记录账号标识、窗口编号和已用次数，不含提示词或任何学习内容。
"""

from datetime import datetime, timezone
import os
import time


WINDOW_SECONDS = 600
USER_LIMIT = 15
SITE_LIMIT = 400
MAX_WINDOW = 86400


class QuotaExceeded(ValueError):
    """可向用户展示的额度错误。"""


def setting(name, default, minimum, maximum):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


class AIMeter:
    def __init__(self, store):
        self.store = store

    def limits(self):
        return {
            "window": setting("STUDYPILOT_AI_WINDOW_SECONDS", WINDOW_SECONDS, 60, MAX_WINDOW),
            "user_limit": setting("STUDYPILOT_AI_USER_LIMIT", USER_LIMIT, 1, 1000),
            "site_limit": setting("STUDYPILOT_AI_SITE_LIMIT", SITE_LIMIT, 1, 100000),
        }

    def reserve(self, token, *, now=None):
        """在事务内记一次用量；超过账号窗口或全站当日额度就抛 QuotaExceeded。"""
        limits = self.limits()
        now = time.time() if now is None else now
        window = int(now // limits["window"])
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            account = self.store._active_account(conn, token)
            conn.execute("DELETE FROM ai_usage WHERE window_start < ?", (window - 1,))
            conn.execute("DELETE FROM ai_site_usage WHERE day < ?", (day,))
            row = conn.execute("SELECT used FROM ai_usage WHERE account_id=? AND window_start=?",
                               (account.id, window)).fetchone()
            used = row["used"] if row else 0
            if used >= limits["user_limit"]:
                raise QuotaExceeded(f"AI 请求过于频繁：每 {limits['window'] // 60} 分钟最多 "
                                    f"{limits['user_limit']} 次，请稍后再试。")
            site = conn.execute("SELECT used FROM ai_site_usage WHERE day=?", (day,)).fetchone()
            total = site["used"] if site else 0
            if total >= limits["site_limit"]:
                raise QuotaExceeded("今天全站 AI 使用额度已达上限，请明天再试；其他学习功能仍可正常使用。")
            if row:
                conn.execute("UPDATE ai_usage SET used=used+1 WHERE account_id=? AND window_start=?",
                             (account.id, window))
            else:
                conn.execute("INSERT INTO ai_usage (account_id,window_start,used) VALUES (?,?,1)",
                             (account.id, window))
            if site:
                conn.execute("UPDATE ai_site_usage SET used=used+1 WHERE day=?", (day,))
            else:
                conn.execute("INSERT INTO ai_site_usage (day,used) VALUES (?,1)", (day,))
        return {"remaining": limits["user_limit"] - used - 1, "window_seconds": limits["window"],
                "site_remaining": max(0, limits["site_limit"] - total - 1)}
