"""运行入口：python -m streamlit run app.py。界面只负责展示和收集输入。"""

from datetime import date, timedelta
from html import escape
import os
from pathlib import Path
import sqlite3

import streamlit as st

from studypilot.database import ConfirmationRequired, ConflictError, Database
from studypilot.auth import AuthStore, AuthError
from studypilot.auth_ui import login_gate, account_bar, account_settings
from studypilot.schedule_ui import schedule_page
from studypilot.agent_ui import agent_page
from studypilot.ai import ai_configured
from studypilot.models import DAYS, DEVICES, LEVELS, PRIORITIES, SPEEDS, STATUSES, SUBJECTS, StudyProfile, TaskInput, ValidationError
from studypilot.progress import get_progress
from studypilot.theme import apply_theme, availability_strip, empty_state, footer, learning_illustration, masthead, page_intro, section_heading


ROOT = Path(__file__).resolve().parent
# 这两个常量只用于界面提示；绝不作为输入值或数据库写入的兜底值。
GOAL_PLACEHOLDER = "写下希望达成的学习目标，也可以暂时留空。"
LEGACY_GOALS_EXAMPLE = "学习 Python 基础；强化数学和英语；逐步了解 AI Agent。"


def go_to(page):
    """按钮回调在下一次页面绘制前改变导航；它不修改数据库。"""
    st.session_state["navigation"] = page


def commit(action, success_message, *, clear_fields=()):
    """仅在按钮提交后调用；错误保留在页面，成功刷新并显示一次提示。"""
    try:
        action()
    except (ConfirmationRequired, ConflictError, ValidationError) as exc:
        st.error(str(exc))
    except sqlite3.Error:
        st.error("暂时无法保存，请稍后重试。填写内容已保留。")
    else:
        # 下一次绘制组件前清理；校验失败时保留全部草稿。
        st.session_state["clear_submitted_fields"] = clear_fields
        st.session_state["notice"] = success_message
        st.rerun()


def profile_page(db):
    profile, version = db.get_study_profile()
    page_intro("02", "给学习留一点空间", "目标、时间和设备，按你的真实生活填写。无需姓名或学校信息。", "YOUR LEARNING PROFILE")
    if not version:
        st.info("目标可以暂时留空。请核对可用时间与设备，确认保存后用于生成学习计划。")
    with st.form(f"profile_{version}"):
        st.subheader("你的学习目标")
        if version and profile.goals == LEGACY_GOALS_EXAMPLE:
            st.caption("目标由你决定，可随时编辑或清空，确认保存后生效。")
        goals = st.text_area("学习目标", value=profile.goals, max_chars=2000,
                             height=155, placeholder=GOAL_PLACEHOLDER, key=f"profile_goals_{version}")
        st.caption("每行可填写一个目标，也可删除或清空。正式目标以确认保存的内容为准。")
        # 折叠入口只改变显示状态，不提交表单，不修改输入或数据库。
        # 联网对话统一在 AI 助手页进行，避免提交当前档案草稿。
        with st.expander("AI 帮我制定目标"):
            st.info("需要建议时，请切换到“AI 助手”讨论目标。目标修改会先生成待确认建议，核对后才保存；此处未提交的内容不会自动发送。")
            st.markdown("你可以先想一想：\n\n"
                        "- 我目前处于哪个学习阶段？\n"
                        "- 我对哪些学科或领域感兴趣？\n"
                        "- 我最希望改善什么问题？\n"
                        "- 我希望长期朝哪个方向发展？\n"
                        "- 我每周实际可以投入多少时间？")
            st.caption("这些思考提示不会保存。未提交的草稿切换页面后可能丢失，请先决定是否保存当前档案。")
        st.subheader("时间与学习偏好")
        left, right = st.columns(2)
        hours = left.number_input("每周学习时间（小时）", min_value=0.5, max_value=40.0, value=float(profile.weekly_hours), step=0.5)
        speed = right.selectbox("学习速度", SPEEDS, index=SPEEDS.index(profile.speed))
        maximum = left.number_input("单次学习时长上限（分钟）", 1, 180, profile.max_session_minutes)
        preference = right.text_input("学习偏好", profile.preference, max_chars=500)
        st.subheader("各科目基础与优先级")
        levels, priorities = {}, {}
        for subject in SUBJECTS:
            a, b = st.columns(2)
            levels[subject] = a.selectbox(f"{subject} · 当前水平", LEVELS, index=LEVELS.index(profile.levels[subject]))
            priorities[subject] = b.selectbox(f"{subject} · 优先级", PRIORITIES, index=PRIORITIES.index(profile.priorities[subject]))
        st.subheader("每一天的时间与设备")
        st.caption("填写额外学习时间；0 分钟代表这天不安排学习。各天合计应至少覆盖每周学习时间。")
        availability = {}
        for day in DAYS:
            a, b = st.columns(2)
            amount = a.number_input(f"{day} · 可用分钟", 0, 1440, profile.availability[day]["minutes"], step=15)
            devices = b.multiselect(f"{day} · 可用设备", DEVICES, default=profile.availability[day]["devices"])
            availability[day] = {"minutes": amount, "devices": devices}
        confirmed = st.checkbox("我确认保存以上学习档案")
        if st.form_submit_button("保存档案", type="primary"):
            updated = StudyProfile(goals, hours, speed, preference, maximum, levels, priorities, availability)
            commit(lambda: db.save_profile(updated, expected_version=version, confirmed=confirmed), "学习档案已保存。")


