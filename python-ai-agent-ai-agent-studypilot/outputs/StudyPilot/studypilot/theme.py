"""展示层：样式与小型 HTML 组件，不读写学习数据。"""

import base64
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from .models import DAYS


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def apply_theme():
    """本地 CSS 和 SVG 保证离线可用；原生表单继续处理真实交互。"""
    st.markdown(f"<style>{(ASSETS / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def masthead():
    # 主题是浏览器外观偏好；纯前端切换不会重跑或提交正在填写的表单。
    # 同名同定义注册是幂等的；每个独立 Runtime（含 AppTest）均需注册。
    switcher = st.components.v2.component(
        "pilot_theme_switcher",
        html=(ASSETS / "theme-switcher.html").read_text(encoding="utf-8"),
        js=(ASSETS / "theme-switcher.js").read_text(encoding="utf-8"),
        isolate_styles=False,
    )
    switcher(data={"date": f"{date.today():%Y.%m.%d}"}, key="appearance", height="content")


def page_intro(number, title, subtitle, english):
    st.markdown(f"""<div class="page-intro"><div class="eyebrow">{escape(number)} / {escape(english)}</div>
        <h1>{escape(title)}<span class="accent-dot">.</span></h1><p>{escape(subtitle)}</p></div>""", unsafe_allow_html=True)


def section_heading(number, title, detail=""):
    st.markdown(f"""<div class="section-heading"><div><span class="section-number">{escape(number)}</span>
        <h2>{escape(title)}</h2></div><span class="section-detail">{escape(detail)}</span></div>""", unsafe_allow_html=True)


def empty_state(title, description, symbol="↗"):
    st.markdown(f"""<div class="empty-state"><span class="empty-symbol" aria-hidden="true">{escape(symbol)}</span>
        <div><h3>{escape(title)}</h3><p>{escape(description)}</p></div></div>""", unsafe_allow_html=True)


def learning_illustration():
    encoded = base64.b64encode((ASSETS / "learning-map.svg").read_bytes()).decode("ascii")
    st.markdown(f'<div class="learning-figure"><img src="data:image/svg+xml;base64,{encoded}" alt="一本笔记、一台电脑和一条向前的学习路线的原创插画"><span>SMALL STEPS. REAL PROGRESS.</span></div>', unsafe_allow_html=True)


def availability_strip(profile, saved):
    """展示用户档案中的约束，不把它伪装成已经生成的任务安排。"""
    cells = []
    for day in DAYS:
        slot = profile.availability[day]
        amount = slot["minutes"]
        hours = f"{amount / 60:g} 小时" if amount else "留给日常"
        devices = " / ".join(slot["devices"]) if amount else "无额外学习时间"
        cells.append(f'<div class="day-cell {"available" if amount else "rest"}"><span>{escape(day)}</span><strong>{hours}</strong><small>{escape(devices)}</small></div>')
    label = "已保存的学习档案" if saved else "默认档案草稿 · 可修改"
    st.markdown(f'<div class="rhythm-header"><h3>按你的节奏来。</h3><span>每周 {profile.weekly_hours:g} 小时 · {label}</span></div><div class="week-strip">{"".join(cells)}</div>', unsafe_allow_html=True)


def footer(ai_configured):
    status = "AI 已配置 · 修改先审阅" if ai_configured else "AI 未启用 · 本地功能正常可用"
    st.markdown(f'<div class="site-footer"><span class="footer-brand">StudyPilot.</span><span>本地保存 · 修改需确认</span><span class="footer-status">{status}</span></div>', unsafe_allow_html=True)
