"""中文助手及真实的提案审阅入口；对话文字不能代替按钮确认。"""

from datetime import datetime
import os
import time

import streamlit as st

from .agent import AIError, DEFAULT_MODEL, run_agent
from .database import ConfirmationRequired, ConflictError
from .models import ValidationError
from .proposals import execute_proposal, list_proposals, reject_proposal
from .schedule_ui import render_plan
from .theme import page_intro


LABELS = dict(create_task="创建任务", update_task="修改任务", delete_task="删除任务",
              update_profile="修改学习档案", log_session="保存真实学习记录", save_schedule="保存每周计划")
FIELD_LABELS = dict(title="标题", subject="科目", due_date="截止日期", estimated_minutes="预计分钟", priority="优先级",
                    status="状态", requires_computer="需要电脑", notes="备注", goals="学习目标", weekly_hours="每周小时",
                    speed="速度", preference="学习偏好", max_session_minutes="单次时长上限", levels="各科基础",
                    priorities="科目优先级", availability="每天时间和设备", study_date="实际学习日期", duration="实际分钟", note="备注", minutes="分钟", devices="设备")


def display_value(value):
    if type(value) is bool:
        return "是" if value else "否"
    if isinstance(value, dict):
        return "\n".join(f"{FIELD_LABELS.get(key, key)}：{display_value(entry)}" for key, entry in value.items())
    if isinstance(value, list):
        return "、".join(map(str, value))
    return str(value)


def render_proposal(proposal):
    data = proposal["payload"]
    action = proposal["action"]
    st.write(f"**{LABELS.get(action, action)}** · {proposal['reason']}")
    st.caption(f"编号 {proposal['id'][:8]} · 创建于 {datetime.fromtimestamp(proposal['created_at']):%m-%d %H:%M} · 30 分钟内有效")
    if action == "save_schedule":
        if data["expected_version"]:
            st.warning("确认后替换这一周已保存的计划。已有真实学习记录不变。")
        render_plan(data["after"])
    elif action == "delete_task":
        st.warning(f"将软删除 #{data['task_id']}：{data['before']['title']}。已有学习记录保留。")
        st.json(data["before"], expanded=False)
    elif action in {"update_task", "update_profile"}:
        rows = [{"字段": FIELD_LABELS.get(key, key), "当前内容": display_value(data["before"].get(key)), "拟改为": display_value(value)}
                for key, value in data["after"].items() if data["before"].get(key) != value]
        if action == "update_task":
            st.caption(f"任务 #{data['task_id']} · 基于版本 {data['expected_version']}")
        st.dataframe(rows, hide_index=True, width="stretch")
        for row in rows:
            if max(len(row["当前内容"]), len(row["拟改为"])) > 100:
                with st.expander(f"完整内容：{row['字段']}"):
                    left, right = st.columns(2)
                    left.caption("当前内容"); left.code(row["当前内容"], language=None)
                    right.caption("拟改为"); right.code(row["拟改为"], language=None)
    else:
        if action == "log_session":
            st.caption(f"关联任务 #{data['task_id']}：{data['before']['title']}")
        for key, value in data["after"].items():
            st.text(f"{FIELD_LABELS.get(key, key)}：{display_value(value)}")