def task_fields(task=None, prefix="new"):
    """新建和编辑共用表单字段，减少重复代码；每个组件用独立 key。"""
    current = task or {}
    title = st.text_input("任务标题", current.get("title", ""), max_chars=120, key=f"{prefix}_title")
    a, b = st.columns(2)
    subject = a.selectbox("科目", SUBJECTS, index=SUBJECTS.index(current.get("subject", "Python")), key=f"{prefix}_subject")
    due = b.date_input("截止日期", date.fromisoformat(current["due_date"]) if task else date.today(), key=f"{prefix}_due")
    duration = a.number_input("预计学习时间（分钟）", 1, 1440, current.get("estimated_minutes", 45), key=f"{prefix}_estimate")
    priority = b.selectbox("优先级", PRIORITIES, index=PRIORITIES.index(current.get("priority", "中")), key=f"{prefix}_priority")
    status = a.selectbox("状态", STATUSES, index=STATUSES.index(current.get("status", "待开始")), key=f"{prefix}_status")
    computer = b.checkbox("这项任务需要电脑", bool(current.get("requires_computer", False)), key=f"{prefix}_computer")
    notes = st.text_area("任务备注", current.get("notes", ""), max_chars=2000, key=f"{prefix}_notes")
    return TaskInput(title, subject, due.isoformat(), duration, priority, status, computer, notes)


def task_rows(tasks, sessions):
    totals = {}
    for session in sessions:
        totals[session["task_id"]] = totals.get(session["task_id"], 0) + session["minutes"]
    return [{"编号": t["id"], "任务": t["title"], "科目": t["subject"], "状态": t["status"], "截止日期": t["due_date"],
             "优先级": t["priority"], "预计分钟": t["estimated_minutes"], "实际分钟": totals.get(t["id"], 0),
             "需要电脑": bool(t["requires_computer"])} for t in tasks]


