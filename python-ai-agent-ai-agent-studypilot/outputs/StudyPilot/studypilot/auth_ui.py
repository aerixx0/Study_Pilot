"""账号界面：只有验证通过的会话才能进入学习页面。"""

import streamlit as st
from datetime import datetime
import json

from .auth import AuthError, AVATARS, USERNAME_MAX_LENGTH, normalize_username
from .database import ConfirmationRequired, ConflictError
from .models import ValidationError
from .theme import page_intro


def clear_account_state():
    """退出或切换账号时清空整个页面草稿，避免把上一人的输入带给下一人。"""
    for key in list(st.session_state):
        del st.session_state[key]


def show_recovery_receipt(username, code, message):
    clear_account_state()
    st.session_state["recovery_receipt"] = {"username": username, "code": code, "message": message}
    st.rerun()


def matching_passwords(password, confirmation):
    if password != confirmation:
        raise ValidationError("两次输入的密码不一致。")


def login_gate(auth):
    """返回服务端认证后的 Account；匿名请求只渲染登录页，不创建学习数据库。"""
    token = st.session_state.get("auth_token")
    account = auth.authenticate(token)
    if account:
        return account
    if token:
        clear_account_state()
        st.session_state["auth_notice"] = "登录已过期或已在其他位置退出，请重新登录。"
    page_intro("HELLO", "欢迎使用 StudyPilot", "登录账号，管理学习目标、任务和进度。", "YOUR OWN LEARNING SPACE")
    if "auth_notice" in st.session_state:
        st.info(st.session_state.pop("auth_notice"))
    receipt = st.session_state.get("recovery_receipt")
    if receipt:
        st.success(receipt["message"])
        st.write(f"用户名：{receipt['username']}")
        st.warning("请现在保存恢复码。离开后无法再次查看；忘记密码时，需要用户名和恢复码一起重置。旧恢复码已失效。")
        st.code(receipt["code"], language=None)
        st.caption("请放在你自己的密码管理器或安全位置，不要分享给他人。")
        if st.button("我已妥善保存，去登录", type="primary", key="recovery_ack"):
            clear_account_state()
            st.rerun()
        return None

    mode = st.radio("账号操作", ("登录", "注册账号", "找回密码"), horizontal=True, key="auth_mode")
    try:
        if mode == "登录":
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("用户名", max_chars=USERNAME_MAX_LENGTH, key="login_username")
                password = st.text_input("密码", type="password", max_chars=128, key="login_password")
                if st.form_submit_button("登录", type="primary", width="stretch"):
                    token = auth.login(username, password)
                    clear_account_state()
                    st.session_state["auth_token"] = token
                    st.rerun()
            st.caption("会话最长 12 小时，30 分钟无操作会过期。刷新页面或打开新标签页后，请重新登录；已保存的数据不会丢失。")
        elif mode == "注册账号":
            with st.form("registration_form", clear_on_submit=False):
                username = st.text_input("用户名", max_chars=USERNAME_MAX_LENGTH, key="register_username", help="1–64 个字符，支持中文、字母、数字、空格和常用符号；首尾空格自动去除，英文不区分大小写。无需真实姓名。")
                password = st.text_input("设置密码", type="password", max_chars=128, key="register_password", help="15–128 个字符，建议使用容易记住的长短语。")
                repeat = st.text_input("再次输入密码", type="password", max_chars=128, key="register_repeat")
                confirmed = st.checkbox("我确认创建账号", key="register_confirm")
                if st.form_submit_button("创建账号", type="primary", width="stretch"):
                    matching_passwords(password, repeat)
                    account, code = auth.register(username, password, confirmed=confirmed)
                    show_recovery_receipt(account.username, code, "账号已创建。请先保存恢复码，再登录。")
            st.caption("使用用户名和密码创建账号。注册后请妥善保存恢复码，用于找回密码。")
        else:
            st.caption("输入注册或上次改密时保存的恢复码。密码找回目前仅支持恢复码，不支持邮箱或短信验证。")
            with st.form("reset_form", clear_on_submit=False):
                username = st.text_input("用户名", max_chars=USERNAME_MAX_LENGTH, key="reset_username")
                code = st.text_input("恢复码", type="password", max_chars=128, key="reset_code")
                password = st.text_input("新密码", type="password", max_chars=128, key="reset_password")
                repeat = st.text_input("再次输入新密码", type="password", max_chars=128, key="reset_repeat")
                confirmed = st.checkbox("我确认重置密码并退出该账号的所有会话", key="reset_confirm")
                if st.form_submit_button("重置密码", type="primary", width="stretch"):
                    matching_passwords(password, repeat)
                    next_code = auth.reset_password(username, code, password, confirmed=confirmed)
                    show_recovery_receipt(normalize_username(username), next_code, "密码已重置，所有旧会话已退出。请保存新的恢复码。")
    except (AuthError, ValidationError, ConfirmationRequired) as exc:
        st.error(str(exc))
    return None


