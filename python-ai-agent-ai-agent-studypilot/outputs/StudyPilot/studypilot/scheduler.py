"""确定性的每周排课；仅生成建议，不写数据库或伪造实际学习记录。"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .models import DAYS, LEVELS, PRIORITIES, ValidationError
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
    def deadline(task):
        return min(task["due_date"], profile.goal_deadline) if profile.goal_deadline else task["due_date"]

    studied, spent_by_day, reserved = defaultdict(int), defaultdict(int), defaultdict(int)
    actual_by_task_day, reserved_by_task_day = defaultdict(int), defaultdict(int)
    tasks_by_id = {task["id"]: task for task in tasks}
    for session in sessions:
        studied[session["task_id"]] += session["minutes"]
        spent_by_day[session["study_date"]] += session["minutes"]
        actual_by_task_day[session["task_id"], session["study_date"]] += session["minutes"]
    for entry in reservations:
        task = tasks_by_id.get(entry["task_id"])
        if (task and today.isoformat() <= entry["date"] <= deadline(task)
                and not start.isoformat() <= entry["date"] < end.isoformat()):
            reserved_by_task_day[entry["task_id"], entry["date"]] += entry["minutes"]
    for key, amount in reserved_by_task_day.items():
        # A study record can fulfil an existing reservation; deduct it only once.
        reserved[key[0]] += max(0, amount - actual_by_task_day[key])
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
    active.sort(key=lambda task: (deadline(task), PRIORITIES.index(task["priority"]),
                PRIORITIES.index(profile.priorities[task["subject"]]), not task["requires_computer"],
                LEVELS.index(profile.levels[task["subject"]]), task["id"]))
    for task in active:
        remaining = max(0, task["estimated_minutes"] - studied[task["id"]] - reserved[task["id"]])
        if not remaining:
            notices.append(dict(task_id=task["id"], title=task["title"],
                                reason="实际用时与其他周已保存的安排已覆盖预计时长，无需新增安排。"))
            continue
        limit = deadline(task)
        eligible = [day for day in days if today.isoformat() <= day["date"] <= limit
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
            if limit < max(start, today).isoformat():
                reason = ("目标期限已过或早于计划周。" if profile.goal_deadline and limit == profile.goal_deadline
                          else "已过截止日期，请先调整截止日期。")
                suggestion = "核对目标期限和任务截止日期，调整后重新预览。"
            elif not eligible:
                reason = "截止前没有可用电脑日期。" if task["requires_computer"] else "截止前没有可用学习日期。"
                suggestion = "增加截止前的可用时间或所需设备，或调整期限和任务范围。"
            elif not remaining_budget:
                reason = "每周预算已用完。"
                suggestion = "在实际可用时间内调整周预算，或减少任务范围、延后期限。"
            else:
                reason = "截止前符合时间与设备要求的每日容量不足。"
                suggestion = "增加截止前符合设备要求的时间，或缩小任务范围、调整期限。"
            unscheduled.append(dict(task_id=task["id"], title=task["title"], remaining_minutes=remaining,
                                    planned_minutes=assigned, reason=reason, suggestion=suggestion))
    entries.sort(key=lambda entry: entry["date"])
    return dict(week_start=start.isoformat(), week_end=(end - timedelta(days=1)).isoformat(),
                as_of=today.isoformat(), budget_minutes=budget, actual_minutes=actual,
                planned_minutes=sum(entry["minutes"] for entry in entries),
                unused_minutes=remaining_budget, entries=entries, days=days,
                unscheduled=unscheduled, notices=notices)
