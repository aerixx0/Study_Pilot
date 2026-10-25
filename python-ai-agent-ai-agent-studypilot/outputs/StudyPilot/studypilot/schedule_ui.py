"""学习计划页面：生成预览、说明约束、确认保存，绝不自动记入实际用时。"""

from datetime import date

import streamlit as st

from .database import ConfirmationRequired, ConflictError
from .models import ValidationError
from .progress import week_bounds
from .theme import page_intro


def render_plan(plan):
    a, b, c = st.columns(3)
    a.metric("每周预算", f"{plan['budget_minutes']} 分钟")
    b.metric("本周已记录", f"{plan['actual_minutes']} 分钟")
    c.metric("本次安排", f"{plan['planned_minutes']} 分钟")
    st.caption(f"{plan['week_start']} 至 {plan['week_end']} · 生成日期 {plan['as_of']} · 预算剩余 {plan['unused_minutes']} 分钟")
    if plan["actual_minutes"] > plan["budget_minutes"]:
        st.warning("本周真实用时已超过预算，本次不会继续增加安排。")
    if plan["entries"]:
        st.dataframe([{"日期": entry["date"], "任务": entry["title"], "科目": entry["subject"],
                       "计划分钟": entry["minutes"], "设备要求": "电脑" if entry["requires_computer"] else "任一可用设备"}
                      for entry in plan["entries"]], hide_index=True, width="stretch")
    else:
        st.info("本周没有可安排的任务。可以检查任务截止日期、已记录用时和可用设备。")
    with st.expander("每日容量与用时", expanded=True):
        st.dataframe([{"日期": day["date"], "星期": day["weekday"], "可用分钟": day["available_minutes"],
                       "已记录分钟": day["actual_minutes"], "计划分钟": day["planned_minutes"],
                       "设备": " / ".join(day["devices"])} for day in plan["days"]], hide_index=True, width="stretch")
        st.bar_chart({"日期": [day["date"][5:] for day in plan["days"]],
                      "已记录": [day["actual_minutes"] for day in plan["days"]],
                      "计划": [day["planned_minutes"] for day in plan["days"]]}, x="日期", y=["已记录", "计划"])
    if plan["unscheduled"]:
        st.warning("部分任务未能全部安排；已安排的部分仍可保存。")
        st.dataframe([{"任务": item["title"], "已安排分钟": item["planned_minutes"],
                       "尚余分钟": item["remaining_minutes"], "原因": item["reason"],
                       "可调整方式": item.get("suggestion", "核对时间、设备和截止日期后重新预览。")}
                      for item in plan["unscheduled"]], hide_index=True, width="stretch")
    if plan["notices"]:
        with st.expander("无需新增安排的任务"):
            for notice in plan["notices"]:
                st.write(f"{notice['title']}：{notice['reason']}")


def schedule_page(db):
    page_intro("PLAN", "给这一周，一个安排", "在真实可用的时间里，一步步完成任务。", "YOUR WEEKLY PLAN")
    st.caption("计划优先安排临近截止日期的任务，并结合科目优先级、可用设备和单次学习时长。你可核对安排后决定是否保存。")
    st.info("每周预算包含当周已记录的真实用时；过去日期不再新增安排。其他周已保存的未来安排会预留任务时长。计划不会自动完成任务或记入真实学习时间。")
    selected = st.date_input("选择计划所在周", value=date.today(), key="schedule_week")
    start, end = week_bounds(selected)
    saved, version = db.get_schedule(selected)
    _, profile_version = db.get_study_profile()
    if not profile_version:
        st.warning("请先到学习档案确认保存每周预算、每日时间与设备，再生成计划。")
    if st.button("生成计划预览", type="primary", disabled=not profile_version or end <= date.today(), key="generate_schedule"):
        try:
            data = db.preview_schedule(selected)
            st.session_state["schedule_preview"] = dict(data=data, version=version)
            st.session_state.pop("schedule_confirm", None)
        except (ValidationError, ConflictError) as exc:
            st.error(str(exc))
    pending = st.session_state.get("schedule_preview")
    preview = pending if pending and pending["data"]["week_start"] == start.isoformat() else None
    if preview:
        st.subheader("待确认的计划预览")
        render_plan(preview["data"])
        if preview["data"]["entries"]:
            with st.form("save_schedule_form", clear_on_submit=False):
                label = "我确认替换本周已保存的计划" if preview["version"] else "我确认保存以上学习计划"
                confirmed = st.checkbox(label, key="schedule_confirm")
                if st.form_submit_button("确认保存计划"):
                    try:
                        db.save_schedule(preview["data"], expected_version=preview["version"], confirmed=confirmed)
                        st.session_state.pop("schedule_preview", None)
                        st.session_state["notice"] = "学习计划已保存，真实学习记录保持不变。"
                        st.rerun()
                    except (ConfirmationRequired, ConflictError, ValidationError) as exc:
                        st.error(str(exc))
    if saved:
        with st.expander("已保存的本周计划", expanded=not preview):
            st.caption("这里展示保存时的安排。任务、档案或真实用时变化后，请重新生成预览；新计划经确认后替换本周计划。")
            if end > date.today() and profile_version:
                current = db.preview_schedule(selected)
                if current["source_hash"] != saved["source_hash"] or current["as_of"] != saved["as_of"]:
                    st.warning("计划生成后，排课输入或日期已有变化。建议重新生成并核对。")
            render_plan(saved)
            with st.form(f"delete_schedule_{start}_{version}", clear_on_submit=False):
                confirmed = st.checkbox("我确认删除本周计划，保留任务和真实学习记录", key=f"delete_schedule_confirm_{start}_{version}")
                if st.form_submit_button("删除本周计划"):
                    try:
                        db.delete_schedule(selected, expected_version=version, confirmed=confirmed)
                        st.session_state.pop("schedule_preview", None)
                        st.session_state["notice"] = "本周计划已删除，任务与真实学习记录保留。"
                        st.rerun()
                    except (ConfirmationRequired, ConflictError) as exc:
                        st.error(str(exc))
    elif not preview:
        st.caption("这一周尚未保存学习计划。生成预览不会写入计划记录。")