def account_bar(auth, account):
    with st.container(key="account-bar"):
        left, right = st.columns([6, 1])
        personal = auth.get_personal_profile(st.session_state.get("auth_token"))
        name = personal["nickname"]
        label = name if name == account.username else f"{name}（{account.username}）"
        left.caption(f"{personal['avatar']} 已登录：{label} · {'开发者' if account.role == 'developer' else '个人学习空间'}")
        if right.button("退出登录", key="logout", width="stretch"):
            auth.logout(st.session_state.get("auth_token"))
            clear_account_state()
            st.rerun()


def account_settings(auth, account):
    page_intro("ACCOUNT", "你的资料，你来决定", "管理个人资料、登录安全和自己的学习数据。", "ACCOUNT SETTINGS")
    st.write(f"用户名：{account.username}")
    personal = auth.get_personal_profile(st.session_state.get("auth_token"))
    st.subheader("个人资料")
    prefix = f"personal_{personal['version']}"
    with st.form(f"{prefix}_form", clear_on_submit=False):
        nickname = st.text_input("昵称", value=personal["nickname"], max_chars=64, key=f"{prefix}_nickname", help="显示在个人学习空间中，可以与登录用户名不同。")
        avatar = st.selectbox("头像标识", AVATARS, index=AVATARS.index(personal["avatar"]), key=f"{prefix}_avatar")
        bio = st.text_input("个性签名", value=personal["bio"], max_chars=120, key=f"{prefix}_bio", placeholder="写一句想对自己说的话")
        confirmed = st.checkbox("我确认保存个人资料", key=f"{prefix}_confirm")
        if st.form_submit_button("保存个人资料", type="primary"):
            try:
                auth.save_personal_profile(st.session_state.get("auth_token"), nickname, avatar, bio,
                                           expected_version=personal["version"], confirmed=confirmed)
                st.session_state["notice"] = "个人资料已保存。"
                st.rerun()
            except (AuthError, ValidationError, ConflictError, ConfirmationRequired) as exc:
                st.error(str(exc))
    st.subheader("账号与安全")
    st.caption("密码更新后，所有旧会话与旧恢复码都会失效，请保存新的恢复码。")
    with st.form("change_password_form", clear_on_submit=False):
        current = st.text_input("当前密码", type="password", max_chars=128, key="change_current")
        password = st.text_input("新密码", type="password", max_chars=128, key="change_password")
        repeat = st.text_input("再次输入新密码", type="password", max_chars=128, key="change_repeat")
        confirmed = st.checkbox("我确认修改密码并退出所有会话", key="change_confirm")
        if st.form_submit_button("更新密码", type="primary"):
            try:
                matching_passwords(password, repeat)
                code = auth.change_password(st.session_state.get("auth_token"), current, password, confirmed=confirmed)
                show_recovery_receipt(account.username, code, "密码已更新。请保存新恢复码，然后重新登录。")
            except (AuthError, ValidationError, ConfirmationRequired) as exc:
                st.error(str(exc))
    st.caption("忘记或遗失恢复码时，可以在记得当前密码的情况下，通过更新密码获取新的恢复码。")
    with st.expander("登录会话管理"):
        st.caption("查看当前有效的登录会话；同一设备可能存在多个会话。")
        sessions = auth.get_sessions(st.session_state.get("auth_token"))
        st.dataframe([{"会话": "当前会话" if session["current"] else "其他会话",
                       "登录时间": datetime.fromtimestamp(session["created_at"]).strftime("%Y-%m-%d %H:%M"),
                       "最近活动": datetime.fromtimestamp(session["last_seen"]).strftime("%Y-%m-%d %H:%M")}
                      for session in sessions], hide_index=True, width="stretch")
        with st.form("revoke_sessions_form", clear_on_submit=False):
            confirmed = st.checkbox("我确认退出其他登录会话", key="revoke_sessions_confirm")
            if st.form_submit_button("退出其他会话"):
                try:
                    count = auth.revoke_other_sessions(st.session_state.get("auth_token"), confirmed=confirmed)
                    st.session_state["notice"] = f"已退出 {count} 个其他会话，当前登录保留。"
                    st.rerun()
                except (AuthError, ConfirmationRequired) as exc:
                    st.error(str(exc))
    with st.expander("个人数据与导出"):
        st.caption("导出个人资料、学习档案、任务、真实学习记录和已保存计划。文件不含密码、恢复码或登录令牌。导出文件可供查阅和留存，目前不支持导入恢复。")
        # 在点击时重新验证并生成；闭合面板与普通重绘不读取全部个人数据。
        token = st.session_state.get("auth_token")
        def export_on_download():
            return json.dumps(auth.export_account(token), ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button("导出我的数据（JSON）", export_on_download,
                           file_name="studypilot-data.json", mime="application/json", on_click="ignore")
    st.caption("StudyPilot · 学习目标、任务计划与进度记录")