def tasks_page(db):
    page_intro("03", "从一件小事开始", "把一个大目标，拆成今天能完成的一步。", "ONE TASK AT A TIME")
    tasks = db.get_tasks()
    with st.expander("＋ 创建任务", expanded=not tasks):
        with st.form("create_task", clear_on_submit=False):
            task = task_fields()
            confirmed = st.checkbox("我确认创建以上任务", key="create_confirm")
            if st.form_submit_button("创建任务", type="primary"):
                commit(lambda: db.create_task(task, confirmed=confirmed), "任务已创建。",
                       clear_fields=tuple(f"new_{field}" for field in ("title", "subject", "due", "estimate", "priority", "status", "computer", "notes")) + ("create_confirm",))
    section_heading("01", "你的任务", f"{len(tasks)} 项 · 每一步都算数")
    a, b = st.columns(2)
    subject_filter = a.selectbox("按科目筛选", ("全部",) + SUBJECTS)
    status_filter = b.selectbox("按状态筛选", ("全部",) + STATUSES)
    visible = [t for t in tasks if (subject_filter == "全部" or t["subject"] == subject_filter) and (status_filter == "全部" or t["status"] == status_filter)]
    if not visible:
        empty_state("给想法一个起点", "还没有符合条件的任务。展开上方表单，写下一件可以完成的小事。")
        return
    st.dataframe(task_rows(visible, db.get_sessions()), hide_index=True, width="stretch")
    by_id = {t["id"]: t for t in visible}
    selected = st.selectbox("选择要编辑的任务", list(by_id), format_func=lambda i: f"#{i} · {by_id[i]['title']}", key="edit_selection")
    current = by_id[selected]
    prefix = f"edit_{selected}_{current['version']}"
    with st.expander("编辑任务 / 标记完成", expanded=True):
        with st.form(prefix):
            task = task_fields(current, prefix)
            confirmed = st.checkbox("我确认保存以上任务修改", key=f"{prefix}_confirm")
            if st.form_submit_button("保存任务修改", type="primary"):
                commit(lambda: db.update_task(selected, task, expected_version=current["version"], confirmed=confirmed), "任务修改已保存。")
    with st.expander("删除任务"):
        st.warning(f"即将删除 #{selected}：{current['title']}。任务将从任务列表隐藏，已有学习记录和变更历史仍会保留。")
        with st.form(f"delete_{prefix}"):
            confirmed = st.checkbox("我确认删除这个任务", key=f"{prefix}_delete_confirm")
            if st.form_submit_button("删除任务"):
                commit(lambda: db.delete_task(selected, expected_version=current["version"], confirmed=confirmed), "任务已删除，已有学习记录保留。")


def records_page(db):
    page_intro("04", "把努力留下来", "学习结束后，记录真实投入的时间。一天可以有多次记录。", "THE WORK YOU PUT IN")
    tasks = db.get_tasks()
    if tasks:
        task_lookup = {t["id"]: t for t in tasks}
        with st.form("record_session", clear_on_submit=False):
            selected = st.selectbox("关联任务", list(task_lookup), format_func=lambda i: f"#{i} · {task_lookup[i]['title']}", key="record_task")
            a, b = st.columns(2)
            day = a.date_input("实际学习日期", date.today(), max_value=date.today(), key="record_date")
            duration = b.number_input("实际学习时间（分钟）", 1, 1440, 30, key="record_minutes")
            note = st.text_input("学习记录备注", max_chars=1000, key="record_note")
            confirmed = st.checkbox("我确认这次学习确实发生并保存记录", key="record_confirm")
            if st.form_submit_button("保存学习记录", type="primary"):
                commit(lambda: db.log_session(selected, day.isoformat(), duration, note, confirmed=confirmed), "真实学习记录已保存。",
                       clear_fields=("record_task", "record_date", "record_minutes", "record_note", "record_confirm"))
    else:
        empty_state("先有行动，再留下记录", "创建一个学习任务，真正学习之后，再回来记录用时。", "✎")
        st.button("去创建学习任务 ↗", on_click=go_to, args=("学习任务",), key="records_to_tasks")
    sessions = db.get_sessions()
    if not sessions:
        if tasks:
            empty_state("第一页，等你写下", "还没有实际学习记录。完成一次学习后，填写上方表单即可。", "✎")
        return
    st.dataframe([{"编号": s["id"], "日期": s["study_date"], "任务": s["task_title"], "科目": s["subject"], "分钟": s["minutes"],
                   "备注": s["note"], "任务已删除": bool(s["deleted_at"])} for s in sessions], hide_index=True, width="stretch")
    with st.expander("纠正误记的学习时间"):
        st.caption("删除错误记录后，可以重新填写正确记录。删除学习记录会相应更新统计。")
        session_lookup = {s["id"]: s for s in sessions}
        selected = st.selectbox("选择错误记录", list(session_lookup), format_func=lambda i: f"#{i} · {session_lookup[i]['study_date']} · {session_lookup[i]['minutes']} 分钟 · {session_lookup[i]['task_title']}")
        with st.form(f"delete_session_{selected}"):
            confirmed = st.checkbox("我确认删除这条学习记录", key=f"session_delete_confirm_{selected}")
            if st.form_submit_button("删除学习记录"):
                commit(lambda: db.delete_session(selected, confirmed=confirmed), "错误学习记录已删除。")


