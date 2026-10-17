"""确定性的每周排课；仅生成建议，不写数据库或伪造实际学习记录。"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .models import DAYS, PRIORITIES, ValidationError
from .progress import week_bounds


def generate_schedule(profile, tasks, sessions, selected_day, *, today=None, reservations=()):
    """截止日期优先，同期限按任务/科目优先级；普通任务优先使用无电脑日。"""
    profile.validated()
    today = today or date.today()
    if type(selected_day) is not date or type(today) is not date:
        raise ValidationError("请选择有效的计划日期。")
    start, end = week_bounds(selected_day)
    if end <= today:
        raise ValidationError("不能为已经过去的一周生成新计划。")
    budget = int(Decimal(str(profile.weekly_hours)) * 60)
    studied, spent_by_day, reserved = defaultdict(int), defaultdict(int), defaultdict(int)
    for session in sessions:
        studied[session["task_id"]] += session["minutes"]
        spent_by_day[session["study_date"]] += session["minutes"]
    for entry in reservations:
        if entry["date"] >= today.isoformat() and not start.isoformat() <= entry["date"] < end.isoformat():
            reserved[entry["task_id"]] += entry["minutes"]
    days = []
    for index, name in enumerate(DAYS):
        day = start + timedelta(days=index)
        slot = profile.availability[name]
        actual = spent_by_day[day.isoformat()]
        days.append(dict(date=day.isoformat(), weekday=name, available_minutes=slot["minutes"],
                         actual_minutes=actual, planned_minutes=0, devices=list(slot["devices"]),
                         remaining_minutes=max(0, slot["minutes"] - actual) if day >= today else 0))
    actual = sum(day["actual_minutes"] for day in days)
    remaining_budget = max(0, budget - actual)
    entries, unscheduled, notices = [], [], []
    active = [task for task in tasks if not task.get("deleted_at") and task["status"] != "已完成"]
    active.sort(key=lambda task: (task["due_date"], PRIORITIES.index(task["priority"]),
                PRIORITIES.index(profile.priorities[task["subject"]]), not task["requires_computer"], task["id"]))
    for task in active:
        remaining = max(0, task["estimated_minutes"] - studied[task["id"]] - reserved[task["id"]])
        if not remaining:
            notices.append(dict(task_id=task["id"], title=task["title"],
                                reason="实际用时与其他周已保存的安排已覆盖预计时长，无需新增安排。"))
            continue
        eligible = [day for day in days if today.isoformat() <= day["date"] <= task["due_date"]
                    and day["available_minutes"] and day["devices"]
                    and (not task["requires_computer"] or "电脑" in day["devices"])]
        # 需要电脑的任务保留电脑容量；同类日期仍按日期先后安排。
        if not task["requires_computer"]:
            eligible.sort(key=lambda day: ("电脑" in day["devices"], day["date"]))
        assigned = 0
        for day in eligible:
            while remaining and remaining_budget and day["remaining_minutes"]:
                amount = min(remaining, remaining_budget, day["remaining_minutes"], profile.max_session_minutes)
                entries.append(dict(task_id=task["id"], title=task["title"], subject=task["subject"],
                                    date=day["date"], minutes=amount, requires_computer=bool(task["requires_computer"])))
                day["planned_minutes"] += amount
                day["remaining_minutes"] -= amount
                remaining -= amount
                remaining_budget -= amount
                assigned += amount
        if remaining:
            if task["due_date"] < max(start, today).isoformat():
                reason = "已过截止日期，请先调整截止日期。"
            elif not eligible:
                reason = "截止前没有可用电脑日期。" if task["requires_computer"] else "截止前没有可用学习日期。"
            elif not remaining_budget:
                reason = "每周预算已用完。"
            else:
                reason = "截止前符合时间与设备要求的每日容量不足。"
            unscheduled.append(dict(task_id=task["id"], title=task["title"], remaining_minutes=remaining,
                                    planned_minutes=assigned, reason=reason))
    entries.sort(key=lambda entry: entry["date"])
    return dict(week_start=start.isoformat(), week_end=(end - timedelta(days=1)).isoformat(),
                as_of=today.isoformat(), budget_minutes=budget, actual_minutes=actual,
                planned_minutes=sum(entry["minutes"] for entry in entries),
                unused_minutes=remaining_budget, entries=entries, days=days,
                unscheduled=unscheduled, notices=notices)
