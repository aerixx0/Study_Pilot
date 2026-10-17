"""只汇总真实任务和学习记录，不调用 AI，不推测目标完成百分比。"""

from collections import defaultdict
from datetime import date, timedelta


def week_bounds(day: date):
    """date.weekday(): 周一是 0；先找到周一，再计算下一周周一。"""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=7)


def get_progress(tasks, sessions, day: date):
    """完成率以本周到期且未删除的任务为分母；实际时长按学习日期汇总。"""
    start, end = week_bounds(day)
    active = [t for t in tasks if not t.get("deleted_at")]
    cohort = [t for t in active if start.isoformat() <= t["due_date"] < end.isoformat()]
    completed = [t for t in cohort if t["status"] == "已完成"]
    weekly_sessions = [s for s in sessions if start.isoformat() <= s["study_date"] < end.isoformat()]
    subjects = defaultdict(int)
    history = defaultdict(int)
    for session in sessions:
        monday, _ = week_bounds(date.fromisoformat(session["study_date"]))
        history[monday.isoformat()] += session["minutes"]
    for session in weekly_sessions:
        subjects[session["subject"]] += session["minutes"]
    total = sum(subjects.values())
    return {
        "start": start, "end": end, "task_count": len(cohort), "completed_count": len(completed),
        "completion_rate": len(completed) / len(cohort) if cohort else None,
        "actual_minutes": total, "subjects": dict(subjects),
        "subject_shares": {s: m / total for s, m in subjects.items()} if total else {},
        "incomplete": [t for t in cohort if t["status"] != "已完成"],
        "overdue": [t for t in active if t["due_date"] < day.isoformat() and t["status"] != "已完成"],
        "weekly_history": dict(sorted(history.items())), "sessions": weekly_sessions,
    }
