"""数据模型与输入校验；这里不依赖 Streamlit，方便单独学习和测试。"""

from dataclasses import asdict, dataclass, field
from datetime import date
import math


SUBJECTS = ("Python", "AI Agent", "数学", "英语", "计算机科研", "其他")
LEVELS = ("零基础", "入门", "基础", "进阶")
SPEEDS = ("较慢", "普通", "较快")
STATUSES = ("待开始", "进行中", "已完成")
PRIORITIES = ("高", "中", "低")
DAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
DEVICES = ("纸笔", "电脑", "手机")


class ValidationError(ValueError):
    """把可预期的输入错误转换成界面上的中文提示。"""


def clean_text(value: str, label: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label}必须是文字。")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"请填写{label}。")
    if len(value) > maximum:
        raise ValidationError(f"{label}最多 {maximum} 字。")
    return value


def minutes(value: int, label: str, maximum: int = 1440) -> int:
    # bool 是 int 的子类，因此这里用 type，避免 True 被当成 1 分钟。
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError(f"{label}必须是 1–{maximum} 的整数分钟。")
    return value


def iso_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{label}须使用 YYYY-MM-DD 格式。") from None
    if parsed.isoformat() != value:
        raise ValidationError(f"{label}须使用 YYYY-MM-DD 格式。")
    return value


@dataclass
class StudyProfile:
    # 默认值只是可编辑的档案草稿，不代表真实学习记录，也不会自动写入数据库。
    # 目标由用户决定；示例只放在界面的 placeholder，不能成为数据默认值。
    goals: str = ""
    weekly_hours: float = 8.0
    speed: str = "较慢"
    preference: str = "短任务、动手练习和中文解释"
    max_session_minutes: int = 45
    levels: dict = field(default_factory=lambda: {s: "零基础" if s in ("Python", "AI Agent", "计算机科研") else "基础" for s in SUBJECTS})
    priorities: dict = field(default_factory=lambda: {s: "高" if s in ("Python", "数学", "英语") else "中" for s in SUBJECTS})
    availability: dict = field(default_factory=lambda: {
        d: {"minutes": m, "devices": ["纸笔", "电脑"] if m else ["纸笔"]}
        for d, m in zip(DAYS, (0, 0, 0, 0, 120, 180, 180))
    })

    def validated(self):
        """检查时间、科目和设备，并返回可安全保存的标准字典。"""
        data = asdict(self)
        # 空目标是有效状态：用户可以暂不决定，也可以清空后确认删除。
        data["goals"] = clean_text(self.goals, "学习目标", 2000, required=False)
        data["preference"] = clean_text(self.preference, "学习偏好", 500, False)
        if type(self.weekly_hours) not in (int, float) or not math.isfinite(self.weekly_hours) or not 0 < self.weekly_hours <= 40:
            raise ValidationError("每周学习时间须大于 0 且不超过 40 小时。")
        if self.speed not in SPEEDS:
            raise ValidationError("请选择有效的学习速度。")
        minutes(self.max_session_minutes, "单次学习时长", 180)
        if not isinstance(self.levels, dict) or set(self.levels) != set(SUBJECTS) or any(v not in LEVELS for v in self.levels.values()):
            raise ValidationError("请为每个科目设置有效的当前水平。")
        if not isinstance(self.priorities, dict) or set(self.priorities) != set(SUBJECTS) or any(v not in PRIORITIES for v in self.priorities.values()):
            raise ValidationError("请为每个科目设置有效的优先级。")
        if not isinstance(self.availability, dict) or set(self.availability) != set(DAYS):
            raise ValidationError("请填写一周七天的可用时间。")
        total = 0
        for day, slot in self.availability.items():
            if not isinstance(slot, dict):
                raise ValidationError(f"{day}可用时间和设备格式无效。")
            amount = slot.get("minutes")
            devices = slot.get("devices")
            if type(amount) is not int or not 0 <= amount <= 1440:
                raise ValidationError(f"{day}可用时间须为 0–1440 分钟的整数。")
            if not isinstance(devices, list) or any(d not in DEVICES for d in devices) or len(set(devices)) != len(devices):
                raise ValidationError(f"{day}设备无效。")
            if amount and not devices:
                raise ValidationError(f"{day}有可用时间，请至少选择一种设备。")
            total += amount
        if total < self.weekly_hours * 60:
            raise ValidationError("各天可用时间合计少于每周学习时间，请调整其中一项。")
        return data


@dataclass
class TaskInput:
    title: str
    subject: str
    due_date: str
    estimated_minutes: int = 45
    priority: str = "中"
    status: str = "待开始"
    requires_computer: bool = False
    notes: str = ""

    def validated(self):
        """所有入口都复用同一校验，后续 Agent 也不能绕过这里。"""
        data = asdict(self)
        data["title"] = clean_text(self.title, "任务标题", 120)
        data["notes"] = clean_text(self.notes, "任务备注", 2000, False)
        if self.subject not in SUBJECTS or self.priority not in PRIORITIES or self.status not in STATUSES:
            raise ValidationError("科目、优先级或状态无效。")
        iso_date(self.due_date, "截止日期")
        minutes(self.estimated_minutes, "预计时长")
        if type(self.requires_computer) is not bool:
            raise ValidationError("需要电脑必须是真或假。")
        return data