def progress_page(db):
    profile, version = db.get_study_profile()
    with st.container(key="dashboard-hero"):
        left, right = st.columns([1.5, 1], gap="large")
        with left:
            st.markdown('''<div class="hero-copy"><div class="eyebrow">MAKE ROOM FOR YOUR NEXT CHAPTER</div>
                <h1>把想学的，<br>变成<span class="hero-accent">做到的。</span></h1>
                <p>为有限的时间，留一份清晰的安排。<br>从一个小任务开始，慢慢走向你想成为的自己。</p></div>''', unsafe_allow_html=True)
            with st.container(key="hero-actions"):
                a, b = st.columns([1, 1])
                a.button("＋ 创建学习任务", type="primary", on_click=go_to, args=("学习任务",), key="hero_create", width="stretch")
                b.button("设置学习档案 ↗", on_click=go_to, args=("学习档案",), key="hero_profile", width="stretch")
            st.markdown('<div class="hero-note">小步前进，也是在前进。</div>', unsafe_allow_html=True)
        with right:
            learning_illustration()
    availability_strip(profile, bool(version))
    section_heading("01", "这一周，有据可查", "只统计你真实记录的学习")
    _, date_column = st.columns([2, 1])
    day = date_column.date_input("查看哪一周", date.today())
    tasks, sessions = db.get_tasks(include_deleted=True), db.get_sessions()
    progress = get_progress(tasks, sessions, day)
    st.caption(f"{progress['start']} 至 {progress['end'] - timedelta(days=1)} · 周一开始")
    a, b, c = st.columns(3)
    rate = progress["completion_rate"]
    a.metric("到期任务完成率", "—" if rate is None else f"{rate:.0%}", help="本周截止的未删除任务中，目前已完成任务的比例。没有到期任务时显示破折号。查看过去周时也按当前任务状态计算，不是当时快照。")
    b.metric("实际时长", f"{progress['actual_minutes'] / 60:.1f} 小时", help=f"精确时长：{progress['actual_minutes']} 分钟。按实际学习日期统计，包括已删除任务的学习记录。")
    c.metric("已完成任务", f"{progress['completed_count']} / {progress['task_count']}", help="已完成数量 / 本周到期的未删除任务数量。")
    st.caption("完成率依据任务当前状态；历史时长依据原始学习日期。预计时长不计入实际学习时间。")
    if progress["subjects"]:
        section_heading("02", "时间花在了哪里", "各科目实际投入")
        chart = [{"科目": subject, "实际分钟": amount} for subject, amount in progress["subjects"].items()]
        st.bar_chart(chart, x="科目", y="实际分钟", color="#df6045")
        st.dataframe([{"科目": s, "实际分钟": m, "投入比例": f"{progress['subject_shares'][s]:.1%}"} for s, m in progress["subjects"].items()], hide_index=True, width="stretch")
    else:
        empty_state("努力会在这里留下痕迹", "这周还没有学习记录。真实学习后记录一次用时，就能看到科目投入与每周变化。", "✎")
    if progress["weekly_history"]:
        section_heading("03", "回头看，已经走了一段", "每周真实学习历史")
        st.bar_chart([{"周一日期": w, "实际分钟": m} for w, m in progress["weekly_history"].items()], x="周一日期", y="实际分钟", color="#719582")
        st.caption("只显示有记录的周；没有记录的周不等于没有学习。")
    section_heading("04" if progress["weekly_history"] else "02", "接下来，做一点什么", "行动与方向")
    todo_column, goal_column = st.columns([1.3, 1], gap="large")
    with todo_column:
        st.subheader("本周待办")
        if progress["incomplete"]:
            st.dataframe(task_rows(progress["incomplete"], sessions), hide_index=True, width="stretch")
        else:
            empty_state("留一点空间，给下一步", "这周没有未完成的到期任务。你可以选一件小事，开始下一段学习。")
        st.button("查看全部任务 ↗", on_click=go_to, args=("学习任务",), key="overview_to_tasks")
    with goal_column:
        if profile.goals.strip():
            st.markdown(f'<div class="goal-sheet"><h3>你的方向。</h3><p>{escape(profile.goals)}</p><small>学习目标 · 已保存</small></div>', unsafe_allow_html=True)
            st.caption("目标尚未绑定可衡量的里程碑，不计算完成百分比。")
        else:
            empty_state("目标，等你来决定", "你还没有设置学习目标。可以先想一想自己的需求，再到学习档案中填写并确认保存。", "↗")
            st.button("去制定学习目标 ↗", on_click=go_to, args=("学习档案",), key="overview_to_goals")
    if progress["overdue"]:
        st.subheader("所选日期之前的逾期任务")
        st.dataframe(task_rows(progress["overdue"], sessions), hide_index=True, width="stretch")
    events = db.get_events(include_snapshot=False)
    if events:
        with st.expander("任务变更历史（时间为 UTC）"):
            st.dataframe([{"任务编号": e["task_id"], "操作": e["action"], "时间": e["created_at"]} for e in events], hide_index=True, width="stretch")