def proposal_panel(auth, token):
    proposals = list_proposals(auth, token)
    pending = [entry for entry in proposals if entry["state"] == "pending"]
    st.subheader("待确认的修改")
    st.caption("以下内容才是实际待执行的更改。AI 回复中说“已完成”或你在聊天中说“确认”，都不会执行。")
    if not pending:
        st.info("暂无待确认提案。询问学习情况只会读取数据；要求修改时会在这里出现提案。")
    for proposal in pending:
        with st.container(border=True):
            render_proposal(proposal)
            expired = proposal["expires_at"] <= time.time()
            if expired:
                st.warning("提案已过期，请重新生成；也可以忽略它。")
            with st.form(f"proposal_{proposal['id']}", clear_on_submit=False):
                label = "我核对了以上更改，确认执行"
                if proposal["action"] == "log_session":
                    label = "我确认以上学习确实发生，并保存这条记录"
                confirmed = st.checkbox(label, key=f"approve_{proposal['id']}", disabled=expired)
                left, right = st.columns(2)
                approve = left.form_submit_button("确认执行", type="primary", disabled=expired)
                reject = right.form_submit_button("忽略提案")
                try:
                    if approve:
                        execute_proposal(auth, token, proposal["id"], confirmed=confirmed)
                        st.session_state["notice"] = "提案已执行并保存，重复提交不会重复写入。"
                        st.rerun()
                    elif reject:
                        reject_proposal(auth, token, proposal["id"])
                        st.rerun()
                except (ValidationError, ConflictError, ConfirmationRequired) as exc:
                    st.error(str(exc))
    completed = [entry for entry in proposals if entry["state"] == "applied"][:5]
    if completed:
        with st.expander("最近执行记录"):
            st.dataframe([{"提案": entry["id"][:8], "操作": LABELS.get(entry["action"], entry["action"]),
                           "执行时间": datetime.fromtimestamp(entry["applied_at"]).strftime("%m-%d %H:%M:%S"),
                           "收据": str(entry["result"])} for entry in completed], hide_index=True, width="stretch")


def agent_page(auth, account):
    page_intro("AI", "先看清，再向前一步", "查询真实学习情况，把修改建议留给你决定。", "YOUR STUDY ASSISTANT")
    configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
    if not configured:
        st.info("AI 未启用：本机服务未配置 OPENAI_API_KEY。你仍可查看和处理已保存的提案。")
        if account.role == "developer":
            with st.expander("本机配置说明"):
                st.write("在启动 StudyPilot 的同一终端设置 OPENAI_API_KEY；可用 OPENAI_MODEL 指定支持函数调用的模型，然后重启服务。不要把 Key 发到聊天中或写进源码。")
                st.caption(f"默认模型：{DEFAULT_MODEL}。实际可用模型取决于你的 OpenAI API 账号权限。")
    else:
        st.caption("使用 OpenAI Responses API；本次问题、对话上下文及工具读取的当前账号学习数据会发送给 OpenAI。账号密码、恢复码和登录令牌不发送。")
    model = st.text_input("模型", value=os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL, max_chars=100, key="agent_model")
    history = st.session_state.setdefault("agent_history", [])
    if st.button("清空对话", key="agent_clear"):
        st.session_state["agent_history"] = []
        st.session_state.pop("agent_trace", None)
        st.rerun()
    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    st.caption("聊天只保留在当前登录页面，刷新或退出后清除；提案和执行收据保存在当前账号的 SQLite 中。清空聊天不会执行或删除提案。")
    with st.form("agent_question", clear_on_submit=False):
        prompt = st.text_area("你想查询或调整什么？", key="agent_prompt", max_chars=3000,
                              placeholder="例如：看看我本周的学习情况；把任务 #1 延后到下周一，先给我看修改提案。")
        consent = st.checkbox("我同意将本次问题、对话上下文及工具读取的学习数据发送给 OpenAI", key="agent_consent")
        submitted = st.form_submit_button("发送给学习助手", type="primary", disabled=not configured)
    if submitted:
        if not consent:
            st.error("请先确认本次向 OpenAI 发送学习数据。输入内容已保留。")
        else:
            try:
                with st.status("正在分析；修改只会生成提案…", expanded=True) as status:
                    def show_tool(name, state):
                        st.write(f"{'待确认提案' if state == 'pending' else '只读查询' if state == 'read' else '参数未通过'}：{name}")
                    result = run_agent(auth, st.session_state.get("auth_token"), prompt, model=model, history=history, on_tool=show_tool)
                    status.update(label="已完成，修改仍需你确认", state="complete", expanded=False)
                st.session_state["agent_history"] = (history + [{"role": "user", "content": prompt},
                    {"role": "assistant", "content": result.text}])[-12:]
                st.session_state["agent_trace"] = result.trace
                st.session_state["clear_submitted_fields"] = ("agent_prompt",)
                st.rerun()
            except (AIError, ValidationError, ConflictError) as exc:
                st.error(str(exc))
    if st.session_state.get("agent_trace"):
        with st.expander("本次工具调用记录"):
            st.dataframe(st.session_state["agent_trace"], hide_index=True, width="stretch")
    proposal_panel(auth, st.session_state.get("auth_token"))
