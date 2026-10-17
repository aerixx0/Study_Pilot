"""模型只能创建提案；此模块的确认入口独立于模型工具白名单。"""

from dataclasses import fields
from datetime import date
import json
import time
import uuid

from .database import ConflictError, require_confirmation
from .models import StudyProfile, TaskInput, ValidationError, clean_text, iso_date, minutes


ACTIONS = {"create_task", "update_task", "delete_task", "update_profile", "log_session", "save_schedule"}
TTL_SECONDS = 30 * 60
TASK_FIELDS = tuple(field.name for field in fields(TaskInput))


def task_data(row):
    return {key: row[key] for key in TASK_FIELDS} | {"requires_computer": bool(row["requires_computer"])}


def positive_id(value):
    if type(value) is not int or value < 1:
        raise ValidationError("任务编号须为正整数。")
    return value


def stage_proposal(auth, token, action, data, reason, *, request_id, call_id):
    """取服务器快照并保存待审提案；不调用任何学习数据写入方法。"""
    if action not in ACTIONS:
        raise ValidationError("不支持这种修改提案。")
    reason = clean_text(reason, "修改理由", 300)
    db = auth.study_database(token)
    payload = {}
    if action in {"create_task", "update_task"}:
        payload["after"] = TaskInput(**data["task"]).validated()
    if action in {"update_task", "delete_task", "log_session"}:
        row = db.get_task(positive_id(data["task_id"]))
        expected = data["expected_version"]
        if type(expected) is not int or row["version"] != expected:
            raise ConflictError("任务已变化，请重新读取后生成提案。")
        payload.update(task_id=row["id"], expected_version=expected, before=task_data(row))
    if action == "delete_task":
        payload["after"] = None
    elif action == "update_profile":
        profile, version = db.get_study_profile()
        if type(data["expected_version"]) is not int or data["expected_version"] != version:
            raise ConflictError("学习档案已变化，请重新读取后生成提案。")
        payload.update(before=profile.validated(), after=StudyProfile(**data["profile"]).validated(), expected_version=version)
    elif action == "log_session":
        day = iso_date(data["study_date"], "实际学习日期")
        if day > date.today().isoformat():
            raise ValidationError("不能记录未来的实际学习。")
        payload["after"] = dict(study_date=day, duration=minutes(data["minutes"], "实际学习分钟"),
                                note=clean_text(data["note"], "学习记录备注", 1000, False))
    elif action == "save_schedule":
        selected = date.fromisoformat(iso_date(data["week_of"], "计划周"))
        saved, version = db.get_schedule(selected)
        payload.update(before=saved, after=db.preview_schedule(selected), expected_version=version)
    if action in {"update_task", "update_profile"} and payload["after"] == payload["before"]:
        raise ValidationError("提案没有实际修改。")
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 512_000:
        raise ValidationError("提案内容过大，请缩小修改范围。")
    now = time.time()
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT id FROM agent_proposals WHERE request_id=? AND call_id=?", (request_id, call_id)).fetchone()
        if previous:
            return previous["id"]
        count = conn.execute("SELECT COUNT(*) FROM agent_proposals WHERE state='pending' AND expires_at>?", (now,)).fetchone()[0]
        if count >= 20:
            raise ValidationError("待确认提案已达 20 项，请先处理已有提案。")
        proposal_id = uuid.uuid4().hex
        conn.execute("INSERT INTO agent_proposals VALUES (?,?,?,?, 'pending',?,?,NULL,NULL,?,?)",
                     (proposal_id, action, encoded, reason, now, now + TTL_SECONDS, request_id, call_id))
    return proposal_id


def list_proposals(auth, token):
    db = auth.study_database(token)
    with db.connection() as conn:
        rows = conn.execute("SELECT * FROM agent_proposals ORDER BY (state='pending') DESC,created_at DESC,id DESC LIMIT 40").fetchall()
    return [dict(row) | {"payload": json.loads(row["payload"]), "result": json.loads(row["result"]) if row["result"] else None}
            for row in rows]


def execute_proposal(auth, token, proposal_id, *, confirmed=False):
    """用户界面的专用入口：重新认证、版本校验、业务写入和收据原子提交。"""
    require_confirmation(confirmed)
    db = auth.study_database(token)
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM agent_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise ValidationError("提案不存在或不属于当前账号。")
        if row["state"] == "applied":
            return json.loads(row["result"])
        if row["state"] != "pending":
            raise ConflictError("提案已被忽略，不能执行。")
        if row["expires_at"] <= time.time():
            raise ConflictError("提案已超过 30 分钟，请重新生成。")
        data = json.loads(row["payload"])
        action = row["action"]
        result = {"action": action}
        if action in {"update_task", "delete_task", "log_session"}:
            task = conn.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (data["task_id"],)).fetchone()
            if task is None or task["version"] != data["expected_version"] or task_data(task) != data["before"]:
                raise ConflictError("任务已变化或删除，请重新生成提案。")
        if action == "create_task":
            result["task_id"] = db.create_task(TaskInput(**data["after"]), confirmed=True, _connection=conn)
        elif action == "update_task":
            db.update_task(data["task_id"], TaskInput(**data["after"]), expected_version=data["expected_version"], confirmed=True, _connection=conn)
            result["task_id"] = data["task_id"]
        elif action == "delete_task":
            db.delete_task(data["task_id"], expected_version=data["expected_version"], confirmed=True, _connection=conn)
            result["task_id"] = data["task_id"]
        elif action == "update_profile":
            db.save_profile(StudyProfile(**data["after"]), expected_version=data["expected_version"], confirmed=True, _connection=conn)
        elif action == "log_session":
            result["session_id"] = db.log_session(data["task_id"], **data["after"], confirmed=True, _connection=conn)
        elif action == "save_schedule":
            db.save_schedule(data["after"], expected_version=data["expected_version"], confirmed=True, _connection=conn)
            result["week_start"] = data["after"]["week_start"]
        else:
            raise ValidationError("未知提案类型，未执行。")
        conn.execute("UPDATE agent_proposals SET state='applied',applied_at=?,result=? WHERE id=?",
                     (time.time(), json.dumps(result, ensure_ascii=False), proposal_id))
        return result


def reject_proposal(auth, token, proposal_id):
    db = auth.study_database(token)
    with db.connection() as conn:
        if conn.execute("UPDATE agent_proposals SET state='rejected' WHERE id=? AND state='pending'", (proposal_id,)).rowcount != 1:
            raise ConflictError("提案已处理或不存在，请刷新。")