def main():
    st.set_page_config(page_title="StudyPilot · 把想学的变成做到的", page_icon="↗", layout="wide")
    for key in st.session_state.pop("clear_submitted_fields", ()):
        st.session_state.pop(key, None)
    apply_theme()
    masthead()
    legacy_path = Path(os.getenv("STUDYPILOT_DB") or ROOT / "data" / "studypilot.db")
    try:
        auth = AuthStore(os.getenv("STUDYPILOT_AUTH_DIR") or legacy_path.parent / "accounts")
        with st.container(key="auth-shell"):
            account = login_gate(auth)
    except (sqlite3.Error, OSError, ValidationError):
        st.error("账号服务暂时不可用，请稍后重试。")
        return
    if account is None:
        return
    account_bar(auth, account)
    # 每次请求从账号数据库读取角色；环境变量和浏览器参数不能授予开发者身份。
    developer_mode = account.role == "developer"
    pages = ("学习概览", "学习档案", "学习任务", "学习计划", "学习记录", "账号设置", "AI 助手")
    if developer_mode:
        pages += ("开发进度",)
    # 关闭开发模式后，旧会话不能继续停留在开发页；未知页面也回到首页。
    if st.session_state.get("navigation") not in pages:
        st.session_state["navigation"] = "学习概览"
    with st.container(key="top-navigation"):
        page = st.radio("导航", pages, key="navigation", horizontal=True, label_visibility="collapsed")
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    try:
        db = auth.study_database(st.session_state.get("auth_token"))
        with st.container(key=f"page-content-{pages.index(page)}"):
            if page == "学习档案":
                profile_page(db)
            elif page == "学习任务":
                tasks_page(db)
            elif page == "学习记录":
                records_page(db)
            elif page == "学习计划":
                schedule_page(db)
            elif page == "学习概览":
                progress_page(db)
            elif page == "账号设置":
                account_settings(auth, account)
            elif page == "AI 助手":
                agent_page(auth, account)
            elif page == "开发进度" and developer_mode:
                page_intro("DEV", "功能与维护", "查看已启用功能与后续维护事项。此页面仅对开发者开放。", "PRODUCT STATUS")
                st.write("✅ 学习管理：档案、任务、完成状态、学习记录和进度统计。")
                st.write("✅ 每周计划：按可用时间与设备安排任务，核对后保存；无法安排的任务会说明原因。")
                st.write("✅ AI 助手：学习查询、目标与计划建议，所有更改由用户确认后执行。服务需由维护者启用。")
                st.write("后续维护事项：目标里程碑、考试优先级与统计体验。")
                st.info("AI 助手只提供读取与提案工具。模型不能确认执行，学习计划仍由规则算法生成。")
    except AuthError:
        st.error("登录已失效，请退出后重新登录。")
        st.stop()
    except (ValidationError, sqlite3.Error, OSError) as exc:
        if isinstance(exc, ValidationError):
            st.error(str(exc))
        else:
            st.error("暂时无法读取学习数据，请稍后重试。若问题持续，请联系维护人员。")
        st.stop()
    ai_enabled = ai_configured()
    footer(ai_enabled)
    with st.expander("使用说明"):
        if ai_enabled:
            st.info("AI 助手已开放，可在同意使用相关学习资料后发起对话。")
        else:
            st.info("AI 未启用：助手暂未开放。学习档案、任务、计划和统计仍可正常使用。")
        st.caption("规则排课已启用。AI 助手可读取学习数据、生成修改提案，只有用户核对并确认后才执行；不会自动记入计划时长或修改账号权限。")


if __name__ == "__main__":
    main()
