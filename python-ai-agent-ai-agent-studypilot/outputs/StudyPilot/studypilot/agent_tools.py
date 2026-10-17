"""固定白名单：只读查询和提案。没有 SQL、文件路径、账号参数或确认执行工具。"""

from datetime import date
import json

from .database import ConflictError
from .models import DAYS, DEVICES, LEVELS, PRIORITIES, SPEEDS, STATUSES, SUBJECTS, ValidationError, iso_date
from .progress import get_progress
from .proposals import stage_proposal


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def text(maximum=2000, **extra):
    return {"type": "string", "maxLength": maximum, **extra}


def integer(minimum=1, maximum=2**31-1):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def choice(values):
    return {"type": "string", "enum": list(values)}


DATE = text(10, format="date")
TASK = obj(dict(title=text(120), subject=choice(SUBJECTS), due_date=DATE, estimated_minutes=integer(1, 1440),
                priority=choice(PRIORITIES), status=choice(STATUSES), requires_computer={"type": "boolean"}, notes=text(2000)))
PROFILE = obj(dict(goals=text(2000), weekly_hours={"type": "number", "exclusiveMinimum": 0, "maximum": 40},
                   speed=choice(SPEEDS), preference=text(500), max_session_minutes=integer(1, 180),
                   levels=obj({subject: choice(LEVELS) for subject in SUBJECTS}),
                   priorities=obj({subject: choice(PRIORITIES) for subject in SUBJECTS}),
                   availability=obj({day: obj(dict(minutes=integer(0, 1440),
                       devices={"type": "array", "items": choice(DEVICES), "maxItems": 3})) for day in DAYS})))


def tool(name, description, properties):
    return dict(type="function", name=name, description=description, strict=True, parameters=obj(properties))


TOOLS = [
    tool("get_study_profile", "只读：获取当前账号学习档案及版本；saved=false 表示尚未保存的默认草稿。", {}),
    tool("list_tasks", "只读：分页读取当前账号未删除任务。备注截取前 200 字，编辑前用 get_task 读取完整内容。",
         dict(subject=choice(("全部",) + SUBJECTS), status=choice(("全部",) + STATUSES), offset=integer(0), limit=integer(1, 30))),
    tool("get_task", "只读：获取一个任务的完整内容与版本号。", dict(task_id=integer())),
    tool("get_study_records", "只读：分页读取真实学习记录，日期均须填写。", dict(start_date=DATE, end_date=DATE, offset=integer(0), limit=integer(1, 20))),
    tool("get_progress", "只读：统计指定日期所在周及每周历史；不虚构学习用时。", dict(day=DATE)),
    tool("preview_weekly_plan", "只读：依据已保存档案、预算、每天时间和设备生成规则计划预览，不保存。", dict(week_of=DATE)),
    tool("propose_task_create", "只生成创建任务的待确认提案，不创建任务。", dict(task=TASK, reason=text(300))),
    tool("propose_task_update", "只生成任务修改提案。先读取完整任务；保留用户未要求修改的字段。",
         dict(task_id=integer(), expected_version=integer(), task=TASK, reason=text(300))),
    tool("propose_task_delete", "只生成软删除任务提案；真实学习记录保留。", dict(task_id=integer(), expected_version=integer(), reason=text(300))),
    tool("propose_profile_update", "只生成档案修改提案。先读档案；目标由用户决定，不能擅自补充目标。",
         dict(expected_version=integer(0), profile=PROFILE, reason=text(300))),
    tool("propose_study_record", "仅针对用户明确报告的实际学习生成记录提案；不得把计划时长当实际时长。",
         dict(task_id=integer(), expected_version=integer(), study_date=DATE, minutes=integer(1, 1440), note=text(1000), reason=text(300))),
    tool("propose_weekly_plan", "由服务器规则生成本周计划保存提案，不接受模型编造的时间表，不自动保存。", dict(week_of=DATE, reason=text(300))),
]
SCHEMAS = {item["name"]: item["parameters"] for item in TOOLS}
PROPOSE_ACTIONS = dict(propose_task_create="create_task", propose_task_update="update_task", propose_task_delete="delete_task",
                       propose_profile_update="update_profile", propose_study_record="log_session", propose_weekly_plan="save_schedule")


def validate(schema, value):
    """校验这里使用的 JSON Schema 子集；即使模型绕过 strict 也不信任其参数。"""
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
             "integer": type(value) is int, "number": type(value) in (int, float), "boolean": type(value) is bool}[kind]
    if not valid:
        raise ValidationError("工具参数类型不正确。")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValidationError("工具参数有缺失或不允许的字段。")
        for key, definition in schema["properties"].items():
            validate(definition, value[key])
    elif kind == "array":
        if len(value) > schema.get("maxItems", 100):
            raise ValidationError("工具数组过长。")
        for entry in value:
            validate(schema["items"], entry)
        if schema.get("uniqueItems") and len(set(value)) != len(value):
            raise ValidationError("工具数组包含重复选项。")
    elif kind == "string":
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValidationError("工具文字包含无效 Unicode 字符。")
        if len(value) > schema.get("maxLength", 2000):
            raise ValidationError("工具文字参数过长。")
        if schema.get("format") == "date":
            iso_date(value, "工具日期")
    elif kind in {"integer", "number"}:
        import math
        if (type(value) is float and not math.isfinite(value)) or value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            raise ValidationError("工具数字参数超出范围。")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValidationError("工具数字参数超出范围。")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError("工具选项无效。")


