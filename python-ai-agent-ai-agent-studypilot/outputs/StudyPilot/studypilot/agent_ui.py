"""中文助手及真实的提案审阅入口；对话文字不能代替按钮确认。"""

from datetime import datetime
import time

import streamlit as st

from .agent import AIError, MODE_LABELS, MODES, run_agent
from .ai import ai_configured, configured_providers, provider_status
from .database import ConfirmationRequired, ConflictError
from .models import ValidationError
from .quota import QuotaExceeded
from .proposals import execute_proposal, list_proposals, reject_proposal
from .schedule_ui import render_plan


LABELS = dict(create_task="创建任务", update_task="修改任务", delete_task="删除任务",
              update_profile="修改学习档案", log_session="保存真实学习记录", save_schedule="保存每周计划")
TOOL_LABELS = dict(get_study_profile="读取学习档案", list_tasks="查看学习任务", get_task="查看任务详情",
                  get_study_records="查看学习记录", get_progress="统计学习进度", preview_weekly_plan="预览每周计划",
                  propose_task_create="准备新任务建议", propose_task_update="准备任务调整建议",
                  propose_task_delete="准备任务删除建议", propose_profile_update="准备档案修改建议",
                  propose_study_record="准备学习记录建议", propose_weekly_plan="准备每周计划建议")
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
        st.warning(f"将删除 #{data['task_id']}：{data['before']['title']}。已有学习记录保留。")
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


def proposal_panel(auth, token, proposals, *, has_history):
    pending = [entry for entry in proposals if entry["state"] == "pending"]
    if pending:
        st.subheader(f"待确认的修改（{len(pending)}）")
        st.caption("核对建议后，在卡片中勾选确认并执行。")
    elif has_history:
        st.caption("当前没有待确认的修改。")
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



SUGGESTIONS = (
    ("总结本周进度", "帮我总结本周的学习进度，并建议下一步。", "chat"),
    ("梳理学习目标", "和我一起梳理学习目标，先讨论，不要直接修改。", "goal_coach"),
    ("安排每周计划", "根据我的任务和可用时间生成本周计划建议。", "plan_builder"),
)


def start_new_chat():
    for key in ("agent_history", "agent_trace", "agent_prompt", "agent_consent", "agent_mode"):
        st.session_state.pop(key, None)


def fill_suggestion(prompt, mode):
    st.session_state["agent_prompt"] = prompt
    st.session_state["agent_mode"] = mode
    st.session_state.pop("agent_consent", None)


def render_thread(history):
    if not history:
        st.markdown(
            '<div class="pilot-chat-welcome"><div class="pilot-chat-mark" aria-hidden="true">↗</div>'
            '<h2>今天，想推进什么？</h2><p>聊聊学习目标，或者安排接下来的学习计划。</p></div>',
            unsafe_allow_html=True,
        )
        with st.container(key="assistant-suggestions", horizontal=True, horizontal_alignment="center", gap="small"):
            for label, prompt, mode in SUGGESTIONS:
                st.button(label, key=f"assistant-suggest-{mode}", icon=":material/north_east:",
                          on_click=fill_suggestion, args=(prompt, mode))
        return
    for index, message in enumerate(history):
        role = message["role"]
        avatar = ":material/north_east:" if role == "assistant" else None
        with st.container(key=f"assistant-message-{role}-{index}"), st.chat_message(role, avatar=avatar):
            st.text(message["content"], width="stretch")


def agent_page(auth):
    configured = ai_configured(local=True)
    token = st.session_state.get("auth_token")
    history = st.session_state.setdefault("agent_history", [])
    proposals = list_proposals(auth, token)

    with st.container(key="assistant-workspace"):
        with st.container(key="assistant-topbar", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center"):
            st.markdown("**对话**")
            st.button("新建对话", key="agent_clear", type="tertiary", icon=":material/add:",
                      on_click=start_new_chat)

        thread = st.container(key="assistant-transcript", height=390 if history or proposals else "content",
                              border=False, autoscroll=bool(history))
        with thread:
            render_thread(history)

        with st.container(key="assistant-dock"):
            if not configured:
                st.caption("对话服务暂未开放。学习管理和已有提案仍可使用。")
            with st.form("agent_question", clear_on_submit=False):
                prompt = st.text_area("发送消息", key="agent_prompt", height=80, max_chars=3000,
                                      label_visibility="collapsed", placeholder="向 StudyPilot 提问")
                with st.container(key="assistant-controls", horizontal=True, horizontal_alignment="distribute",
                                  vertical_alignment="center"):
                    mode = st.selectbox("对话模式", MODES, key="agent_mode", format_func=MODE_LABELS.__getitem__,
                                        label_visibility="collapsed", width=190)
                    submitted = st.form_submit_button("发送", type="primary", disabled=not configured,
                                                      icon=":material/arrow_upward:")
                consent = st.checkbox("我同意本次对话使用相关学习资料", key="agent_consent")

            if submitted and not consent:
                st.error("请先同意本次使用相关学习资料。问题已保留。")
            elif submitted:
                try:
                    with st.status("正在思考…", expanded=False):
                        def show_tool(name, state):
                            label = {"pending": "待确认提案", "read": "只读查询"}.get(state, "未完成")
                            st.write(f"{label}：{TOOL_LABELS.get(name, '处理学习请求')}")
                        result = run_agent(auth, token, prompt, mode=mode, history=history, on_tool=show_tool, local=True)
                    st.session_state["agent_history"] = (history + [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": result.text}])[-12:]
                    st.session_state["agent_trace"] = result.trace
                    st.session_state["clear_submitted_fields"] = ("agent_prompt", "agent_consent")
                    st.rerun()
                except (AIError, ValidationError, ConflictError, QuotaExceeded) as exc:
                    st.error(f"{exc} 问题已保留，可修改后重新发送。")
                    proposals = list_proposals(auth, token)

            if configured:
                providers = configured_providers(local=True)
                if any(provider.name == "cloudflare" for provider in providers):
                    st.caption("本机模型优先。若使用 Cloudflare 备用，问题、上下文及相关学习资料会发给 "
                               "Cloudflare。AI 建议请先核对。")
                else:
                    st.caption("问题和学习资料在本机处理。AI 建议请先核对。对话在刷新或退出后清除。")
            with st.expander("本地 AI 连接状态"):
                for provider in provider_status(local=True):
                    if provider["name"] == "llamacpp":
                        status = "已就绪，无需 API Key" if provider["configured"] else "本机模型未就绪"
                    elif provider["configured"]:
                        status = "已读取凭据"
                    elif provider["name"] == "cloudflare" and provider["token_configured"]:
                        status = "缺少有效的 Cloudflare Account ID"
                    else:
                        status = "缺少 API 密钥"
                    st.write(f"{provider['label']} · {status}")
                st.caption("Cloudflare 是可选备用。在开始菜单「配置 StudyPilot AI」中输入 Cloudflare 凭据。"
                           "Cloudflare 请使用 Workers Free。")

        with thread:
            proposal_panel(auth, token, proposals, has_history=bool(history))
            if trace := st.session_state.get("agent_trace"):
                with st.expander("本次处理记录"):
                    st.dataframe([{"操作": TOOL_LABELS.get(row["tool"], "处理学习请求"),
                                   "状态": {"read": "只读查询", "pending": "待确认提案", "error": "未完成"}.get(
                                       row["state"], "未完成")}
                                  for row in trace], hide_index=True, width="stretch")