def parse_arguments(name, raw):
    if name not in SCHEMAS:
        raise ValidationError("工具不在允许的白名单中。")
    if not isinstance(raw, str) or len(raw) > 20000:
        raise ValidationError("工具参数过大或格式错误。")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError("invalid number")
    try:
        arguments = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError("工具参数不是有效 JSON。") from None
    validate(SCHEMAS[name], arguments)
    return arguments


def plan_summary(plan):
    return {key: plan[key] for key in ("week_start", "week_end", "as_of", "budget_minutes", "actual_minutes", "planned_minutes", "unused_minutes")} | {
        "entries": plan["entries"][:20], "entry_count": len(plan["entries"]),
        "unscheduled": plan["unscheduled"][:20], "unscheduled_count": len(plan["unscheduled"])}


class AgentTools:
    def __init__(self, auth, token, request_id):
        self.auth, self.token, self.request_id = auth, token, request_id
        self.trace = []
        self.proposals = []

    def call(self, name, raw, call_id):
        args = parse_arguments(name, raw)
        if name in PROPOSE_ACTIONS:
            proposal = stage_proposal(self.auth, self.token, PROPOSE_ACTIONS[name],
                {key: value for key, value in args.items() if key != "reason"}, args["reason"], request_id=self.request_id, call_id=call_id)
            self.proposals.append(proposal)
            return dict(proposal_id=proposal, state="pending", message="仅生成提案，尚未执行。只能由用户在界面确认。")
        db = self.auth.study_database(self.token)  # 每次工具调用重新认证；路径不来自模型。
        with db.connection() as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            if name == "get_study_profile":
                row = conn.execute("SELECT payload,version FROM profile WHERE id=1").fetchone()
                from .models import StudyProfile
                return dict(saved=bool(row), version=row["version"] if row else 0,
                            profile=json.loads(row["payload"]) if row else StudyProfile().validated())
            if name == "list_tasks":
                clauses, params = ["deleted_at IS NULL"], []
                for field in ("subject", "status"):
                    if args[field] != "全部":
                        clauses.append(f"{field}=?"); params.append(args[field])
                sql = "SELECT id,title,subject,due_date,estimated_minutes,priority,status,requires_computer,version,substr(notes,1,200) AS notes,length(notes)>200 AS notes_truncated FROM tasks WHERE "
                rows = [dict(row) for row in conn.execute(sql + " AND ".join(clauses) + " ORDER BY due_date,id LIMIT ? OFFSET ?",
                                                        (*params, args["limit"] + 1, args["offset"]))]
                return dict(tasks=rows[:args["limit"]], has_more=len(rows) > args["limit"], next_offset=args["offset"] + args["limit"])
            if name == "get_task":
                row = conn.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (args["task_id"],)).fetchone()
                if row is None:
                    raise ValidationError("任务不存在或已删除。")
                result = dict(row); result["requires_computer"] = bool(result["requires_computer"])
                return result
            if name == "get_study_records":
                if args["start_date"] > args["end_date"]:
                    raise ValidationError("开始日期不能晚于结束日期。")
                rows = [dict(row) for row in conn.execute("""SELECT s.id,s.task_id,s.study_date,s.minutes,s.subject,
                    substr(s.note,1,200) AS note,length(s.note)>200 AS note_truncated,t.title AS task_title
                    FROM study_sessions s JOIN tasks t ON s.task_id=t.id WHERE s.study_date BETWEEN ? AND ?
                    ORDER BY s.study_date DESC,s.id DESC LIMIT ? OFFSET ?""",
                    (args["start_date"], args["end_date"], args["limit"] + 1, args["offset"]))]
                return dict(records=rows[:args["limit"]], has_more=len(rows) > args["limit"], next_offset=args["offset"] + args["limit"])
            if name == "get_progress":
                tasks = [dict(row) for row in conn.execute("SELECT * FROM tasks")]
                sessions = [dict(row) for row in conn.execute("SELECT * FROM study_sessions")]
                result = get_progress(tasks, sessions, date.fromisoformat(args["day"]))
                return {key: result[key] for key in ("task_count", "completed_count", "completion_rate", "actual_minutes", "subjects", "weekly_history")}
            if name == "preview_weekly_plan":
                return plan_summary(db._schedule_preview(conn, date.fromisoformat(args["week_of"])))
        raise ValidationError("工具未实现。")
