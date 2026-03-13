from __future__ import annotations

import glob
import inspect
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import streamlit as st
import engine

try:
    import timetable
    _HAS_TIMETABLE = True
except Exception:
    timetable = None
    _HAS_TIMETABLE = False

try:
    import report_generator
    _HAS_REPORT_GEN = True
except Exception:
    report_generator = None
    _HAS_REPORT_GEN = False

# ── Session state init ────────────────────────────────────────────────────────
st.session_state.setdefault("ui_theme", "light")

def _ensure_auth_state() -> None:
    if not isinstance(st.session_state.get("auth"), dict):
        st.session_state["auth"] = {}
    a = st.session_state["auth"]
    for k, v in [("logged_in", False), ("role", "auditor"), ("username", ""), ("tenant_id", "default")]:
        a.setdefault(k, v)

_ensure_auth_state()

def _rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.stop()

# ── CSS helpers ───────────────────────────────────────────────────────────────
def inject_enterprise_css():
    # Load Google Fonts via <link> (non-blocking) instead of CSS @import (render-blocking)
    st.markdown(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600;1,700&family=Inter:wght@300;400;500;600;700&display=swap">',
        unsafe_allow_html=True,
    )
    st.markdown("""<style>
    /* ── Global ── */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    .stApp { background: #f0f2f7 !important; }
    .block-container { max-width: 1280px !important; padding: 1.5rem 2rem 3rem !important; }
    footer, #MainMenu { visibility: hidden; }

    /* ══ Sidebar — dark navy, matching login ══ */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg,#0a1628 0%,#0d1f40 60%,#0f2a52 100%) !important;
        border-right: none !important;
        box-shadow: 4px 0 24px rgba(0,0,0,0.25) !important;
        position: relative !important;
    }
    /* Dot-grid texture */
    section[data-testid="stSidebar"]::before {
        content: '' !important; position: absolute !important;
        inset: 0 !important; pointer-events: none !important; z-index: 0 !important;
        background-image: radial-gradient(rgba(255,255,255,0.04) 1px, transparent 1px) !important;
        background-size: 24px 24px !important;
    }
    /* Green top accent line */
    section[data-testid="stSidebar"]::after {
        content: '' !important; position: absolute !important;
        top: 0 !important; left: 0 !important; right: 0 !important; height: 3px !important;
        background: linear-gradient(90deg,#34d399,#10b981,#059669) !important;
        z-index: 10 !important;
    }
    section[data-testid="stSidebar"] > div { position: relative !important; z-index: 1 !important; }
    section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

    /* Hide radio buttons entirely — we style the label */
    section[data-testid="stSidebar"] input[type="radio"] {
        display: none !important;
    }
    section[data-testid="stSidebar"] .stRadio > div {
        display: flex !important; flex-direction: column !important; gap: 3px !important;
    }
    section[data-testid="stSidebar"] .stRadio label {
        font-size: 14px !important; font-weight: 500 !important;
        padding: 12px 16px !important; border-radius: 12px !important;
        margin: 0 !important; display: flex !important;
        align-items: center !important; gap: 0 !important;
        transition: all .18s ease !important;
        color: #94a3b8 !important; cursor: pointer !important;
        border: 1px solid transparent !important;
        letter-spacing: .1px !important;
    }
    section[data-testid="stSidebar"] .stRadio label:hover {
        background: rgba(255,255,255,0.07) !important;
        color: #e2e8f0 !important;
        border-color: rgba(255,255,255,0.08) !important;
    }
    section[data-testid="stSidebar"] .stRadio label[data-checked="true"],
    section[data-testid="stSidebar"] .stRadio label:has(input:checked) {
        background: rgba(52,211,153,0.14) !important;
        color: #34d399 !important; font-weight: 700 !important;
        border-color: rgba(52,211,153,0.25) !important;
        box-shadow: 0 2px 12px rgba(52,211,153,0.12) !important;
    }
    section[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {
        font-size: 14px !important; font-weight: inherit !important;
        color: inherit !important; margin: 0 !important; line-height: 1 !important;
    }

    /* Logout button */
    section[data-testid="stSidebar"] button {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        color: #94a3b8 !important; border-radius: 10px !important;
        font-size: 13px !important; font-weight: 600 !important;
        transition: all .18s !important;
    }
    section[data-testid="stSidebar"] button:hover {
        background: rgba(239,68,68,0.15) !important;
        border-color: rgba(239,68,68,0.35) !important;
        color: #fca5a5 !important;
    }

    /* Sidebar logo card */
    .sb-logo {
        background: linear-gradient(135deg,#34d399 0%,#10b981 50%,#059669 100%) !important;
        border-radius: 14px !important; padding: 18px 16px !important;
        margin-bottom: 6px !important;
        box-shadow: 0 4px 20px rgba(16,185,129,0.30) !important;
    }
    .sb-logo-title { font-family:'Cormorant Garamond',serif !important;
                     font-size:20px !important; font-weight:700 !important;
                     color:#ffffff !important; letter-spacing:.2px !important; }
    .sb-logo-sub   { font-size:11px !important; color:rgba(255,255,255,0.80) !important;
                     margin-top:3px !important; letter-spacing:.3px !important; }

    /* User card */
    .sb-user {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 12px !important; padding: 12px 14px !important;
        margin-bottom: 8px !important;
    }
    .sb-user-name { font-size:14px !important; font-weight:700 !important;
                    color:#e2e8f0 !important; }
    .sb-user-role { font-size:11px !important; color:#4a6a8a !important;
                    margin-top:3px !important; }

    /* Nav section label */
    .sb-nav-label {
        font-size:9px !important; font-weight:800 !important;
        letter-spacing:2.5px !important; text-transform:uppercase !important;
        color:#2a4a6a !important; padding:16px 4px 8px !important;
        display:block !important;
    }
    .sb-divider { border-top: 1px solid rgba(255,255,255,0.06) !important;
                  margin: 10px 0 !important; }

    /* ── Typography ── */
    h1 { font-family: 'Cormorant Garamond', serif !important; font-size: 32px !important;
         font-weight: 700 !important; color: #0a1628 !important; letter-spacing: -0.4px !important; }
    h2 { font-family: 'Cormorant Garamond', serif !important; font-size: 24px !important;
         font-weight: 700 !important; color: #0a1628 !important; }
    h3 { font-size: 15px !important; font-weight: 700 !important; color: #1e293b !important; }
    p, span, li { color: #334155; font-size: 14px; line-height: 1.6; }

    /* ── Inputs ── */
    .stTextInput input, .stTextArea textarea,
    .stSelectbox div[data-baseweb="select"] > div,
    .stMultiSelect div[data-baseweb="select"] > div,
    .stDateInput input {
        background: #ffffff !important; border: 1px solid #dde3ef !important;
        border-radius: 10px !important; color: #0f172a !important;
        font-size: 14px !important; font-family: 'Inter', sans-serif !important;
        box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
        transition: border-color .15s, box-shadow .15s !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #10b981 !important;
        box-shadow: 0 0 0 3px rgba(16,185,129,0.12) !important;
    }

    /* ── Buttons ── */
    .stButton button {
        background: #ffffff !important; color: #1e293b !important;
        border: 1px solid #dde3ef !important; border-radius: 10px !important;
        font-weight: 600 !important; font-size: 13px !important;
        padding: 0.5rem 1.2rem !important;
        box-shadow: 0 1px 3px rgba(15,23,42,0.07) !important;
        transition: all .15s !important; font-family: 'Inter', sans-serif !important;
    }
    .stButton button:hover {
        background: #f0fdf9 !important; border-color: #6ee7b7 !important;
        box-shadow: 0 3px 8px rgba(16,185,129,0.12) !important;
    }
    .stButton button[kind="primary"] {
        background: linear-gradient(135deg,#34d399 0%,#10b981 50%,#059669 100%) !important;
        color: #ffffff !important; border: none !important;
        box-shadow: 0 2px 8px rgba(16,185,129,0.35) !important;
    }
    .stButton button[kind="primary"]:hover {
        background: linear-gradient(135deg,#10b981 0%,#059669 100%) !important;
        box-shadow: 0 4px 14px rgba(5,150,105,0.45) !important;
    }

    /* ── Form submit buttons — green gradient, large ── */
    div[data-testid="stFormSubmitButton"] > button {
        background: linear-gradient(135deg,#34d399 0%,#10b981 50%,#059669 100%) !important;
        color: #ffffff !important; border: none !important;
        border-radius: 12px !important; padding: 14px 28px !important;
        font-size: 15px !important; font-weight: 700 !important;
        letter-spacing: .4px !important; width: 100% !important;
        box-shadow: 0 4px 16px rgba(16,185,129,0.38) !important;
        transition: all .2s ease !important; font-family: 'Inter', sans-serif !important;
        cursor: pointer !important;
    }
    div[data-testid="stFormSubmitButton"] > button:hover {
        background: linear-gradient(135deg,#10b981 0%,#059669 100%) !important;
        box-shadow: 0 7px 24px rgba(5,150,105,0.50) !important;
        transform: translateY(-2px) !important;
    }
    div[data-testid="stFormSubmitButton"] > button:active {
        transform: translateY(0) !important;
    }
    div[data-testid="stFormSubmitButton"] > button p,
    div[data-testid="stFormSubmitButton"] > button span {
        color: #ffffff !important; font-weight: 700 !important; font-size: 15px !important;
    }

    /* ── Forms ── */
    .stForm { background: #ffffff !important; border: 1px solid #e8edf5 !important;
              border-radius: 16px !important; padding: 24px !important;
              box-shadow: 0 2px 8px rgba(15,23,42,0.05) !important; }

    /* ── DataFrames ── */
    div[data-testid="stDataFrame"] {
        background: #ffffff; border: 1px solid #e8edf5;
        border-radius: 14px; overflow: hidden;
        box-shadow: 0 2px 8px rgba(15,23,42,0.05);
    }

    /* ── Metrics ── */
    div[data-testid="metric-container"] {
        background: #ffffff !important; border: 1px solid #e8edf5 !important;
        border-radius: 14px !important; padding: 18px 20px !important;
        box-shadow: 0 2px 8px rgba(15,23,42,0.05) !important;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #ffffff !important; border-radius: 12px !important;
        border: 1px solid #e8edf5 !important; padding: 4px !important; gap: 2px !important;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 9px !important; font-weight: 600 !important;
        font-size: 13px !important; padding: 8px 18px !important; color: #64748b !important;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg,#34d399,#059669) !important; color: #ffffff !important;
    }

    /* ── Expanders ── */
    .streamlit-expanderHeader {
        background: #ffffff !important; border: 1px solid #e8edf5 !important;
        border-radius: 12px !important; font-weight: 600 !important;
        font-size: 14px !important; color: #1e293b !important;
    }

    /* ── Alerts ── */
    .stAlert { border-radius: 12px !important; border: none !important; font-size: 13px !important; }

    /* ── Progress bar ── */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg,#34d399,#059669) !important;
        border-radius: 999px !important;
    }
    .stProgress > div > div > div {
        background: #e8edf5 !important; border-radius: 999px !important;
    }

    /* ── Dividers ── */
    hr { border-color: #e8edf5 !important; margin: 1.5rem 0 !important; }

    /* ── Topbar ── */
    .topbar {
        background: linear-gradient(135deg, #0a1628 0%, #0f2347 60%, #162d55 100%);
        border-radius: 16px; padding: 20px 28px;
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 24px;
        box-shadow: 0 4px 20px rgba(10,22,40,0.22);
        position: relative; overflow: hidden;
    }
    .topbar::before {
        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
        background: linear-gradient(90deg, #34d399, #10b981, #059669);
    }
    .topbar-brand { font-family: 'Cormorant Garamond', serif; font-size: 22px;
                    font-weight: 700; color: #f0f4ff; letter-spacing: -0.2px; }
    .topbar-sub { font-size: 12px; color: #4a6a8a; margin-top: 2px; }
    .topbar-pill {
        background: rgba(52,211,153,0.15); border: 1px solid rgba(52,211,153,0.30);
        border-radius: 999px; padding: 6px 16px;
        font-size: 12px; font-weight: 700; color: #6ee7b7; letter-spacing: .4px;
        display: flex; align-items: center; gap: 7px;
    }
    .topbar-dot { width:8px;height:8px;border-radius:50%;background:#34d399;
                  box-shadow:0 0 8px rgba(52,211,153,0.6); display:inline-block; }

    /* ── Breadcrumb ── */
    .breadcrumb {
        display: inline-flex; align-items: center; gap: 8px;
        font-size: 12px; color: #64748b; font-weight: 600;
        margin: 0 0 18px 0; background: #ffffff;
        padding: 6px 14px; border-radius: 999px;
        border: 1px solid #e8edf5;
        box-shadow: 0 1px 3px rgba(15,23,42,0.05);
    }
    .breadcrumb .sep { color: #cbd5e1; }
    .breadcrumb .current { color: #10b981; font-weight: 700; }

    /* ── Panel ── */
    .panel {
        background: #ffffff; border: 1px solid #e8edf5;
        border-left: 4px solid #10b981; border-radius: 12px;
        padding: 14px 18px; margin-bottom: 16px;
        box-shadow: 0 2px 8px rgba(15,23,42,0.04);
    }
    .panel-title { font-family: 'Cormorant Garamond', serif; font-size: 18px;
                   font-weight: 700; color: #0a1628; }
    .panel-subtitle { font-size: 12px; color: #64748b; margin-top: 3px; }

    /* ── KPI ── */
    .kpi { background:#ffffff; border:1px solid #e8edf5; border-radius:14px;
           padding:18px 20px; box-shadow:0 2px 8px rgba(15,23,42,0.05); }
    .kpi .label { font-size:12px; font-weight:700; color:#64748b;
                  text-transform:uppercase; letter-spacing:.5px; }
    .kpi .value { font-family:'Cormorant Garamond',serif; font-size:34px;
                  font-weight:700; color:#0a1628; line-height:1.1; margin:4px 0; }
    .kpi .meta  { font-size:11px; color:#94a3b8; }

    /* ── Sidebar logo ── */
    .sb-logo {
        background: linear-gradient(135deg,#34d399 0%,#10b981 50%,#059669 100%);
        border-radius: 12px; padding: 16px 14px; margin-bottom: 16px;
        box-shadow: 0 4px 16px rgba(16,185,129,0.30);
    }
    .sb-logo-title { font-family:'Cormorant Garamond',serif; font-size:19px;
                     font-weight:700; color:#ffffff; letter-spacing: 0.2px; }
    .sb-logo-sub   { font-size:11px; color:rgba(255,255,255,0.85); margin-top:3px; }
    .sb-user { background:#f8fafc; border:1px solid #e8edf5;
               border-radius:10px; padding:10px 12px; margin-bottom:14px; }
    .sb-user-name { font-size:13px; font-weight:700; color:#0f172a; }
    .sb-user-role { font-size:11px; color:#64748b; margin-top:2px; }
    .sb-nav-label  { font-size:10px; font-weight:800; letter-spacing:1.5px;
                     text-transform:uppercase; color:#94a3b8 !important;
                     padding: 6px 4px 8px 4px; display:block; }
    .sb-divider { border-top:1px solid #e8edf5; margin: 12px 0; }

    /* ── Dashboard cards ── */
    .db-header {
        background: linear-gradient(135deg,#0a1628 0%,#0f2347 60%,#162d55 100%);
        border-radius:18px; padding:28px 32px; margin-bottom:28px;
        position:relative; overflow:hidden;
        box-shadow:0 4px 20px rgba(10,22,40,0.22);
    }
    .db-header::before {
        content:''; position:absolute; top:0; left:0; right:0; height:3px;
        background:linear-gradient(90deg,#34d399,#10b981,#059669);
    }
    .db-header-title { font-family:'Cormorant Garamond',serif; font-size:26px;
                       font-weight:700; color:#f0f4ff; }
    .db-header-sub   { font-size:13px; color:#4a6a8a; margin-top:4px; }
    .db-header-badge {
        background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.3);
        border-radius:999px; padding:6px 16px;
        font-size:12px; font-weight:700; color:#6ee7b7;
        display:inline-flex; align-items:center; gap:7px;
    }
    .db-kpi { background:#ffffff; border:1px solid #e8edf5; border-radius:16px;
              padding:20px 22px; box-shadow:0 2px 8px rgba(15,23,42,0.05);
              position:relative; overflow:hidden; }
    .db-kpi::before { content:''; position:absolute; top:0; left:0; bottom:0;
                      width:3px; background:linear-gradient(180deg,#34d399,#059669);
                      border-radius:3px 0 0 3px; }
    .db-kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px; }
    .db-section-title { font-family:'Cormorant Garamond',serif; font-size:20px;
                        font-weight:700; color:#0a1628; margin:24px 0 12px; }
    .db-table-wrap { background:#ffffff; border:1px solid #e8edf5; border-radius:16px;
                     overflow:hidden; box-shadow:0 2px 8px rgba(15,23,42,0.05); margin-bottom:24px; }
    .db-table-head { display:grid; grid-template-columns:1.5fr 1fr 1fr;
                     background:#f8fafc; border-bottom:1px solid #e8edf5; padding:10px 20px; }
    .db-th { font-size:10px; font-weight:800; letter-spacing:1.2px;
             text-transform:uppercase; color:#94a3b8; }
    .db-table-row { display:grid; grid-template-columns:1.5fr 1fr 1fr;
                    padding:14px 20px; border-bottom:1px solid #f8fafc;
                    transition:background .15s; }
    .db-table-row:hover { background:#f0fdf9; }
    .db-table-row:last-child { border-bottom:none; }
    .db-td { font-size:13px; color:#334155; display:flex; align-items:center; }
    .db-td-sub { font-size:11px; color:#94a3b8; margin-top:2px; }
    .db-avail-card { background:#ffffff; border:1px solid #e8edf5; border-radius:12px;
                     padding:14px 16px; box-shadow:0 1px 4px rgba(15,23,42,0.04); }

    /* Calendar styles */
    .cal-year{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
    @media (max-width:1100px){.cal-year{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media (max-width:750px){.cal-year{grid-template-columns:repeat(1,minmax(0,1fr))}}
    .cal-month{background:#ffffff;border:1px solid #e8edf5;border-radius:16px;padding:12px;box-shadow:0 2px 10px rgba(15,23,42,0.06)}
    .cal-month-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:10px}
    .cal-month-name{font-weight:700;font-size:16px;color:#0a1628}
    .cal-month-meta{font-size:12px;color:#64748b;font-weight:600}
    .cal-weekdays{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:6px}
    .cal-weekday{font-size:11px;color:#64748b;font-weight:800;text-transform:uppercase;letter-spacing:0.6px;text-align:center}
    .cal-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px}
    .cal-cell{border:1px solid #eef2f7;border-radius:12px;min-height:74px;padding:6px;background:#fbfdff;position:relative;overflow:hidden}
    .cal-cell.muted{background:#f8fafc;color:#94a3b8}
    .cal-cell:hover{border-color:#6ee7b7;box-shadow:0 4px 12px rgba(16,185,129,0.08)}
    .cal-daynum{font-size:12px;font-weight:900;color:#0a1628}
    .cal-cell.muted .cal-daynum{color:#94a3b8}
    .cal-pills{margin-top:6px;display:flex;flex-direction:column;gap:4px}
    .cal-pill{border-radius:999px;border:1px solid #a7f3d0;background:#ecfdf5;color:#065f46;padding:2px 8px;font-size:11px;font-weight:800;line-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .cal-pill.alt{border-color:#bfdbfe;background:#eff6ff;color:#1e3a8a}
    .cal-pill.warn{border-color:#fed7aa;background:#fff7ed;color:#9a3412}
    .cal-more{font-size:11px;font-weight:800;color:#475569;padding-left:4px}

    /* checklist styles */
    .ck-ctx{background:linear-gradient(135deg,#0a1628,#0f2347);border-radius:14px;padding:18px 22px;margin-bottom:20px;border-left:4px solid #34d399;}
    .ck-main-card{background:#ffffff;border:1px solid #e8edf5;border-radius:12px;padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 4px rgba(15,23,42,0.04);}
    .ck-node-main{background:#ffffff;border:2px solid #10b981;border-radius:12px;padding:16px 18px;margin-bottom:12px;}
    .ck-node-sub{background:#f0fdf9;border:1px solid #a7f3d0;border-radius:10px;padding:14px 16px;margin-bottom:8px;margin-left:24px;}
    .ck-badge{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0;border-radius:999px;padding:2px 10px;font-size:11px;font-weight:700;}
    .subtle{font-size:12px;color:#64748b;}
    /* Hide "Press Enter to submit form" tooltip everywhere */
    [data-testid="InputInstructions"]{display:none!important;visibility:hidden!important;}

    /* ── Multiselect tags — light teal/green, readable text ── */
    span[data-baseweb="tag"]{
        background:#e6fdf4 !important;
        border:1px solid #6ee7b7 !important;
        border-radius:8px !important;
        padding:3px 8px !important;
    }
    span[data-baseweb="tag"] span{
        color:#065f46 !important;
        font-weight:600 !important;
        font-size:12px !important;
    }
    span[data-baseweb="tag"] svg{
        fill:#10b981 !important;
    }
    </style>""", unsafe_allow_html=True)

def inject_theme_overrides():
    if (st.session_state.get("ui_theme") or "light").lower().strip() != "dark":
        return
    st.markdown(
        """<style>.stApp{background:#0b1220 !important;color:#e5e7eb !important}.block-container{background:transparent !important}section[data-testid="stSidebar"]{background:#0f172a !important;border-right:1px solid #223047 !important}section[data-testid="stSidebar"] *{color:#e5e7eb !important}h1,h2,h3,h4,h5,h6{color:#f1f5f9 !important}p,span,li{color:#cbd5e1 !important}.panel,.card,.hero,.kpi,.pill,.breadcrumb{background:#0f172a !important;border:1px solid #223047 !important}.panel-title,.title{color:#f1f5f9 !important}.panel-subtitle,.sub,.subtle{color:#94a3b8 !important}.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div,.stMultiSelect div[data-baseweb="select"]>div,.stDateInput input{background:#0b1220 !important;color:#e5e7eb !important;border:1px solid #223047 !important}.stButton button,button[kind="primary"]{background:#111c33 !important;color:#e5e7eb !important;border:1px solid #223047 !important}.stButton button:hover{border-color:#3b82f6 !important}[data-testid="stDataFrame"],.stDataFrame,.stTable{background:#0f172a !important;border:1px solid #223047 !important}</style>""",
        unsafe_allow_html=True,
    )

# ── UI components ─────────────────────────────────────────────────────────────
def render_topbar(username: str, role: str):
    role_lbl = role.upper()
    st.markdown(
        '<div class="topbar">'
        '<div>'
        '<div class="topbar-brand">Audit Management System</div>'
        '<div class="topbar-sub">Controlled scheduling · Skill matching · Checklists · Reports</div>'
        '</div>'
        '<div class="topbar-pill">'
        '<span class="topbar-dot"></span>'
        + role_lbl + ' &nbsp;·&nbsp; ' + username +
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

# Page icon map
_PAGE_ICONS = {
    "Dashboard": "⬛", "Audit Calender": "📅", "Audit Plan": "🗓",
    "Auditors & Skills": "👥", "Checklist": "✅", "Audit Details": "🔍",
    "Reports": "📄", "My Audits": "📋",
}

def render_breadcrumb(role: str, page_name: str):
    role_label = "Admin" if (role or "").strip().lower() == "admin" else "Auditor"
    icon = _PAGE_ICONS.get(page_name, "▸")
    st.markdown(
        '<div class="breadcrumb">'
        '<span>' + role_label + '</span>'
        '<span class="sep">›</span>'
        '<span class="current">' + icon + ' &nbsp;' + page_name + '</span>'
        '</div>',
        unsafe_allow_html=True,
    )

def render_panel(title: str, subtitle: str = ""):
    st.markdown(
        f"""<div class="panel"><div class="panel-title">{title}</div><div class="panel-subtitle">{subtitle}</div></div>""",
        unsafe_allow_html=True,
    )

def render_kpi(label: str, value: str, meta: str = ""):
    st.markdown(
        f"""<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="meta">{meta}</div></div>""",
        unsafe_allow_html=True,
    )

def status_chip(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "closed":
        bg, fg, bd, label = "#ecfdf5", "#065f46", "#a7f3d0", "Closed"
    elif "report" in s:
        bg, fg, bd, label = "#eff6ff", "#1e3a8a", "#bfdbfe", "Report Submitted"
    elif "progress" in s:
        bg, fg, bd, label = "#fff7ed", "#9a3412", "#fed7aa", "In Progress"
    else:
        bg, fg, bd, label = "#f8fafc", "#0f172a", "#e5e7eb", status or "Assigned"
    return (
        f"""<span style="display:inline-flex;align-items:center;gap:8px;padding:4px 10px;border-radius:999px;"""
        f"""border:1px solid {bd};background:{bg};color:{fg};font-size:12px;line-height:18px;font-weight:900;vertical-align:middle;">{label}</span>"""
    )

def render_status_legend():
    st.markdown(
        " ".join(status_chip(s) for s in ["Assigned", "In Progress", "Report Submitted", "Closed"]),
        unsafe_allow_html=True,
    )

# ── App config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Audit Assignment System", page_icon="✅", layout="wide", initial_sidebar_state="expanded")
inject_enterprise_css()
inject_theme_overrides()

if "bootstrapped" not in st.session_state:
    try:
        engine.ensure_seed_files(tenant_code="default", tenant_name="Default")
    except TypeError:
        engine.ensure_seed_files()
    st.session_state["bootstrapped"] = True

# ── Checklist seed ────────────────────────────────────────────────────────────
CHECKLIST_CANDIDATE_FILES = ["checklist.catalog.json", "checklist_catalog.json", "checklists_catalog.json"]

def _find_checklist_catalog_file() -> str:
    return next((f for f in CHECKLIST_CANDIDATE_FILES if os.path.exists(f)), CHECKLIST_CANDIDATE_FILES[0])

def _load_json_file(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json_file(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _ensure_dict(d) -> dict:
    return d if isinstance(d, dict) else {}

def ensure_checklist_seed_data():
    path = _find_checklist_catalog_file()
    catalog = _ensure_dict(_load_json_file(path, {}))
    seed: Dict[str, Dict[str, List[str]]] = {
        "Management Review": {
            "General Requirements": ["Does top management conduct management reviews at planned intervals?","Is MRM plan documented?","Is the management review procedure defined and implemented?","Are management review records maintained?","Is MRM notice sent, acknowledged by respective personnel, and documented?","Is the MRM attendance documented?"],
            "Management Review Inputs": ["Results of internal and external audits reviewed and documented","Customer feedback (including complaints) reviewed and documented","Process performance and product conformity reviewed and documented","Status of preventive and corrective actions reviewed and documented","Follow-up actions from previous management reviews reviewed and documented","Changes that could affect the QMS (regulatory, organizational, product-related) reviewed and documented","Recommendations for improvement reviewed and documented","New or revised regulatory requirements applicable to medical devices reviewed and documented","Resource needs (human, infrastructure, work environment) reviewed and documented"],
            "Conduct of Management Review": ["Is the management review chaired or attended by top management?","Are relevant process owners involved as required?","Are discussions aligned with the planned agenda?"],
            "Management Review Outputs": ["Decisions/actions documented for improvement of the effectiveness of the QMS","Decisions/actions documented for improvement of product-related processes","Decisions/actions documented for improvement of medical device safety and performance","Resource requirements documented","Actions addressing identified risks documented","Responsibilities and timelines assigned for actions"],
            "Follow-up & Records": ["Is the effectiveness of previous actions reviewed in subsequent MRMs?","Are management review minutes legible, dated, and approved?"],
        },
        "Purchase and Supplier": {
            "Supplier Selection": ["Is supplier selection initiated when a new material, component, or service is required?","Does the Purchase Department identify potential suppliers?","Are supplier identification sources documented?","Are suppliers evaluated based on defined selection criteria?","Are suppliers categorized based on risk-based approach?"],
            "Supplier Evaluation & Approval": ["Is Supplier Assessment completed for potential suppliers?","Is the completed assessment reviewed?","Are suppliers evaluated and scored as per defined criteria?","Are approved suppliers included in Approved Supplier List?","For critical suppliers, is Supplier Quality Agreement executed before approval?"],
            "Control of Outsourced Processes": ["Are outsourced processes assigned only to approved suppliers?","Is verification of certificates and reports from outsourced activities carried out?"],
            "Purchase Order Control": ["Is supplier verification against the Approved Supplier List performed before PO issuance?","Is Supplier Selection & Evaluation initiated if the supplier is not approved?","Are POs reviewed and approved by authorized personnel?","Are PO records maintained?"],
            "Verification of Purchased Product": ["Is Incoming Inspection conducted as per approved procedure or specifications?","Are inspection results documented?","Are inspection outcomes (acceptance/rejection/deviation/concession) linked to the supplier?","Are non-conforming items recorded?","Are inspection results used for supplier performance monitoring?"],
            "Supplier Performance Evaluation": ["Is supplier performance evaluated based on defined parameters?","Are suppliers classified according to defined rating scale?","Are suppliers evaluated as per defined time period?","Are supplier audits conducted when required?","Is SCAR issued to the suppliers when required?","Are supplier ratings reviewed in Management Review Meetings?"],
            "Supplier Re-evaluation": ["Is re-evaluation initiated based on performance monitoring results?","Are re-evaluation outcomes documented?"],
        },
        "HR": {
            "Resource Planning": ["Is manpower planning performed at planned intervals?","Are roles and responsibilities defined for all positions?","Are competency requirements defined for each role?"],
            "Onboarding": ["Is an onboarding plan available for new joiners?","Are onboarding records maintained (induction, training schedule, acknowledgements)?"],
            "Training Planning": ["Is an annual training plan prepared based on role competency requirements?","Is training need identification documented (gap assessment)?"],
            "Training Execution & Records": ["Are training records maintained (attendance, trainer, topic, date)?","Are trainees assessed where applicable (quiz, observation, supervision sign-off)?"],
            "Training Effectiveness": ["Is training effectiveness evaluated and documented?","Are re-trainings or corrective actions initiated if effectiveness is not met?"],
            "Regulatory & QMS Awareness": ["Are personnel aware of applicable regulatory/QMS requirements relevant to their roles?","Is awareness training conducted for changes to procedures or regulations?"],
        },
        "Production": {
            "BMR": ["PICK UP A BATCH MANUFACTURING RECORD (BMR)","Are the following details available – batch number, manufacturing start and completion date?","Are raw material lot numbers mentioned?","Check for the Certificate of Analysis (COA) of the Raw Materials","Does the COA give test names, specified and achieved results","Check the Quality Assurance Plan (QAP)","Does the QAP give details such test stage, test name, method, sample size, acceptance criteria?","Are the quantities produced and rejected mentioned in the BMR?","Is a NCR form filled out in case of rejections?","Is the NCR report approved by the designated authority?","Are the instrument IDs mentioned in the BMR?","Check the calibration log and report of the instruments.","Do the calibration reports mention name of an accredited lab","Do the calibration reports mention traceability to national or international standards?"],
        },
    }
    changed = False
    for dept, sections in seed.items():
        if not isinstance(catalog.get(dept), dict):
            catalog[dept] = {}
            changed = True
        for sec, items in sections.items():
            if not isinstance(catalog[dept].get(sec), list) or not catalog[dept].get(sec):
                catalog[dept][sec] = items
                changed = True
    if changed:
        _save_json_file(path, catalog)

if "checklist_seeded" not in st.session_state:
    ensure_checklist_seed_data()
    st.session_state["checklist_seeded"] = True

# ── Engine helpers ────────────────────────────────────────────────────────────
def _current_tenant_id() -> Optional[str]:
    return st.session_state.auth.get("tenant_id")

def _engine_call(func_name: str, *args, **kwargs):
    fn = getattr(engine, func_name)
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        if "tenant_id" in params and "tenant_id" not in kwargs:
            pos = params.index("tenant_id")
            if len(args) <= pos:
                kwargs["tenant_id"] = _current_tenant_id()
    except Exception:
        pass
    return fn(*args, **kwargs)

# ── Cached data ───────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=60)
def _cached_list_audits(tenant_id):
    return engine.list_audits(tenant_id=tenant_id) if hasattr(engine, "list_audits") else _engine_call("list_audits")

@st.cache_data(show_spinner=False, ttl=60)
def _cached_list_audit_calendar(tenant_id):
    try:
        return _engine_call("list_audit_calendar", tenant_id=tenant_id)
    except TypeError:
        return _engine_call("list_audit_calendar")

@st.cache_data(show_spinner=False, ttl=300)
def _cached_departments_catalog(tenant_id):
    return _engine_call("load_departments_catalog", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=300)
def _cached_skills_catalog(tenant_id):
    return _engine_call("load_skills_catalog", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=120)
def _cached_people(tenant_id):
    return _engine_call("list_people_records", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_state(tenant_id):
    return _engine_call("load_state", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=300)
def _cached_sections_for_dept(tenant_id, dept: str):
    return _engine_call("get_sections_for_department", dept, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=300)
def _cached_items_for_section(tenant_id, dept: str, section: str):
    return _engine_call("get_items_for_department_section", dept, section, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=300)
def _cached_timetable_schedule():
    return (timetable.load_schedule() if _HAS_TIMETABLE and timetable else {}) or {"days": {}}

def _clear_caches_and_rerun():
    st.cache_data.clear()
    _rerun()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def logout():
    st.session_state.auth = {"logged_in": False, "tenant_code": "default", "tenant_id": None, "username": None, "role": None, "person_name": None}
    st.session_state["_do_rerun"] = True

def require_login():
    if not st.session_state.auth["logged_in"]:
        st.stop()

# ── Timetable reminder ────────────────────────────────────────────────────────
def _parse_slot_start_end(slot_str: str):
    start_s, end_s = slot_str.split("-", 1)
    return start_s.strip(), end_s.strip()

def show_auditor_timetable_reminder(auditor_name: str, remind_within_minutes: int = 30):
    try:
        tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    today = now.date().isoformat()
    day = _cached_timetable_schedule().get("days", {}).get(today, {})
    my_today = [{"slot": slot, "department": a.get("department", "")} for slot, audits in day.items() for a in audits if a.get("auditor") == auditor_name]
    if not my_today:
        return

    ongoing_msg = None
    upcoming_candidates = []
    for item in my_today:
        slot, dept = item["slot"], item["department"]
        try:
            start_s, end_s = _parse_slot_start_end(slot)
            today_d = date.fromisoformat(today)
            start_dt = datetime.combine(today_d, datetime.strptime(start_s, "%H:%M").time())
            end_dt = datetime.combine(today_d, datetime.strptime(end_s, "%H:%M").time())
            if tz:
                start_dt = start_dt.replace(tzinfo=tz)
                end_dt = end_dt.replace(tzinfo=tz)
            if start_dt <= now < end_dt:
                ongoing_msg = f"Active now: {slot} | Department: {dept}"
                break
            if now < start_dt:
                upcoming_candidates.append((int((start_dt - now).total_seconds() // 60), slot, dept))
        except Exception:
            continue

    if ongoing_msg:
        st.warning(ongoing_msg)
    elif upcoming_candidates:
        upcoming_candidates.sort(key=lambda x: x[0])
        mins, slot, dept = upcoming_candidates[0]
        if mins <= remind_within_minutes:
            st.info(f"Upcoming audit: in {mins} minutes | Start: {slot.split('-')[0]} | Department: {dept}")

# ── Dropdown/table helpers ────────────────────────────────────────────────────
def get_department_options_with_other() -> List[str]:
    return _cached_departments_catalog(_current_tenant_id()) + ["Other"]

def get_skill_catalog() -> Dict[str, str]:
    return _cached_skills_catalog(_current_tenant_id())

def _get_checklist_catalog_depts() -> List[str]:
    catalog = _ensure_dict(_load_json_file(_find_checklist_catalog_file(), {}))
    return sorted([k for k in catalog if str(k).strip()], key=lambda x: str(x).lower())

def build_audit_dropdown(audits: List[Dict], *, restrict_to_auditor: bool, auditor_name: Optional[str]) -> tuple[list[str], dict[str, str]]:
    visible = [a for a in audits if a.get("assigned_auditor") == auditor_name] if restrict_to_auditor and auditor_name else audits
    labels: list[str] = []
    label_to_id: dict[str, str] = {}
    for a in visible:
        aid = (a.get("audit_id") or "").strip()
        if not aid:
            continue
        title = (a.get("title") or "").strip()
        dept = (a.get("audited_department") or "").strip()
        status = (a.get("status") or "").strip()
        base = title or f"{dept or 'Audit'} | {aid[:8]}"
        extras = [x for x in [dept, status] if x]
        label = f"{base}  ({' | '.join(extras)})" if extras else base
        uniq, n = label, 2
        while uniq in label_to_id:
            uniq, n = f"{label} [{n}]", n + 1
        labels.append(uniq)
        label_to_id[uniq] = aid
    return sorted(labels, key=str.lower), label_to_id

def audits_table(audits: List[Dict], *, search_query: str = ""):
    if not audits:
        st.info("No audits found.")
        return
    q = (search_query or "").strip().lower()
    rows = []
    for a in audits:
        row = {"Audit ID": a.get("audit_id"), "Title": a.get("title"), "Dept": a.get("audited_department"), "Auditor": a.get("assigned_auditor"), "Status": a.get("status"), "Created": a.get("created_at"), "Due": a.get("due_date"), "Reports": len(a.get("reports", []))}
        if q and q not in " ".join(str(v or "") for v in row.values()).lower():
            continue
        rows.append(row)
    if not rows:
        st.info("No results for the current search filter.")
    else:
        st.dataframe(rows, use_container_width=True, hide_index=True)




# ── Login page ────────────────────────────────────────────────────────────────
if not st.session_state.auth["logged_in"]:
    st.markdown("""<style>
    html,[class*="css"]{font-family:'Inter',sans-serif!important;}

    .stApp{
        background:#f0f2f8!important;
        min-height:100vh!important;
        display:flex!important;
        align-items:center!important;
    }
    footer,#MainMenu,header{visibility:hidden!important;}
    section[data-testid="stSidebar"]{display:none!important;}

    /* Stretch block container full width */
    .block-container{
        max-width:1100px!important;
        padding:4vh 2rem!important;
        margin:0 auto!important;
        width:100%!important;
    }

    /* The outer card box */
    .block-container > div:first-child{
        border-radius:28px;
        overflow:hidden;
        box-shadow:0 8px 20px rgba(0,0,0,0.25),0 40px 100px rgba(0,0,0,0.30);
        border:1px solid rgba(255,255,255,0.06);
        background:#ffffff;
    }

    /* ════ LEFT PANEL ════ */
    .lg-left{
        background:linear-gradient(150deg,#0a1628 0%,#0d1f40 45%,#0f2a52 100%);
        padding:60px 52px 48px;
        min-height:620px;
        display:flex;flex-direction:column;justify-content:space-between;
        position:relative;overflow:hidden;
    }
    /* Dot grid */
    .lg-left::before{
        content:'';position:absolute;inset:0;
        background-image:radial-gradient(rgba(255,255,255,0.06) 1px,transparent 1px);
        background-size:30px 30px;
        mask-image:linear-gradient(135deg,transparent 0%,rgba(0,0,0,.5) 40%,rgba(0,0,0,.5) 80%,transparent 100%);
        -webkit-mask-image:linear-gradient(135deg,transparent 0%,rgba(0,0,0,.5) 40%,rgba(0,0,0,.5) 80%,transparent 100%);
        pointer-events:none;z-index:0;
    }
    /* Glow orb top-right */
    .lg-left::after{
        content:'';position:absolute;top:-140px;right:-100px;
        width:420px;height:420px;border-radius:50%;
        background:radial-gradient(circle,rgba(99,102,241,0.20) 0%,transparent 65%);
        pointer-events:none;z-index:0;
    }
    .lg-glow-bottom{
        position:absolute;bottom:-120px;left:-80px;
        width:360px;height:360px;border-radius:50%;
        background:radial-gradient(circle,rgba(52,211,153,0.13) 0%,transparent 65%);
        pointer-events:none;z-index:0;
    }
    .lg-left-inner{position:relative;z-index:1;display:flex;flex-direction:column;height:100%;}

    /* Brand row */
    .lg-brand{display:flex;align-items:center;gap:14px;margin-bottom:64px;}
    .lg-brand-icon{
        width:46px;height:46px;border-radius:14px;flex-shrink:0;
        background:linear-gradient(135deg,#34d399,#059669);
        display:flex;align-items:center;justify-content:center;font-size:20px;
        box-shadow:0 4px 18px rgba(52,211,153,0.35);
    }
    .lg-brand-name{
        font-size:13px;font-weight:700;color:#e2e8f0;
        letter-spacing:.8px;text-transform:uppercase;line-height:1.2;
    }
    .lg-brand-sub{font-size:10px;color:#4a6a8a;letter-spacing:.5px;margin-top:1px;}

    /* Hero copy */
    .lg-kicker{
        font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
        color:#34d399;margin-bottom:18px;
        display:inline-flex;align-items:center;gap:8px;
    }
    .lg-kicker::before{content:'';width:20px;height:1px;background:#34d399;display:inline-block;}
    .lg-title{
        font-family:'Cormorant Garamond',serif;
        font-size:52px;font-weight:700;line-height:1.06;
        color:#f0f4ff;margin-bottom:22px;letter-spacing:-.5px;
    }
    .lg-title em{font-style:italic;color:#a5b4fc;}
    .lg-title strong{font-style:normal;color:#ffffff;}
    .lg-desc{
        font-size:13px;color:#94b4cc;line-height:1.85;
        max-width:320px;margin-bottom:44px;
    }

    /* Feature pills */
    .lg-feats{display:flex;flex-direction:column;gap:14px;}
    .lg-feat{
        display:flex;align-items:center;gap:14px;
        padding:12px 14px;border-radius:12px;
        background:rgba(255,255,255,0.06);
        border:1px solid rgba(255,255,255,0.09);
        transition:background .2s;
    }
    .lg-feat:hover{background:rgba(255,255,255,0.09);}
    .lg-feat-icon{
        width:36px;height:36px;border-radius:10px;flex-shrink:0;
        display:flex;align-items:center;justify-content:center;font-size:15px;
    }
    .lg-feat-icon-green{background:rgba(52,211,153,0.18);border:1px solid rgba(52,211,153,0.30);}
    .lg-feat-icon-blue {background:rgba(99,102,241,0.18);border:1px solid rgba(99,102,241,0.30);}
    .lg-feat-icon-amber{background:rgba(251,191,36,0.15);border:1px solid rgba(251,191,36,0.28);}
    .lg-feat-title{font-size:13px;font-weight:600;color:#e8f0f8;letter-spacing:.1px;}
    .lg-feat-desc{font-size:11px;color:#7a9ab8;margin-top:2px;line-height:1.5;}

    .lg-left-foot{
        margin-top:48px;padding-top:18px;
        border-top:1px solid rgba(255,255,255,0.08);
        font-size:11px;color:#4a6a8a;letter-spacing:.3px;
        display:flex;align-items:center;gap:12px;
    }
    .lg-foot-dot{width:5px;height:5px;border-radius:50%;background:#34d399;flex-shrink:0;}

    /* ════ RIGHT PANEL ════ */
    .lg-right{
        background:#ffffff;
        padding:60px 56px 48px;
        display:flex;flex-direction:column;justify-content:center;
    }
    .lg-status{
        display:inline-flex;align-items:center;gap:7px;
        background:#f0fdf9;border:1px solid #a7f3d0;border-radius:999px;
        padding:5px 14px 5px 8px;margin-bottom:32px;
        font-size:11px;font-weight:600;color:#065f46;
    }
    .lg-status-dot{
        width:7px;height:7px;border-radius:50%;background:#10b981;
        box-shadow:0 0 0 3px rgba(16,185,129,0.2);
        animation:lgpulse 2.4s ease-in-out infinite;
    }
    @keyframes lgpulse{
        0%,100%{box-shadow:0 0 0 3px rgba(16,185,129,0.20);}
        50%{box-shadow:0 0 0 7px rgba(16,185,129,0.06);}
    }
    .lg-form-label{
        font-size:10px;font-weight:800;letter-spacing:2.5px;text-transform:uppercase;
        color:#10b981;margin-bottom:8px;
    }
    .lg-form-title{
        font-family:'Cormorant Garamond',serif;
        font-size:38px;font-weight:700;color:#0f172a;
        line-height:1.15;margin-bottom:6px;letter-spacing:-.4px;
    }
    .lg-form-sub{font-size:13px;color:#94a3b8;margin-bottom:32px;line-height:1.5;}

    /* Streamlit inputs */
    .stTextInput label{
        font-size:11px!important;font-weight:700!important;
        letter-spacing:.8px!important;text-transform:uppercase!important;
        color:#475569!important;
    }
    .stTextInput>div>div>input{
        background:#f8fafc!important;border:1.5px solid #e2e8f0!important;
        border-radius:12px!important;padding:14px 16px!important;
        font-size:14px!important;font-weight:500!important;
        color:#0f172a!important;font-family:'Inter',sans-serif!important;
        transition:all .2s!important;
    }
    .stTextInput>div>div>input::placeholder{color:#c4cdd9!important;}
    .stTextInput>div>div>input:focus{
        border-color:#10b981!important;background:#fff!important;
        box-shadow:0 0 0 4px rgba(16,185,129,0.12)!important;
    }

    /* Button */
    div[data-testid="stFormSubmitButton"]>button,
    div[data-testid="stFormSubmitButton"]>button:focus{
        background:linear-gradient(135deg,#34d399 0%,#10b981 50%,#059669 100%)!important;
        color:#fff!important;border:none!important;
        border-radius:13px!important;padding:15px 24px!important;
        font-size:15px!important;font-weight:700!important;
        letter-spacing:.4px!important;width:100%!important;
        box-shadow:0 4px 20px rgba(16,185,129,0.40)!important;
        transition:all .2s ease!important;cursor:pointer!important;
        font-family:'Inter',sans-serif!important;
    }
    div[data-testid="stFormSubmitButton"]>button:hover{
        background:linear-gradient(135deg,#10b981 0%,#059669 100%)!important;
        box-shadow:0 8px 28px rgba(5,150,105,0.50)!important;
        transform:translateY(-2px)!important;
    }
    div[data-testid="stFormSubmitButton"]>button:active{transform:translateY(0)!important;}
    div[data-testid="stFormSubmitButton"]>button p,
    div[data-testid="stFormSubmitButton"]>button span{
        color:#fff!important;font-weight:700!important;font-size:15px!important;
    }
    div[data-testid="stForm"]{
        background:transparent!important;border:none!important;
        box-shadow:none!important;padding:0!important;
    }
    /* Hide "Press Enter to submit form" tooltip */
    .stTextInput [data-testid="InputInstructions"],
    .stTextInput ~ [data-testid="InputInstructions"],
    small[data-testid="InputInstructions"],
    [data-testid="InputInstructions"]{
        display:none!important;visibility:hidden!important;opacity:0!important;
    }

    /* Credentials */
    .lg-creds{margin-top:24px;padding-top:20px;border-top:1px solid #f1f5f9;}
    .lg-creds-hd{
        font-size:10px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;
        color:#cbd5e1;margin-bottom:12px;display:flex;align-items:center;gap:10px;
    }
    .lg-creds-hd::after{content:'';flex:1;height:1px;background:#f1f5f9;}
    .lg-cred-row{
        display:flex;align-items:center;gap:10px;
        padding:9px 14px;border-radius:10px;
        background:#f8fafc;border:1px solid #f0f2f8;margin-bottom:6px;
        transition:background .15s;
    }
    .lg-cred-row:hover{background:#f0fdf9;}
    .lg-badge{
        font-size:9px;font-weight:800;padding:3px 9px;
        border-radius:6px;flex-shrink:0;letter-spacing:.5px;text-transform:uppercase;
    }
    .lg-badge-a{background:#eef2ff;color:#4338ca;}
    .lg-badge-u{background:#f0fdf4;color:#15803d;}
    .lg-cred-txt{font-size:12px;color:#64748b;}
    .lg-cred-txt strong{color:#1e293b;font-weight:700;}
    </style>""", unsafe_allow_html=True)

    # ── Layout: 55% left, 45% right ──────────────────────────────────────────
    col_l, col_r = st.columns([1.2, 1], gap="small")

    with col_l:
        st.markdown("""
        <div class="lg-left">
          <div class="lg-glow-bottom"></div>
          <div class="lg-left-inner">
            <div>
              <div class="lg-brand">
                <div class="lg-brand-icon">&#128203;</div>
                <div>
                  <div class="lg-brand-name">Audit Management</div>
                  <div class="lg-brand-sub">Enterprise Platform</div>
                </div>
              </div>
              <div class="lg-kicker">Trusted by enterprise teams</div>
              <div class="lg-title">
                <strong>Audit</strong> with<br>
                <em>confidence</em><br>
                <strong>&amp; clarity</strong>
              </div>
              <div class="lg-desc">
                A complete audit lifecycle platform — from intelligent scheduling and
                skill-based assignment to structured checklists and secure report archiving.
              </div>
              <div class="lg-feats">
                <div class="lg-feat">
                  <div class="lg-feat-icon lg-feat-icon-green">&#128197;</div>
                  <div>
                    <div class="lg-feat-title">Smart Scheduling</div>
                    <div class="lg-feat-desc">Automated calendar with skill-matched auditor assignment</div>
                  </div>
                </div>
                <div class="lg-feat">
                  <div class="lg-feat-icon lg-feat-icon-blue">&#9989;</div>
                  <div>
                    <div class="lg-feat-title">Structured Checklists</div>
                    <div class="lg-feat-desc">Hierarchical flows that preserve full audit integrity</div>
                  </div>
                </div>
                <div class="lg-feat">
                  <div class="lg-feat-icon lg-feat-icon-amber">&#128196;</div>
                  <div>
                    <div class="lg-feat-title">PDF Reports &amp; Closure</div>
                    <div class="lg-feat-desc">Professional reports generated and securely archived</div>
                  </div>
                </div>
              </div>
            </div>
            <div class="lg-left-foot">
              <span class="lg-foot-dot"></span>
              &#169; 2025 Audit Management System &nbsp;&#183;&nbsp; Secure RBAC Access Control
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    with col_r:
        st.markdown("""
        <div class="lg-right">
          <div class="lg-status"><span class="lg-status-dot"></span>System Online &nbsp;&#183;&nbsp; Secure Access</div>
          <div class="lg-form-label">Secure Portal</div>
          <div class="lg-form-title">Welcome<br>back</div>
          <div class="lg-form-sub">Sign in to access your dashboard</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            tenant_code = st.text_input("Company Code", value=st.session_state.auth.get("tenant_code") or "default", placeholder="e.g. default")
            username    = st.text_input("Username",    placeholder="Enter your username")
            password    = st.text_input("Password",    type="password", placeholder="••••••••")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            submitted   = st.form_submit_button("Sign In  →", type="primary", use_container_width=True)

        st.markdown("""
        <div class="lg-creds">
          <div class="lg-creds-hd">Default Credentials</div>
          <div class="lg-cred-row">
            <span class="lg-badge lg-badge-a">Admin</span>
            <span class="lg-cred-txt"><strong>admin</strong> &nbsp;/&nbsp; <strong>admin123</strong></span>
          </div>
          <div class="lg-cred-row">
            <span class="lg-badge lg-badge-u">Auditor</span>
            <span class="lg-cred-txt">lowercase name &nbsp;/&nbsp; <strong>auditor123</strong></span>
          </div>
        </div>
        """, unsafe_allow_html=True)

    if submitted:
        with st.spinner("Signing in... Please wait"):
            tenant_code = (tenant_code or "").strip().lower()
            username    = (username or "").strip().lower()
            if hasattr(engine, "authenticate_tenant"):
                ok, u, msg = engine.authenticate_tenant(tenant_code, username, password)
            else:
                ok, u, msg = engine.authenticate(username, password)

        if not ok:
            st.error(msg)
        else:
            st.session_state.auth = {"logged_in": True, "tenant_code": tenant_code, "tenant_id": u.get("tenant_id"), "username": u["username"], "role": u["role"], "person_name": u.get("person_name")}
            st.rerun()
    st.stop()
import calendar as _calendar
import pandas as _pd

# ── Audit Calendar page ───────────────────────────────────────────────────────
def page_audit_calendar():
    st.title("Audit Calendar")
    st.caption("Plan the full year in a compact calendar. Create recurring audits using year, start month, frequency, and auto-calculated occurrences.")

    tenant_id = st.session_state.auth.get("tenant_id")
    username = st.session_state.auth.get("username", "")
    today = date.today()

    def _safe_date(s, default="1900-01-01"):
        try:
            return date.fromisoformat(str(s or default))
        except Exception:
            return date.fromisoformat(default)

    def _add_months(d: date, months: int) -> date:
        y = d.year + (d.month - 1 + months) // 12
        mth = (d.month - 1 + months) % 12 + 1
        last = _calendar.monthrange(y, mth)[1]
        return date(y, mth, min(d.day, last))

    def _status_bucket(a):
        s = str(a.get("status", "")).strip().lower()
        if s in {"planned", "open", "assigned", "scheduled", "created"}:
            return "planned"
        if s in {"in progress", "in-progress", "progress", "ongoing", "active"}:
            return "progress"
        if s in {"closed", "done", "complete", "completed"}:
            return "closed"
        return "other"

    def _freq_step_and_count(freq: str, start_month: int) -> tuple[int, int]:
        mapping = {
            "Monthly": 1,
            "Bi-monthly": 2,
            "Quarterly": 3,
            "Half-yearly": 6,
        }
        step = mapping.get(freq, 1)
        count = len(list(range(int(start_month), 13, step)))
        return step, count

    # ── CSS ─────────────────────────────────────────────────────────────────
    st.markdown("""<style>
    .yc-outer{
        border:3px solid #1a3a8f;
        border-radius:4px;
        background:#fff;
        overflow:hidden;
        margin-top:8px;
    }
    .yc-year-banner{
        text-align:center;
        font-size:36px;
        font-weight:900;
        color:#0f172a;
        padding:10px 0 8px 0;
        border-bottom:3px solid #1a3a8f;
        background:#fff;
        letter-spacing:1px;
    }
    .yc-grid{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:0;
        background:#1a3a8f;
    }
    .yc-month{
        background:#fff;
        border-right:2px solid #1a3a8f;
        border-bottom:2px solid #1a3a8f;
        padding:6px 4px 8px 4px;
    }
    .yc-month:nth-child(4n){border-right:none;}
    .yc-month:nth-last-child(-n+4){border-bottom:none;}
    /* full month box highlight when audit is scheduled that month */
    .yc-month.has-audit-month{
        background:#dbeafe !important;
    }
    .yc-month.has-audit-month .yc-month-name{
        color:#1e3a8a;
    }
    .yc-month.has-audit-month .yc-weekday{
        color:#1e40af;
    }
    .yc-month-name{
        text-align:center;
        font-size:15px;
        font-weight:900;
        color:#0f172a;
        padding:2px 0 4px 0;
        letter-spacing:0.3px;
    }
    .yc-weekdays{
        display:grid;
        grid-template-columns:repeat(7,1fr);
    }
    .yc-weekday{
        text-align:center;
        font-size:10px;
        font-weight:800;
        color:#0f172a;
        padding:1px 0 3px 0;
    }
    .yc-days{
        display:grid;
        grid-template-columns:repeat(7,1fr);
    }
    .yc-day{
        text-align:center;
        font-size:11px;
        font-weight:600;
        color:#0f172a;
        padding:2px 1px;
        min-height:18px;
        line-height:16px;
    }
    .yc-day.muted{color:#cbd5e1;}
    /* plan date assigned in audit plan — dark navy circle */
    .yc-day.plan-date{
        background:#1a3a8f !important;
        color:#fff !important;
        font-weight:900;
        border-radius:50%;
        width:20px;
        height:20px;
        line-height:20px;
        margin:0 auto;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:10px;
    }
    /* today — black circle */
    .yc-day.today{
        background:#0f172a !important;
        color:#fff !important;
        border-radius:50%;
        font-weight:900;
    }
    .yc-legend{
        display:flex;gap:14px;flex-wrap:wrap;
        margin:8px 0 10px 0;
        align-items:center;
    }
    .yc-pill{
        display:inline-flex;align-items:center;gap:6px;
        padding:5px 10px;border-radius:999px;
        border:1px solid #e5e7eb;background:#fff;
        color:#334155;font-size:12px;font-weight:600;
    }
    .yc-pill i{display:inline-block;width:10px;height:10px;border-radius:50%;}
    /* month jump buttons */
    div[data-testid="stHorizontalBlock"] button[data-testid="baseButton-secondary"]{
        background:#dbeafe !important;
        color:#1e3a8a !important;
        border:1px solid #93c5fd !important;
        border-radius:8px !important;
        font-weight:700 !important;
        font-size:13px !important;
    }
    div[data-testid="stHorizontalBlock"] button[data-testid="baseButton-secondary"]:hover{
        background:#1a3a8f !important;
        color:#fff !important;
        border-color:#1a3a8f !important;
    }
    @media (max-width:1100px){
        .yc-grid{grid-template-columns:repeat(3,minmax(0,1fr));}
        .yc-month:nth-child(4n){border-right:2px solid #1a3a8f;}
        .yc-month:nth-child(3n){border-right:none;}
        .yc-month:nth-last-child(-n+4){border-bottom:2px solid #1a3a8f;}
        .yc-month:nth-last-child(-n+3){border-bottom:none;}
    }
    @media (max-width:800px){
        .yc-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
        .yc-month:nth-child(3n){border-right:2px solid #1a3a8f;}
        .yc-month:nth-child(2n){border-right:none;}
        .yc-month:nth-last-child(-n+3){border-bottom:2px solid #1a3a8f;}
        .yc-month:nth-last-child(-n+2){border-bottom:none;}
    }
    </style>""", unsafe_allow_html=True)

        # ── Create form ───────────────────────────────────────────────────────────
    st.markdown("""<style>
    div[data-testid="stExpander"]{
        border:1px solid #e2e8f0 !important;
        border-radius:12px !important;
        background:#ffffff !important;
        box-shadow:0 2px 8px rgba(15,23,42,0.05) !important;
    }
    div[data-testid="stExpander"] label p{
        font-size:13px !important;
        font-weight:700 !important;
        color:#374151 !important;
    }
    div[data-testid="stExpander"] button[kind="primaryFormSubmit"],
    div[data-testid="stExpander"] button[data-testid="baseButton-primaryFormSubmit"]{
        background:#4f46e5 !important;
        color:#ffffff !important;
        font-size:15px !important;
        font-weight:700 !important;
        border:none !important;
        border-radius:8px !important;
    }
    div[data-testid="stExpander"] button[kind="primaryFormSubmit"]:hover{
        background:#4338ca !important;
    }
    </style>""", unsafe_allow_html=True)

    year_list = list(range(today.year - 2, today.year + 10))

    with st.expander("➕ Create Audit Calendar", expanded=False):

        # Year | Start Month | Frequency — OUTSIDE form so they update live
        c1, c2, c3 = st.columns([1, 1.2, 1.2])
        audit_year  = c1.selectbox("Audit Year *",
            options=year_list,
            index=year_list.index(today.year),
            key="yc_audit_year")
        start_month = c2.selectbox("Audit Start Month *",
            options=list(range(1, 13)),
            format_func=lambda m: _calendar.month_name[m],
            key="yc_start_month")
        frequency   = c3.selectbox("Audit Frequency *",
            options=["Monthly", "Bi-monthly", "Quarterly", "Half-yearly"],
            index=2, key="yc_frequency")

        # Live occurrence calculation — updates instantly on every change
        step_months, auto_occ = _freq_step_and_count(str(frequency), int(start_month))
        occ_months = list(range(int(start_month), 13, step_months))
        occ_names  = ", ".join(_calendar.month_abbr[m] for m in occ_months)

        oc1, oc2 = st.columns([1, 3])
        oc1.metric("Audit Occurrence (auto)", auto_occ)
        oc2.info(f"**{auto_occ} audit(s) will be created** for: {occ_names}", icon="📌")

        # Title, Scope and Submit — inside form
        with st.form("create_calendar_audit_form"):
            title = st.text_input("Audit Title *",
                placeholder="e.g. BMR Compliance Audit", key="yc_title")
            scope = st.text_area("Audit Scope *",
                placeholder="e.g. QA – Batch Records", height=90, key="yc_scope")

            if st.form_submit_button("🗓  Create Audit Calendar",
                    use_container_width=True, type="primary"):
                if not str(title).strip():
                    st.error("Audit title is required.")
                elif not str(scope).strip():
                    st.error("Scope is required.")
                else:
                    occurrences = int(auto_occ)
                    first_date  = date(int(audit_year), int(start_month), 1)
                    created     = 0
                    last_msg    = ""

                    for i in range(occurrences):
                        sd = _add_months(first_date, step_months * i)
                        ed = sd
                        audit, msg = _engine_call(
                            "create_audit_calendar",
                            title=str(title).strip(),
                            scope=str(scope).strip(),
                            start_date=sd.isoformat(),
                            end_date=ed.isoformat(),
                            created_by=username,
                        )
                        last_msg = msg
                        if audit:
                            created += 1

                    if created == occurrences:
                        st.success(f"✅ Created {created} audit(s) for {int(audit_year)}.")
                        _rerun()
                    elif created > 0:
                        st.warning(f"Created {created}/{occurrences} audit(s). {last_msg}")
                        _rerun()
                    else:
                        st.error(last_msg or "Failed to create audits.")

    # ── View controls ─────────────────────────────────────────────────────────
    c1, c2 = st.columns([1, 3])
    selected_year = c1.selectbox("Select Year",
        options=year_list,
        index=year_list.index(today.year),
        key="yc_view_year")
    search_q = c2.text_input("Search", placeholder="Filter by title, scope, or owner", key="yc_search")

    cal = _cached_list_audit_calendar(tenant_id) or []
    year_start = date(int(selected_year), 1, 1)
    year_end   = date(int(selected_year), 12, 31)

    items = []
    for a in cal:
        sd, ed = _safe_date(a.get("start_date")), _safe_date(a.get("end_date"))
        if ed < sd:
            sd, ed = ed, sd
        if ed < year_start or sd > year_end:
            continue
        blob = " ".join(str(a.get(k, "")) for k in ["title", "scope", "created_by", "auditor", "owner"]).lower()
        if search_q and search_q.lower() not in blob:
            continue
        items.append({**a, "_sd": sd, "_ed": ed, "_bucket": _status_bucket(a)})

    # build day map
    month_day_map = {m: {} for m in range(1, 13)}
    for a in items:
        cur  = max(a["_sd"], year_start)
        last = min(a["_ed"], year_end)
        while cur <= last:
            month_day_map[cur.month].setdefault(cur.day, []).append(a)
            cur += timedelta(days=1)

    # ── Months that have an audit ───────────────────────────────────────────
    audit_months = set()
    for a in items:
        cur  = max(a["_sd"], year_start)
        last = min(a["_ed"], year_end)
        while cur <= last:
            audit_months.add(cur.month)
            cur += timedelta(days=1)

    # ── Plan dates from audit plan ────────────────────────────────────────────
    raw_plan_dates = _engine_call("list_all_plan_dates", tenant_id) or []
    plan_date_set  = set()
    plan_date_tips = {}
    for pd in raw_plan_dates:
        try:
            d = date.fromisoformat(str(pd.get("plan_date", "")))
            if d.year == int(selected_year):
                plan_date_set.add((d.month, d.day))
                plan_date_tips[(d.month, d.day)] = str(pd.get("title", "Audit")).strip()
        except Exception:
            pass

    # ── Legend ────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="yc-legend">'
        '<span class="yc-pill"><i style="background:#dbeafe;border:1px solid #93c5fd"></i>Audit month</span>'
        '<span class="yc-pill"><i style="background:#1a3a8f"></i>Planned date</span>'
        '<span class="yc-pill"><i style="background:#0f172a"></i>Today</span>'
        f'<span style="font-size:12px;color:#64748b;font-weight:600;margin-left:6px;">{len(items)} audit(s) · {len(plan_date_set)} planned date(s) in {int(selected_year)}</span>'
        '</div>',
        unsafe_allow_html=True)

        # ── Calendar: big year banner + 4×3 grid ─────────────────────────────────
    weekdays = ["S", "M", "T", "W", "T", "F", "S"]

    months_html = ""
    for month in range(1, 13):
        # Sunday-first offset: Python weekday() is 0=Mon, so Sun=+1 mod 7
        first_dow = (date(int(selected_year), month, 1).weekday() + 1) % 7
        days_in_month = _calendar.monthrange(int(selected_year), month)[1]

        wd_html = "".join(f'<div class="yc-weekday">{d}</div>' for d in weekdays)

        cells = ""
        # blank cells before day 1
        for _ in range(first_dow):
            cells += '<div class="yc-day muted"></div>'

        for day_num in range(1, days_in_month + 1):
            is_today     = (int(selected_year) == today.year and month == today.month and day_num == today.day)
            is_plan_date = (month, day_num) in plan_date_set

            if is_today:
                cls = "yc-day today"
            elif is_plan_date:
                cls = "yc-day plan-date"
            else:
                cls = "yc-day"

            tooltip = ""
            if is_plan_date and (month, day_num) in plan_date_tips:
                tooltip = ' title="' + plan_date_tips[(month, day_num)].replace('"', "&quot;") + '"'

            cells += f'<div class="{cls}"{tooltip}>{day_num}</div>'
        month_cls = "yc-month has-audit-month" if month in audit_months else "yc-month"
        months_html += (
            f'<div class="{month_cls}">'
            f'<div class="yc-month-name">{_calendar.month_name[month]}</div>'
            f'<div class="yc-weekdays">{wd_html}</div>'
            f'<div class="yc-days">{cells}</div>'
            f'</div>'
        )

    # ── Clickable month buttons (only for months with audits) ─────────────────
    st.markdown("#### 🗓 Jump to Audit Plan")
    btn_cols = st.columns(6)
    audit_month_list = sorted(audit_months)
    if not audit_month_list:
        st.caption("No audits scheduled for this year.")
    else:
        # find which audit belongs to each month
        def _audits_for_month(m):
            return [a for a in items
                    if any(
                        (max(a["_sd"], year_start) <= date(int(selected_year), m, d) <= min(a["_ed"], year_end))
                        for d in [1]  # just check if start is in this month
                    ) or a["_sd"].month == m or a["_ed"].month == m]

        for idx, m in enumerate(range(1, 13)):
            col = btn_cols[idx % 6]
            if m in audit_months:
                if col.button(_calendar.month_abbr[m], key=f"yc_goto_{m}_{selected_year}", use_container_width=True):
                    # find the audit for this month and pre-select it in audit plan
                    matched = [a for a in items if a["_sd"].month == m or a["_ed"].month == m]
                    if matched:
                        a = matched[0]
                        label = f"{a.get('title','')}  ({a.get('start_date','')} → {a.get('end_date','')})"
                        st.session_state["ap_sel_audit"] = label
                    st.session_state["_nav_to"] = "Audit Plan"
                    _rerun()

    st.markdown(
        f'<div class="yc-outer">'
        f'<div class="yc-year-banner">{int(selected_year)}</div>'
        f'<div class="yc-grid">{months_html}</div>'
        f'</div>',
        unsafe_allow_html=True)


def page_audit_plan():
    st.title("Audit Plan")
    st.caption("Select an audit, set the start date and duration, configure time slots, then assign departments and auditors.")

    tenant_id = st.session_state.auth.get("tenant_id")
    username  = st.session_state.auth.get("username", "")
    today     = date.today()

    # ── CSS ───────────────────────────────────────────────────────────────────
    st.markdown("""<style>
    .ap-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;
             padding:14px 16px;margin-bottom:12px;
             box-shadow:0 2px 10px rgba(15,23,42,0.04);}
    .ap-label{font-size:11px;font-weight:700;color:#64748b;
              text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;}
    .ap-value{font-size:14px;font-weight:700;color:#0f172a;}
    .ap-meta {font-size:12px;color:#64748b;margin-top:2px;}
    .day-head{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
              padding:8px 14px;margin:18px 0 10px;
              font-size:13px;font-weight:800;color:#0f172a;
              display:flex;align-items:center;gap:10px;}
    .slot-row{background:#fff;border:1px solid #e2e8f0;border-radius:8px;
              padding:10px 14px;margin-bottom:8px;}
    .slot-time{font-size:12px;font-weight:800;color:#3b82f6;
               background:#eff6ff;border-radius:6px;padding:3px 8px;
               display:inline-block;white-space:nowrap;}
    /* ── fix multiselect tag: light bg, dark readable text ── */
    span[data-baseweb="tag"]{
        background:#e0f2fe !important;
        border:1px solid #7dd3fc !important;
        border-radius:6px !important;
    }
    span[data-baseweb="tag"] span{
        color:#0c4a6e !important;
        font-weight:600 !important;
        font-size:12px !important;
    }
    span[data-baseweb="tag"] svg{
        fill:#0369a1 !important;
    }
    </style>""", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 1 — Select Audit
    # ════════════════════════════════════════════════════════════════════════
    cal = _cached_list_audit_calendar(tenant_id) or []
    if not cal:
        st.info("No audits found in Audit Calendar. Create an audit first.")
        return

    st.markdown("### Step 1 — Select Audit")
    by_label = {
        f"{a.get('title','')}  ({a.get('start_date','')} → {a.get('end_date','')})": a
        for a in cal}
    sel_label = st.selectbox("Audit", options=list(by_label.keys()), key="ap_sel_audit")
    audit             = by_label[sel_label]
    calendar_audit_id = audit.get("id")

    # Show audit info card
    st.markdown(
        f'<div class="ap-card">'
        f'<div class="ap-value">{audit.get("title","")}</div>'
        f'<div class="ap-meta">'
        f'{audit.get("start_date","")} → {audit.get("end_date","")}'
        f'</div>'
        f'<div style="font-size:12px;color:#475569;margin-top:5px;">'
        f'<b>Scope:</b> {audit.get("scope","—")}'
        f'</div></div>',
        unsafe_allow_html=True)

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # STEP 2 — Configure Plan (duration → pick each day → time slots)
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("### Step 2 — Configure Plan")

    # default start from audit record
    default_sd = today
    try:    default_sd = date.fromisoformat(str(audit.get("start_date") or today))
    except: pass

    # Duration picker — drives how many date pickers appear
    duration_days = st.number_input(
        "Duration — how many days will this audit be conducted?",
        min_value=1, max_value=30, value=1, step=1, key="ap_duration",
        help="Set this first. One date picker per day will appear below.")

    duration_days = int(duration_days)

    # One date picker per audit day
    st.markdown(f"**Select the date for each of the {duration_days} audit day(s):**")
    st.caption("Days do not have to be consecutive — pick any dates that suit your schedule.")

    audit_dates = []
    date_cols = st.columns(min(duration_days, 4))   # max 4 per row
    for i in range(duration_days):
        col = date_cols[i % 4] if duration_days > 1 else st.columns([1, 3])[0]
        # default: day i starts from default_sd + i calendar days
        default_di = default_sd + timedelta(days=i)
        picked = col.date_input(
            f"Day {i+1}",
            value=default_di,
            key=f"ap_day_{i}_{calendar_audit_id}",
            help=f"Choose the date for audit day {i+1}")
        audit_dates.append(picked)

    # Duplicate-date warning
    unique_dates = list(dict.fromkeys(audit_dates))   # preserve order, remove dupes
    if len(unique_dates) < len(audit_dates):
        st.warning("⚠️ Some dates are the same. Duplicate dates will be merged into one day.")

    # Time slots — admin configures which slots to include each day
    st.markdown("**Time Slots** — select which time slots to include on each audit day")
    ALL_SLOTS = [
        ("09:00","10:00"), ("09:30","10:30"),
        ("10:00","11:00"), ("10:30","11:30"),
        ("11:00","12:00"), ("11:30","12:30"),
        ("12:00","13:00"), ("12:30","13:30"),
        ("13:00","14:00"), ("13:30","14:30"),
        ("14:00","15:00"), ("14:30","15:30"),
        ("15:00","16:00"), ("15:30","16:30"),
        ("16:00","17:00"),
    ]
    slot_labels  = [f"{s0} – {s1}" for s0, s1 in ALL_SLOTS]
    default_sel  = [f"{s0} – {s1}" for s0, s1 in [
        ("09:30","10:30"),("10:30","11:30"),("11:30","12:30"),
        ("12:30","13:30"),("13:30","14:30"),("14:30","15:30"),("15:30","16:30")]]
    chosen_labels = st.multiselect(
        "Time slots for each audit day",
        options=slot_labels,
        default=[l for l in default_sel if l in slot_labels],
        key="ap_slots",
        help="Each selected slot appears as one row per day in the schedule.")
    chosen_slots = [ALL_SLOTS[slot_labels.index(l)] for l in chosen_labels if l in slot_labels]

    # Live summary
    if unique_dates and chosen_slots:
        total_rows = len(unique_dates) * len(chosen_slots)
        date_strs  = ", ".join(d.strftime("%d %b %Y") for d in sorted(unique_dates))
        st.info(
            f"📋 **{len(unique_dates)} day(s)** × **{len(chosen_slots)} slot(s)** "
            f"= **{total_rows} total rows**\n\n"
            f"Dates: {date_strs}",
            icon="📌")

    # Create / Reset Plan button
    st.write("")
    if st.button("🗓 Create / Reset Plan", type="primary", key="ap_create_plan"):
        if not chosen_slots:
            st.error("Please select at least one time slot.")
        elif not unique_dates:
            st.error("Please select at least one audit date.")
        else:
            p, msg = _engine_call(
                "create_audit_plan_with_dates",
                calendar_audit_id = calendar_audit_id,
                audit_dates       = [d.isoformat() for d in unique_dates],
                created_by        = username,
                custom_slots      = chosen_slots)
            if p:
                st.success(f"✅ {msg}")
                st.cache_data.clear()
                _rerun()
            else:
                st.error(msg)

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # STEP 3 — Schedule: assign department + auditor + notes per slot
    # ════════════════════════════════════════════════════════════════════════
    plan = _engine_call(
        "get_audit_plan_by_calendar_audit",
        calendar_audit_id=calendar_audit_id)

    if not plan:
        st.info("Use the form above to create the audit plan first.")
        return

    slots = plan.get("slots", []) or []
    if not slots:
        st.warning("No slots found — click 'Create / Reset Plan' to generate them.")
        return

    st.markdown("### Step 3 — Assign Departments & Auditors")
    st.caption("Rules: An auditor cannot audit their own department. Skills must match the department's required skills.")

    # Load reference data
    dept_list    = _engine_call("list_departments_simple", tenant_id) or []
    dept_options = [""] + [d for d in dept_list if d]
    people       = _cached_people(tenant_id) or []
    state        = _cached_state(tenant_id) or {}

    def _norm(s): return " ".join(str(s or "").strip().split()).lower()

    def eligible_auditors_for(department: str, date_str: str, slot_str: str) -> list:
        dep = (department or "").strip()
        if not dep: return []
        required = set(_engine_call("get_required_skills_for_dept", dep, tenant_id=tenant_id) or set())
        eligible = []
        for p in people:
            p_name  = getattr(p, "name", "")
            p_dept  = getattr(p, "department", "")
            p_skills= set(getattr(p, "skills", set()) or set())
            # Rule 1: cannot audit own department
            if _norm(p_dept) and _norm(p_dept) == _norm(dep): continue
            # Rule 2: must have required skills
            if required and not required.issubset(p_skills): continue
            # Rule 3: must not be busy
            if engine.is_busy(state, p_name): continue
            eligible.append(p_name)
        return sorted(set(x for x in eligible if x))

    # Session state for edits
    ss_key = f"ap_edits_{plan.get('plan_id')}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = {
            s.get("id"): {
                "department":   s.get("department") or "",
                "auditor_name": s.get("auditor_name") or "",
                "notes":        s.get("notes") or "",
            } for s in slots}
    edits = st.session_state[ss_key]

    # Render by day
    grouped = {}
    for s in slots:
        grouped.setdefault(s.get("plan_date",""), []).append(s)

    for day_str in sorted(grouped.keys()):
        try:    day_label = date.fromisoformat(day_str).strftime("%A, %d %b %Y")
        except: day_label = day_str

        st.markdown(
            f'<div class="day-head">📅 {day_label}</div>',
            unsafe_allow_html=True)

        for s in grouped[day_str]:
            sid      = s.get("id")
            s0, s1   = s.get("slot_start",""), s.get("slot_end","")
            slot_str = f"{s0}-{s1}"
            row      = edits.get(sid, {"department":"","auditor_name":"","notes":""})

            st.markdown(
                f'<div style="margin-bottom:4px;">'
                f'<span class="slot-time">🕐 {s0} – {s1}</span>'
                f'</div>',
                unsafe_allow_html=True)

            col_dept, col_aud, col_notes = st.columns([2, 2, 3])

            dept_val = col_dept.selectbox(
                "Department",
                options=dept_options,
                index=dept_options.index(row["department"]) if row["department"] in dept_options else 0,
                key=f"ap_dept_{sid}")

            aud_opts = [""] + eligible_auditors_for(dept_val, day_str, slot_str)
            cur_aud  = row["auditor_name"] if row["auditor_name"] in aud_opts else ""
            aud_val  = col_aud.selectbox(
                "Auditor",
                options=aud_opts,
                index=aud_opts.index(cur_aud) if cur_aud in aud_opts else 0,
                key=f"ap_aud_{sid}",
                help="Only auditors eligible for this department are shown.")

            notes_val = col_notes.text_input(
                "Notes",
                value=row["notes"],
                placeholder="Any specific instructions for this slot...",
                key=f"ap_notes_{sid}")

            edits[sid] = {
                "department":   dept_val   or "",
                "auditor_name": aud_val    or "",
                "notes":        notes_val  or "",
            }

    st.write("")

    # ── Action buttons ────────────────────────────────────────────────────
    ba, bb = st.columns(2)

    if ba.button("⚡ Auto-assign Missing Auditors", use_container_width=True):
        ok, msg = _engine_call("auto_assign_auditors", tenant_id, plan["plan_id"])
        if ok:
            st.success(msg)
            st.cache_data.clear()
            _rerun()
        else:
            st.error(msg)

    if bb.button("💾 Save Audit Plan", type="primary", use_container_width=True):
        payload = []
        for s in slots:
            sid = s.get("id")
            e   = edits.get(sid, {})
            payload.append({
                "plan_date":    s.get("plan_date"),
                "slot_start":   s.get("slot_start"),
                "slot_end":     s.get("slot_end"),
                "department":   e.get("department",""),
                "auditor_name": e.get("auditor_name",""),
                "notes":        e.get("notes",""),
            })
        ok, msg = _engine_call(
            "update_audit_plan_slots", tenant_id, plan["plan_id"], payload)
        if ok:
            st.success(f"✅ {msg}")
        else:
            st.error(msg)

require_login()

role = st.session_state.auth["role"]
username = st.session_state.auth["username"]
person_name = st.session_state.auth.get("person_name")

render_topbar(username=username, role=role)

if role == "auditor" and person_name and _HAS_TIMETABLE:
    show_auditor_timetable_reminder(person_name, remind_within_minutes=30)

tenant_id = st.session_state.auth.get("tenant_id")
all_audits = _cached_list_audits(tenant_id)
my_audits = [a for a in all_audits if a.get("assigned_auditor") == person_name] if role == "auditor" else []

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    tenant_code    = st.session_state.auth.get('tenant_code','default')
    initials       = (username[:2] if username else "AU").upper()
    role_badge_bg  = "rgba(52,211,153,0.20)" if role == "admin" else "rgba(129,140,248,0.20)"
    role_badge_clr = "#34d399" if role == "admin" else "#818cf8"
    role_label     = "Administrator" if role == "admin" else "Auditor"
    st.markdown(
        '<div class="sb-logo">'
        '<div style="display:flex;align-items:center;gap:11px;">'
        '<div style="width:38px;height:38px;border-radius:11px;background:rgba(255,255,255,0.22);'
        'display:flex;align-items:center;justify-content:center;font-size:19px;flex-shrink:0;">&#128203;</div>'
        '<div>'
        '<div class="sb-logo-title">AMS</div>'
        '<div class="sb-logo-sub">Audit Management System</div>'
        '</div></div>'
        '</div>'
        '<div class="sb-user">'
        '<div style="display:flex;align-items:center;gap:11px;">'
        '<div style="width:38px;height:38px;border-radius:11px;flex-shrink:0;'
        'background:linear-gradient(135deg,#34d399,#059669);'
        'display:flex;align-items:center;justify-content:center;'
        'font-size:13px;font-weight:800;color:#fff;letter-spacing:.5px;">' + initials + '</div>'
        '<div style="min-width:0;">'
        '<div class="sb-user-name">' + username.title() + '</div>'
        '<div style="margin-top:5px;">'
        '<span style="font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;'
        'background:' + role_badge_bg + ';color:' + role_badge_clr + ';'
        'border-radius:6px;padding:2px 9px;">' + role_label + '</span>'
        '</div>'
        '</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.button("⏋  Logout", on_click=logout, use_container_width=True)
    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    if st.session_state.pop("_do_rerun", False):
        st.rerun()

# ── Page functions ────────────────────────────────────────────────────────────
def page_admin_dashboard():
    tenant_id = _current_tenant_id()

    # ── Compute metrics ───────────────────────────────────────────────────────
    total        = len(all_audits)
    closed_count = sum(1 for a in all_audits if str(a.get("status","")).strip().lower() == "closed")
    open_count   = sum(1 for a in all_audits if str(a.get("status","")).strip().lower() in ("assigned","in progress"))
    in_progress  = sum(1 for a in all_audits if str(a.get("status","")).strip().lower() == "in progress")
    rep_submitted= sum(1 for a in all_audits if str(a.get("status","")).strip().lower() == "report submitted")
    no_report    = sum(1 for a in all_audits if not a.get("reports") and str(a.get("status","")).strip().lower() != "closed")
    people       = _cached_people(tenant_id)
    state        = _cached_state(tenant_id)
    busy_count   = sum(1 for p in people if engine.is_busy(state, p.name))
    free_count   = len(people) - busy_count

    # ── CSS ───────────────────────────────────────────────────────────────────
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap');

    .db-root { font-family: 'DM Sans', sans-serif; }

    /* header */
    .db-header {
        background: linear-gradient(135deg, #0a1628 0%, #0f2347 60%, #1a3a6e 100%);
        border-radius: 16px; padding: 32px 36px; margin-bottom: 28px;
        display: flex; align-items: center; justify-content: space-between;
        position: relative; overflow: hidden;
    }
    .db-header::before {
        content: ''; position: absolute; top: -40px; right: -40px;
        width: 220px; height: 220px; border-radius: 50%;
        background: rgba(99,102,241,.12); pointer-events: none;
    }
    .db-header::after {
        content: ''; position: absolute; bottom: -60px; right: 80px;
        width: 160px; height: 160px; border-radius: 50%;
        background: rgba(99,102,241,.07); pointer-events: none;
    }
    .db-header-left {}
    .db-header-eyebrow {
        font-size: 11px; font-weight: 600; letter-spacing: 2.5px;
        text-transform: uppercase; color: #818cf8; margin-bottom: 6px;
    }
    .db-header-title {
        font-family: 'Playfair Display', serif;
        font-size: 30px; font-weight: 900; color: #f0f4ff;
        line-height: 1.15; margin-bottom: 8px;
    }
    .db-header-sub { font-size: 13px; color: #94a3b8; font-weight: 400; }
    .db-header-badge {
        background: rgba(99,102,241,.18); border: 1px solid rgba(99,102,241,.35);
        border-radius: 10px; padding: 14px 22px; text-align: center; z-index: 1;
    }
    .db-header-badge-num {
        font-family: 'Playfair Display', serif;
        font-size: 36px; font-weight: 900; color: #c7d2fe; line-height: 1;
    }
    .db-header-badge-lbl { font-size: 11px; color: #818cf8; font-weight: 500; margin-top: 4px; }

    /* quick action buttons */
    .db-actions { display: flex; gap: 10px; margin-bottom: 28px; flex-wrap: wrap; }

    /* section title */
    .db-section-title {
        font-family: 'Playfair Display', serif;
        font-size: 17px; font-weight: 700; color: #0f172a;
        border-left: 4px solid #4f46e5; padding-left: 12px;
        margin: 28px 0 16px;
    }

    /* KPI cards */
    .db-kpi-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 8px; }
    .db-kpi {
        background: #fff; border: 1px solid #e8edf5;
        border-radius: 14px; padding: 20px 22px;
        position: relative; overflow: hidden;
        box-shadow: 0 2px 8px rgba(15,23,42,.05);
        transition: box-shadow .2s;
    }
    .db-kpi:hover { box-shadow: 0 6px 20px rgba(15,23,42,.1); }
    .db-kpi-accent {
        position: absolute; top: 0; left: 0; right: 0; height: 3px;
        border-radius: 14px 14px 0 0;
    }
    .db-kpi-icon {
        width: 38px; height: 38px; border-radius: 10px;
        display: flex; align-items: center; justify-content: center;
        font-size: 17px; margin-bottom: 14px;
    }
    .db-kpi-value {
        font-family: 'Playfair Display', serif;
        font-size: 34px; font-weight: 900; color: #0f172a;
        line-height: 1; margin-bottom: 4px;
    }
    .db-kpi-label { font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 3px; }
    .db-kpi-meta  { font-size: 11px; color: #94a3b8; font-weight: 400; }

    /* auditor availability row */
    .db-avail-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 14px; }
    .db-avail-card {
        background: #fff; border: 1px solid #e8edf5;
        border-radius: 14px; padding: 20px 22px;
        display: flex; align-items: center; gap: 16px;
        box-shadow: 0 2px 8px rgba(15,23,42,.05);
    }
    .db-avail-dot {
        width: 48px; height: 48px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 20px; flex-shrink: 0;
    }
    .db-avail-num {
        font-family: 'Playfair Display', serif;
        font-size: 28px; font-weight: 900; line-height: 1;
    }
    .db-avail-lbl { font-size: 12px; font-weight: 600; color: #64748b; margin-top: 2px; }

    /* audit status mini-bar */
    .db-mini-bar { display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }
    .db-mini-chip {
        display: flex; align-items: center; gap: 7px;
        padding: 7px 14px; border-radius: 999px;
        font-size: 12px; font-weight: 700; border: 1.5px solid;
    }
    .db-mini-dot { width: 8px; height: 8px; border-radius: 50%; }

    /* scrollable audit table */
    .db-table-wrap {
        background: #fff; border: 1px solid #e8edf5;
        border-radius: 14px; overflow: hidden;
        box-shadow: 0 2px 8px rgba(15,23,42,.05);
        margin-bottom: 8px;
    }
    .db-table-head {
        background: #f8fafc; border-bottom: 1px solid #e8edf5;
        display: grid; grid-template-columns: 2fr 1.2fr 1.2fr 1fr 1fr;
        padding: 11px 20px; gap: 12px;
    }
    .db-th { font-size: 11px; font-weight: 700; color: #64748b;
             letter-spacing: .7px; text-transform: uppercase; }
    .db-table-row {
        display: grid; grid-template-columns: 2fr 1.2fr 1.2fr 1fr 1fr;
        padding: 13px 20px; gap: 12px; border-bottom: 1px solid #f1f5f9;
        align-items: center;
    }
    .db-table-row:last-child { border-bottom: none; }
    .db-table-row:hover { background: #fafbff; }
    .db-td { font-size: 13px; color: #1e293b; font-weight: 500; }
    .db-td-sub { font-size: 11px; color: #94a3b8; font-weight: 400; margin-top: 2px; }

    /* password section */
    .db-pw-box {
        background: #fff; border: 1px solid #e8edf5;
        border-radius: 14px; padding: 24px 26px;
        box-shadow: 0 2px 8px rgba(15,23,42,.05);
    }
    </style>""", unsafe_allow_html=True)

    st.markdown('<div class="db-root">', unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    from datetime import date as _date
    today_str = _date.today().strftime("%B %d, %Y")
    st.markdown(f"""
    <div class="db-header">
      <div class="db-header-left">
        <div class="db-header-eyebrow">Audit Management System</div>
        <div class="db-header-title">Executive Dashboard</div>
        <div class="db-header-sub">Portfolio overview &nbsp;·&nbsp; {today_str}</div>
      </div>
      <div class="db-header-badge">
        <div class="db-header-badge-num">{total}</div>
        <div class="db-header-badge-lbl">Total Audits</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Quick Actions ─────────────────────────────────────────────────────────
    qa1, qa2, qa3, qa4 = st.columns([1,1,1,3])
    if qa1.button("📅 Audit Calendar",  key="db_qa_create",  use_container_width=True, type="primary"):
        st.session_state["_nav_to"] = "Audit Calender"
        st.rerun()
    if qa2.button("🗓 Audit Plan",       key="db_qa_plan",    use_container_width=True):
        st.session_state["_nav_to"] = "Audit Plan"
        st.rerun()
    if qa3.button("📊 Final Reports",   key="db_qa_pdf",     use_container_width=True):
        st.session_state["_nav_to"] = "Reports"
        st.rerun()

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    st.markdown('<div class="db-section-title">Audit Portfolio</div>', unsafe_allow_html=True)

    kpis = [
        ("#4f46e5","#eef2ff","📋","Total Audits",    str(total),       "All time"),
        ("#f59e0b","#fffbeb","⚡","Open Audits",     str(open_count),  "Assigned or in progress"),
        ("#10b981","#ecfdf5","✅","Closed Audits",   str(closed_count),"Completed"),
        ("#ef4444","#fef2f2","⚠️","Pending Reports", str(no_report),   "No upload yet"),
    ]
    cols = st.columns(4)
    for col, (accent, iconbg, icon, label, val, meta) in zip(cols, kpis):
        with col:
            st.markdown(f"""
            <div class="db-kpi">
              <div class="db-kpi-accent" style="background:{accent};"></div>
              <div class="db-kpi-icon" style="background:{iconbg};">{icon}</div>
              <div class="db-kpi-value">{val}</div>
              <div class="db-kpi-label">{label}</div>
              <div class="db-kpi-meta">{meta}</div>
            </div>""", unsafe_allow_html=True)

    # ── Status breakdown ──────────────────────────────────────────────────────
    st.write("")
    breakdown = [
        ("#f8fafc","#0f172a","#e2e8f0","Assigned",         sum(1 for a in all_audits if str(a.get("status","")).strip().lower()=="assigned")),
        ("#fff7ed","#9a3412","#fed7aa","In Progress",       in_progress),
        ("#eff6ff","#1e3a8a","#bfdbfe","Report Submitted",  rep_submitted),
        ("#ecfdf5","#065f46","#a7f3d0","Closed",            closed_count),
    ]
    chips_html = "".join(
        f'<div class="db-mini-chip" style="background:{bg};color:{fg};border-color:{bd};">'
        f'<div class="db-mini-dot" style="background:{fg};opacity:.7;"></div>'
        f'{lbl}&nbsp;<b>{cnt}</b></div>'
        for bg,fg,bd,lbl,cnt in breakdown
    )
    st.markdown(f'<div class="db-mini-bar">{chips_html}</div>', unsafe_allow_html=True)

    # ── Auditor Availability ──────────────────────────────────────────────────
    st.markdown('<div class="db-section-title">Auditor Availability</div>', unsafe_allow_html=True)
    av1, av2, av3 = st.columns([1,1,2])
    with av1:
        st.markdown(f"""<div class="db-avail-card">
          <div class="db-avail-dot" style="background:#ecfdf5;">🟢</div>
          <div>
            <div class="db-avail-num" style="color:#10b981;">{free_count}</div>
            <div class="db-avail-lbl">Auditors Available</div>
          </div>
        </div>""", unsafe_allow_html=True)
    with av2:
        st.markdown(f"""<div class="db-avail-card">
          <div class="db-avail-dot" style="background:#fff7ed;">🔴</div>
          <div>
            <div class="db-avail-num" style="color:#f59e0b;">{busy_count}</div>
            <div class="db-avail-lbl">Currently Engaged</div>
          </div>
        </div>""", unsafe_allow_html=True)

    # ── Auditor List ──────────────────────────────────────────────────────────
    st.markdown('<div class="db-section-title">Auditor Directory</div>', unsafe_allow_html=True)
    skill_cat = get_skill_catalog()
    aud_parts = []
    for p in sorted(people, key=lambda x: (x.department.lower(), x.name.lower())):
        status_bg  = "#ecfdf5" if not engine.is_busy(state, p.name) else "#fff7ed"
        status_fg  = "#065f46" if not engine.is_busy(state, p.name) else "#9a3412"
        status_bd  = "#a7f3d0" if not engine.is_busy(state, p.name) else "#fed7aa"
        status_lbl = "Available" if not engine.is_busy(state, p.name) else "Engaged"
        status_dot = "#10b981" if not engine.is_busy(state, p.name) else "#f59e0b"
        level_bg   = "#eef2ff" if p.level == "experienced" else "#f0fdf4"
        level_fg   = "#3730a3" if p.level == "experienced" else "#166534"
        level_lbl  = p.level.title()
        skills_str = ", ".join(skill_cat.get(k, k) for k in sorted(p.skills)) or "—"
        chip_status = (
            '<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;'
            'border-radius:999px;border:1px solid ' + status_bd + ';background:' + status_bg + ';'
            'color:' + status_fg + ';font-size:11px;font-weight:700;">'
            '<span style="width:7px;height:7px;border-radius:50%;background:' + status_dot + ';display:inline-block;"></span>'
            + status_lbl + '</span>'
        )
        chip_level = (
            '<span style="display:inline-flex;padding:3px 10px;border-radius:999px;'
            'background:' + level_bg + ';color:' + level_fg + ';font-size:11px;font-weight:700;">'
            + level_lbl + '</span>'
        )
        aud_parts.append(
            '<div class="db-table-row" style="grid-template-columns:1.5fr 1fr 1fr;">'
            '<div class="db-td">' + p.name + '<div class="db-td-sub">' + p.department + '</div></div>'
            '<div class="db-td">' + chip_level + '</div>'
            '<div class="db-td">' + chip_status + '</div>'
            '</div>'
        )
    if not aud_parts:
        aud_parts = ['<div style="padding:28px;text-align:center;color:#94a3b8;font-size:13px;">No auditors found.</div>']
    aud_table = (
        '<div class="db-table-wrap">'
        '<div class="db-table-head" style="grid-template-columns:1.5fr 1fr 1fr;">'
        '<div class="db-th">Name / Department</div>'
        '<div class="db-th">Level</div>'
        '<div class="db-th">Availability</div>'
        '</div>'
        + "".join(aud_parts) +
        '</div>'
    )
    st.markdown(aud_table, unsafe_allow_html=True)

    # ── Security Settings ─────────────────────────────────────────────────────
    st.markdown('<div class="db-section-title">Security</div>', unsafe_allow_html=True)
    st.markdown('<div class="db-pw-box">', unsafe_allow_html=True)

    st.caption("Change your login username. This affects only your account.")
    current_username = st.session_state.auth.get("username", "")
    st.text_input("Current username", value=current_username, disabled=True)
    with st.form("admin_change_username_form"):
        new_username = st.text_input("New username")
        username_pw = st.text_input("Current password", type="password", key="admin_username_current_password")
        submit_username = st.form_submit_button("Update Username", type="primary")
    if submit_username:
        if not new_username.strip():
            st.error("New username is required.")
        elif new_username.strip().lower() == (current_username or "").strip().lower():
            st.error("Please enter a different username.")
        elif not username_pw:
            st.error("Current password is required.")
        else:
            ok, new_uname, msg = engine.change_username(
                username=current_username,
                new_username=new_username,
                current_password=username_pw,
                tenant_id=st.session_state.auth.get("tenant_id"),
            )
            if ok:
                st.session_state.auth["username"] = new_uname
                st.success(msg)
            else:
                st.error(msg)

    st.write("")
    st.caption("Change your login password. This affects only your account.")
    with st.form("admin_change_password_form"):
        old_pw     = st.text_input("Current password",  type="password")
        new_pw     = st.text_input("New password",       type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")
        submit_pw  = st.form_submit_button("Update Password", type="primary")
    if submit_pw:
        if not old_pw or not new_pw:
            st.error("All fields are required.")
        elif new_pw != confirm_pw:
            st.error("New password and confirm password do not match.")
        else:
            ok, msg = engine.change_password(
                username=st.session_state.auth.get("username"),
                old_password=old_pw, new_password=new_pw,
                tenant_id=st.session_state.auth.get("tenant_id"))
            st.success(msg) if ok else st.error(msg)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def page_admin_auditors_skills():
    st.title("Auditors & Skills")
    st.caption("Add auditors (name, dept, skills). New departments/skills added via 'Other' will appear in dropdowns next time.")
    left, right = st.columns([1, 1])

    with left:
        render_panel("Add New Auditor", "Create auditor profiles and maintain the controlled skill library.")
        st.write("")
        skill_cat = get_skill_catalog()
        skill_keys = sorted(skill_cat.keys())
        with st.form("add_auditor_form"):
            name = st.text_input("Auditor Name", placeholder="e.g., Suman Kumar")
            dept_choice = st.selectbox("Department", get_department_options_with_other())
            custom_dept = st.text_input("Enter new department", placeholder="e.g., Production, QA, Stores") if dept_choice == "Other" else ""
            department = custom_dept.strip() if dept_choice == "Other" else dept_choice
            level = st.selectbox("Level", ["experienced", "fresher"])
            selected_skill_keys = st.multiselect("Skills", options=skill_keys + ["OTHER"], format_func=lambda k: skill_cat.get(k, k) if k != "OTHER" else "Other")
            custom_skill_keys: List[str] = []
            if "OTHER" in selected_skill_keys:
                custom_skills_text = st.text_area("Enter new skill(s) (one per line). These will be saved and appear in dropdown next time.", placeholder="e.g.\nCAPA effectiveness review\nCleanroom audit basics", height=120)
                for lbl in [s.strip() for s in custom_skills_text.splitlines() if s.strip()]:
                    custom_skill_keys.append(_engine_call("ensure_skill_in_catalog", lbl))
            final_skill_keys = set([k for k in selected_skill_keys if k != "OTHER"] + custom_skill_keys)
            password = st.text_input("Initial Password", value="auditor123")
            submitted = st.form_submit_button("Add Auditor", type="primary")
        if submitted:
            if not name.strip():
                st.error("Auditor Name is required.")
            elif not department.strip():
                st.error("Department is required.")
            elif not final_skill_keys:
                st.error("Please select at least one skill.")
            else:
                if dept_choice == "Other" and department.strip():
                    _engine_call("add_department_to_catalog", department.strip())
                ok, msg = _engine_call("add_auditor", name=name, department=department, level=level, skills=final_skill_keys, password=password.strip() or "auditor123")
                if ok:
                    st.success(msg); _clear_caches_and_rerun()
                else:
                    st.error(msg)

    with right:
        render_panel("Auditor Dashboard", "All auditors loaded from people.json.")
        st.write("")
        people_raw = _engine_call("list_people_records")
        state = _cached_state(tenant_id)
        skill_cat = get_skill_catalog()
        rows = [{"Name": nm, "Department": p.get("department"), "Level": p.get("level"), "Skills": ", ".join(skill_cat.get(k, k) for k in p.get("skills", [])), "Status": "BUSY" if engine.is_busy(state, nm) else "FREE", "Username": nm.strip().lower().replace(" ", "")} for p in sorted(people_raw, key=lambda x: (str(x.get("department", "")), str(x.get("name", "")).lower())) for nm in [str(p.get("name", "")).strip()]]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.markdown("### Delete Auditor")
        delete_name = st.text_input("Enter exact auditor name to delete", placeholder="e.g., Suman Kumar")
        if st.button("Delete Auditor"):
            ok, msg = _engine_call("delete_auditor", delete_name)
            if ok:
                st.success(msg); _clear_caches_and_rerun()
            else:
                st.error(msg)

def page_admin_checklist():
    st.title("Checklist (Admin)")
    st.caption("Create department-wise checklists with sections and tree structure. Each main question can have sub-questions (A, B…) and sub-sub questions (a, b…).")
    import pandas as pd
    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu.")
        st.stop()
    dept_for_checklist = checklist_department
    render_panel("Checklist Library", f"Department: {dept_for_checklist}")
    st.write("")
    sections = _cached_sections_for_dept(_current_tenant_id(), dept_for_checklist)
    pick_section = st.selectbox("Section", ["(Create New)"] + sections, key=f"chk_admin_section_{dept_for_checklist}")
    new_section = st.text_input("New Section Name", key=f"chk_admin_new_section_{dept_for_checklist}").strip() if pick_section == "(Create New)" else ""
    section_name = new_section if pick_section == "(Create New)" else pick_section

    if section_name:
        # Load existing hierarchical items
        existing_hier = _engine_call("get_hierarchical_items_for_section", dept_for_checklist, section_name) or []

        if existing_hier:
            df_data = [{"Item Text": item["item_text"], "Level": item["item_level"], "Parent Q# (for sub/subsub)": item["parent_order"] or ""} for item in existing_hier]
        else:
            df_data = [{"Item Text": "", "Level": "main", "Parent Q# (for sub/subsub)": ""}]

        st.markdown("""**Level guide:**
- `main` → numbered main question (1, 2, 3…)  
- `sub` → capital letter sub-question (A, B…) — set Parent Q# to the main question's item order  
- `subsub` → lowercase sub-sub question (a, b…) — set Parent Q# to the sub-question's item order""")

        edited_df = st.data_editor(
            pd.DataFrame(df_data),
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Level": st.column_config.SelectboxColumn("Level", options=["main", "sub", "subsub"], required=True),
                "Parent Q# (for sub/subsub)": st.column_config.NumberColumn("Parent Q# (for sub/subsub)", min_value=1, step=1),
            },
            key=f"chk_admin_editor_{dept_for_checklist}_{section_name}"
        )

        cA, cB, cC = st.columns([1.2, 1, 2])
        with cA:
            if st.button("Save Section Checklist", type="primary", key=f"chk_admin_save_{dept_for_checklist}"):
                items_to_save = []
                for _, row in edited_df.iterrows():
                    txt = str(row.get("Item Text","") or "").strip()
                    if not txt: continue
                    level = str(row.get("Level","main") or "main").strip()
                    parent_raw = row.get("Parent Q# (for sub/subsub)", "")
                    try:
                        parent_val = int(float(parent_raw)) if str(parent_raw).strip() not in ("","nan","None") else None
                    except Exception:
                        parent_val = None
                    items_to_save.append({"item_text": txt, "item_level": level, "parent_order": parent_val})
                if not items_to_save:
                    st.error("Add at least one checklist item.")
                else:
                    _engine_call("upsert_section_items_hierarchical", dept_for_checklist, section_name, items_to_save)
                    st.success(f"Saved checklist for: {dept_for_checklist} → {section_name}")
                    st.rerun()
        with cB:
            if pick_section != "(Create New)" and st.button("Delete Section", key=f"chk_admin_delete_{dept_for_checklist}_{pick_section}"):
                _engine_call("delete_section", dept_for_checklist, pick_section)
                st.success(f"Deleted section: {dept_for_checklist} → {pick_section}")
                st.rerun()
        with cC:
            st.info("Tip: Add main questions first (item order auto-assigned 1,2,3…). Then add sub-questions with Level=sub and Parent Q# pointing to the main question's row number.")

def page_auditor_checklist():
    """
    Auditor Checklist — redesigned flow
    ─────────────────────────────────────────────────────────────────────
    Step 0 : Context card  (department, audit title, admin notes)
    Step 1 : Section picker
    Step 2 : Main-question list  — only MAIN questions visible
    Step 3 : Sub-question answering — one main at a time, all sub/subsub
             nodes must be completed before returning to main list
    + "Add extra question" expander at bottom of main-question list
    """
    import pandas as _pd   # local import — avoids polluting module scope

    # ── guards ────────────────────────────────────────────────────────────────
    if not person_name:
        st.error("Auditor profile not linked."); st.stop()
    if not my_audits:
        st.info("No audits assigned yet."); st.stop()
    if not checklist_department:
        st.info("Select a department from the sidebar."); st.stop()

    dept = checklist_department.strip()
    dept_audits = [a for a in my_audits
                   if (a.get("audited_department") or "").strip().lower() == dept.lower()]
    if not dept_audits:
        st.info(f"No audits assigned for department: **{dept}**"); st.stop()

    # ── CSS ───────────────────────────────────────────────────────────────────
    st.markdown("""<style>
    /* context card */
    .ck-ctx{background:#fff;border:1px solid #e2e8f0;border-left:5px solid #4f46e5;
            border-radius:10px;padding:16px 20px;margin-bottom:20px;}
    .ck-ctx-dept{font-size:11px;font-weight:800;color:#6366f1;letter-spacing:.6px;
                 text-transform:uppercase;margin-bottom:4px;}
    .ck-ctx-title{font-size:18px;font-weight:900;color:#0f172a;margin-bottom:6px;}
    .ck-ctx-note{background:#fefce8;border:1px solid #fde68a;border-radius:7px;
                 padding:8px 12px;font-size:13px;color:#78350f;margin-top:8px;}
    .ck-ctx-note b{color:#92400e;}
    /* section tabs row */
    .ck-sec-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;}
    .ck-sec-pill{padding:7px 16px;border-radius:999px;border:1.5px solid #e2e8f0;
                 background:#fff;font-size:13px;font-weight:700;color:#475569;cursor:pointer;}
    .ck-sec-pill.active{background:#4f46e5;color:#fff;border-color:#4f46e5;}
    /* progress bar label */
    .ck-prog-label{font-size:12px;font-weight:700;color:#64748b;margin-bottom:4px;}
    /* main question card */
    .ck-main-card{background:#fff;border:1px solid #e2e8f0;border-left:4px solid #94a3b8;
                  border-radius:10px;padding:14px 16px;margin-bottom:10px;
                  display:flex;align-items:flex-start;gap:12px;}
    .ck-main-card.done{border-left-color:#22c55e;background:#f0fdf4;}
    .ck-main-card.active{border-left-color:#6366f1;background:#eef2ff;
                         box-shadow:0 0 0 2px #c7d2fe;}
    .ck-qnum{min-width:34px;height:34px;border-radius:50%;flex-shrink:0;
             display:flex;align-items:center;justify-content:center;
             font-size:12px;font-weight:800;background:#f1f5f9;color:#64748b;margin-top:2px;}
    .ck-qnum.done{background:#dcfce7;color:#15803d;}
    .ck-qnum.active{background:#e0e7ff;color:#4338ca;}
    .ck-qtext{flex:1;font-size:14px;font-weight:600;color:#1e293b;line-height:1.5;padding-top:5px;}
    /* sub-question nodes */
    .ck-node-main{background:#fff;border:1px solid #e2e8f0;border-left:4px solid #6366f1;
                  border-radius:8px;padding:12px 15px;margin-bottom:8px;
                  display:flex;align-items:flex-start;gap:10px;}
    .ck-node-sub{background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid #a5b4fc;
                 border-radius:7px;padding:10px 13px;margin:4px 0 4px 24px;
                 display:flex;align-items:flex-start;gap:10px;}
    .ck-node-subsub{background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid #ddd6fe;
                    border-radius:6px;padding:9px 12px;margin:4px 0 4px 48px;
                    display:flex;align-items:flex-start;gap:10px;}
    .ck-node-main.active,.ck-node-sub.active,.ck-node-subsub.active{
        border-left-color:#6366f1;background:#eef2ff;box-shadow:0 0 0 2px #c7d2fe;}
    .ck-node-main.done,.ck-node-sub.done,.ck-node-subsub.done{
        border-left-color:#22c55e;background:#f0fdf4;}
    .ck-badge{min-width:26px;height:26px;border-radius:50%;flex-shrink:0;
              display:flex;align-items:center;justify-content:center;
              font-size:11px;font-weight:800;background:#f1f5f9;color:#64748b;}
    .ck-badge.active{background:#e0e7ff;color:#4338ca;}
    .ck-badge.done{background:#dcfce7;color:#15803d;}
    .ck-node-lbl{font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.5px;
                 text-transform:uppercase;margin-bottom:3px;}
    .ck-node-txt{font-size:13px;font-weight:600;color:#1e293b;line-height:1.5;flex:1;}
    .ck-tick{font-size:14px;color:#16a34a;flex-shrink:0;padding-top:2px;}
    /* answer form */
    .ck-form{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
             padding:14px 16px;margin-top:8px;}
    </style>""", unsafe_allow_html=True)

    # ── audit selector ────────────────────────────────────────────────────────
    labels, label_to_id = build_audit_dropdown(dept_audits, restrict_to_auditor=False, auditor_name=None)
    audit_id = label_to_id[st.selectbox("Select Audit", options=labels, key=f"ck_sel_{dept}")]
    audit    = _engine_call("get_audit", audit_id)
    if not audit:
        st.error("Audit not found."); st.stop()

    # auto-advance status
    if audit.get("assigned_auditor") == person_name and audit.get("status") == "Assigned":
        _engine_call("set_audit_status", audit_id, "In Progress")
        audit = _engine_call("get_audit", audit_id)

    can_edit = (audit.get("assigned_auditor") == person_name
                and audit.get("status") == "In Progress")

    # ── Step 0: Context card ──────────────────────────────────────────────────
    notes = str(audit.get("plan_slot_notes") or "").strip()
    notes_html = (
        f'<div class="ck-ctx-note"><b>📋 Admin Note:</b> {notes}</div>'
        if notes else ""
    )
    st.markdown(
        f'<div class="ck-ctx">'
        f'<div class="ck-ctx-dept">🏢 Department: {dept}</div>'
        f'<div class="ck-ctx-title">{audit.get("title","Audit")}</div>'
        f'<div style="font-size:12px;color:#64748b;">Date: {audit.get("due_date","—")} &nbsp;|&nbsp; '
        f'Status: <b>{audit.get("status","—")}</b></div>'
        f'{notes_html}'
        f'</div>',
        unsafe_allow_html=True)

    if not can_edit:
        st.warning("⚠️ Read-only — audit must be In Progress and assigned to you.")

    # ── Step 1: Section picker ────────────────────────────────────────────────
    sections = _cached_sections_for_dept(_current_tenant_id(), dept)
    if not sections:
        st.info("No checklist sections found for this department."); return

    # use session state so section persists across reruns
    sec_key = f"ck_sec::{audit_id}"
    if sec_key not in st.session_state:
        st.session_state[sec_key] = sections[0]

    st.markdown("#### 📂 Section")
    sec_cols = st.columns(min(len(sections), 5))
    for i, sec in enumerate(sections):
        is_active = st.session_state[sec_key] == sec
        if sec_cols[i % len(sec_cols)].button(
                sec,
                key=f"ck_sec_btn_{audit_id}_{i}",
                type="primary" if is_active else "secondary",
                use_container_width=True):
            st.session_state[sec_key] = sec
            # clear question state when section changes
            for k in [f"ck_main::{audit_id}::{sec}", f"ck_step::{audit_id}::{sec}"]:
                st.session_state.pop(k, None)
            st.rerun()

    section = st.session_state[sec_key]
    st.markdown("---")

    # ── helpers ───────────────────────────────────────────────────────────────
    def _int(v):
        try: return int(float(str(v))) if v is not None else None
        except: return None

    def _kids(all_rows, parent_sr, level):
        p = _int(parent_sr)
        if p is None: return []
        return [r for r in all_rows
                if _int(r.get("parent_order")) == p
                and str(r.get("item_level","")).strip() == level]

    def _done(r):
        return (bool(str(r.get("observation","") or "").strip())
                and bool(str(r.get("evidence","") or "").strip()))

    def _walk(all_rows, mrow):
        """Flat ordered walk for one main: main → subA → subsub_a → subB …"""
        nodes = [mrow]
        for s in _kids(all_rows, mrow["sr_no"], "sub"):
            nodes.append(s)
            for ss in _kids(all_rows, s["sr_no"], "subsub"):
                nodes.append(ss)
        return nodes

    def _subtree_done(all_rows, mrow):
        return all(_done(n) for n in _walk(all_rows, mrow))

    def _node_label(all_rows, node, mains):
        lvl = str(node.get("item_level","")).strip()
        if lvl == "main":
            mi = next((i for i,m in enumerate(mains)
                       if str(m.get("sr_no","")) == str(node.get("sr_no",""))), 0)
            return f"Q{mi+1}"
        if lvl == "sub":
            sibs = _kids(all_rows, node.get("parent_order"), "sub")
            si = next((i for i,s in enumerate(sibs)
                       if str(s.get("sr_no","")) == str(node.get("sr_no",""))), 0)
            return chr(65 + si)         # A, B, C …
        if lvl == "subsub":
            sibs = _kids(all_rows, node.get("parent_order"), "subsub")
            ssi = next((i for i,ss in enumerate(sibs)
                        if str(ss.get("sr_no","")) == str(node.get("sr_no",""))), 0)
            return chr(97 + ssi)        # a, b, c …
        return "?"

    # ── fetch rows ────────────────────────────────────────────────────────────
    rows  = _engine_call("get_checklist_rows_for_audit_section",
                         audit_id, dept, section) or []
    mains = [r for r in rows if str(r.get("item_level","main")).strip() == "main"]
    if not mains:
        st.info("No checklist items found in this section."); return

    total_q = len(mains)
    done_q  = sum(1 for m in mains if _subtree_done(rows, m))

    # ── progress ──────────────────────────────────────────────────────────────
    st.markdown(f'<div class="ck-prog-label">Progress: {done_q} / {total_q} questions completed</div>',
                unsafe_allow_html=True)
    st.progress(done_q / total_q if total_q else 0.0)
    st.write("")

    # ── session state keys ────────────────────────────────────────────────────
    main_key = f"ck_main::{audit_id}::{section}"   # which main Q is open  (sr_no or None)
    step_key = f"ck_step::{audit_id}::{section}"   # which node is active  (sr_no)
    if main_key not in st.session_state: st.session_state[main_key] = None
    if step_key not in st.session_state: st.session_state[step_key] = None

    sel_main = st.session_state[main_key]
    sel_step = st.session_state[step_key]

    # ══════════════════════════════════════════════════════════════════════════
    # VIEW A — Main-question list  (no main selected yet)
    # ══════════════════════════════════════════════════════════════════════════
    if sel_main is None:
        st.markdown("### 📋 Questions")
        st.caption("Only the main questions are shown. Click **Start** to answer a question and its sub-questions.")
        st.write("")

        for mi, mrow in enumerate(mains):
            main_sr  = str(mrow.get("sr_no",""))
            is_done  = _subtree_done(rows, mrow)
            q_text   = str(mrow.get("checklist","")).strip() or "—"
            num_cls  = "done" if is_done else ""
            card_cls = "done" if is_done else ""
            num_lbl  = "✓"    if is_done else f"Q{mi+1}"

            # count sub-nodes
            sub_count = len(_walk(rows, mrow)) - 1  # exclude the main itself

            st.markdown(
                f'<div class="ck-main-card {card_cls}">'
                f'<div class="ck-qnum {num_cls}">{num_lbl}</div>'
                f'<div class="ck-qtext">'
                f'{q_text}'
                f'<div style="font-size:11px;color:#94a3b8;margin-top:4px;">'
                f'{"✅ All sub-questions complete" if is_done else f"{sub_count} sub-question(s)"}'
                f'</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True)

            btn_lbl = "✏️ Re-answer" if is_done else "▶ Start"
            if st.button(btn_lbl, key=f"ck_start_{audit_id}_{section}_{main_sr}",
                         type="secondary", use_container_width=False):
                walk   = _walk(rows, mrow)
                first  = next((n for n in walk if not _done(n)), walk[0])
                st.session_state[main_key] = main_sr
                st.session_state[step_key] = str(first.get("sr_no",""))
                st.rerun()
            st.write("")

        if done_q == total_q:
            st.success("✅ All questions in this section are complete!")

        # ── Add extra question ─────────────────────────────────────────────
        st.markdown("---")
        with st.expander("➕ Add Extra Question", expanded=False):
            st.caption("Add an additional question to this section that is not in the standard checklist.")
            extra_txt = st.text_area("Question text", key=f"ck_extra_txt_{audit_id}_{section}", height=80)
            if st.button("Add Question", key=f"ck_extra_add_{audit_id}_{section}",
                         type="primary", disabled=not can_edit):
                txt = str(extra_txt or "").strip()
                if not txt:
                    st.error("Please enter a question.")
                else:
                    ok, msg = _engine_call(
                        "add_audit_section_checklist_item",
                        audit_id=audit_id, dept=dept,
                        section=section, checklist_text=txt,
                        auditor_name=person_name)
                    if ok:
                        st.success("Extra question added!")
                        st.rerun()
                    else:
                        st.error(msg or "Failed to add question.")

    # ══════════════════════════════════════════════════════════════════════════
    # VIEW B — Sub-question answering for one selected main question
    # ══════════════════════════════════════════════════════════════════════════
    else:
        mrow = next((m for m in mains if str(m.get("sr_no","")) == sel_main), None)
        if mrow is None:
            st.session_state[main_key] = None; st.rerun()

        mi     = next(i for i,m in enumerate(mains) if str(m.get("sr_no","")) == sel_main)
        q_text = str(mrow.get("checklist","")).strip() or "—"
        walk   = _walk(rows, mrow)
        walk_srs = [str(n.get("sr_no","")) for n in walk]
        step_idx = walk_srs.index(sel_step) if sel_step in walk_srs else 0

        # ── back button ───────────────────────────────────────────────────────
        if st.button("← Back to questions", key=f"ck_back_{audit_id}_{section}"):
            st.session_state[main_key] = None
            st.session_state[step_key] = None
            st.rerun()

        # ── main question header card ─────────────────────────────────────────
        completed_nodes = sum(1 for n in walk if _done(n))
        total_nodes     = len(walk)
        st.markdown(
            f'<div class="ck-node-main">'
            f'<div class="ck-badge active">Q{mi+1}</div>'
            f'<div style="flex:1">'
            f'<div class="ck-node-lbl">Main Question</div>'
            f'<div class="ck-node-txt">{q_text}</div>'
            f'<div style="font-size:11px;color:#6366f1;margin-top:4px;font-weight:700;">'
            f'{completed_nodes} / {total_nodes} nodes answered</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True)

        st.progress(completed_nodes / total_nodes if total_nodes else 0.0)
        st.write("")

        # ── render each node in the walk ──────────────────────────────────────
        for ni, node in enumerate(walk):
            node_sr   = str(node.get("sr_no",""))
            node_lvl  = str(node.get("item_level","")).strip()
            node_text = str(node.get("checklist","")).strip() or "—"
            is_active = node_sr == sel_step
            is_ndone  = _done(node) and not is_active
            label     = _node_label(rows, node, mains)

            # skip future nodes — only show up to and including active
            if ni > step_idx:
                break

            # pick CSS class
            if node_lvl == "main":      base = "ck-node-main"
            elif node_lvl == "sub":     base = "ck-node-sub"
            else:                       base = "ck-node-subsub"

            state_cls = "active" if is_active else ("done" if is_ndone else "")
            badge_cls = "active" if is_active else ("done" if is_ndone else "")
            tick_html = '<div class="ck-tick">✓</div>' if is_ndone else ""

            lbl_map = {"main": f"Question {mi+1}", "sub": "Sub-question", "subsub": "Sub-sub question"}
            lbl_text = lbl_map.get(node_lvl, "")

            st.markdown(
                f'<div class="{base} {state_cls}">'
                f'<div class="ck-badge {badge_cls}">{label}</div>'
                f'<div style="flex:1">'
                f'<div class="ck-node-lbl">{lbl_text}</div>'
                f'<div class="ck-node-txt">{node_text}</div>'
                f'</div>'
                f'{tick_html}'
                f'</div>',
                unsafe_allow_html=True)

            # ── answer form — only for active node ────────────────────────────
            if is_active:
                obs_k = f"ck_obs::{audit_id}::{section}::{node_sr}"
                ev_k  = f"ck_ev::{audit_id}::{section}::{node_sr}"
                if obs_k not in st.session_state:
                    st.session_state[obs_k] = str(node.get("observation","") or "")
                if ev_k not in st.session_state:
                    st.session_state[ev_k]  = str(node.get("evidence","") or "")

                ml = {"main": 0, "sub": 24, "subsub": 48}.get(node_lvl, 0)
                st.markdown(f'<div class="ck-form" style="margin-left:{ml}px">',
                            unsafe_allow_html=True)

                col_obs, col_ev = st.columns([1, 1])
                obs = col_obs.text_area("Observation *", key=obs_k,
                                        height=90, disabled=not can_edit)
                ev  = col_ev.text_area("Evidence *",     key=ev_k,
                                        height=90, disabled=not can_edit)

                is_last = (ni == len(walk) - 1)
                btn_lbl  = "✅ Save & Finish" if is_last else "Save & Next ➜"

                b1, b2 = st.columns([1, 4])
                with b1:
                    if st.button(btn_lbl, key=f"ck_save_{audit_id}_{section}_{node_sr}",
                                 type="primary", disabled=not can_edit):
                        if not str(obs or "").strip() or not str(ev or "").strip():
                            st.error("Both Observation and Evidence are required.")
                        else:
                            ok, msg = _engine_call(
                                "save_single_checklist_response",
                                audit_id=audit_id, dept=dept, section=section,
                                sr_no=node_sr, observation=obs, evidence=ev,
                                auditor_name=person_name)
                            if not ok:
                                st.error(msg)
                            else:
                                st.session_state.pop(obs_k, None)
                                st.session_state.pop(ev_k,  None)
                                if is_last:
                                    # all nodes done → back to main list
                                    st.session_state[main_key] = None
                                    st.session_state[step_key] = None
                                else:
                                    st.session_state[step_key] = walk_srs[ni + 1]
                                st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)


def page_audit_details():
    st.title("Audit Details")
    render_status_legend()
    st.write("")

    labels, label_to_id = build_audit_dropdown(
        all_audits,
        restrict_to_auditor=(role == "auditor"),
        auditor_name=person_name,
    )

    if not labels:
        st.warning("No audits available.")
        st.stop()

    selected_label = st.selectbox("Select Audit ID", options=labels, key="audit_details_select")
    selected_id = label_to_id[selected_label]

    audit = _engine_call("get_audit", selected_id) if selected_id else None
    if not audit:
        st.warning("Select an audit.")
        st.stop()

    if role == "auditor" and audit.get("assigned_auditor") != person_name:
        st.error("Access denied. You can view only audits assigned to you.")
        st.stop()

    skill_cat = get_skill_catalog()

    st.subheader("Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", audit.get("status"))
    c2.metric("Department", audit.get("audited_department"))
    c3.metric("Auditor", audit.get("assigned_auditor"))
    c4.metric("Reports Uploaded", len(audit.get("reports", [])))

    st.write("**Title:**", audit.get("title") or "-")
    st.write("**Scope:**", audit.get("scope") or "-")

    req_keys = audit.get("required_skills", [])
    st.write("**Required Skills:**", ", ".join([skill_cat.get(k, k) for k in req_keys]) or "-")

    st.write("**Created:**", audit.get("created_at"))
    st.write("**Due:**", audit.get("due_date") or "-")
    st.write("**Report Submitted At:**", audit.get("report_submitted_at") or "-")
    st.write("**Closed At:**", audit.get("closed_at") or "-")

    st.write("")
    st.subheader("Reports")

    reports = audit.get("reports", []) or []
    if not reports:
        st.info("No reports uploaded yet.")
    else:
        for idx, r in enumerate(reports, start=1):
            file_name = r.get("file_name") or f"report_{idx}"
            uploaded_by = r.get("uploaded_by") or "-"
            uploaded_at = r.get("uploaded_at") or "-"
            saved_path = r.get("saved_path") or ""

            with st.container(border=True):
                st.write(f"**{file_name}**")
                st.write(f"Uploaded by: {uploaded_by}")
                st.write(f"Uploaded at: {uploaded_at}")

                if saved_path and os.path.exists(saved_path):
                    try:
                        with open(saved_path, "rb") as f:
                            st.download_button(
                                label="Download",
                                data=f.read(),
                                file_name=file_name,
                                mime="application/octet-stream",
                                key=f"dl_report_{audit.get('audit_id')}_{idx}",
                            )
                    except Exception:
                        st.warning("Download unavailable for this file.")
                else:
                    st.warning("File path not found on server.")

    if role == "auditor":
        st.write("")
        st.subheader("Auditor Actions")

        can_submit = (
            audit.get("assigned_auditor") == person_name
            and audit.get("status") == "In Progress"
        )

        st.markdown("#### 1) Upload Report (PDF/XLSX/XLS/CSV)")
        up = st.file_uploader(
            "Choose a file",
            type=["pdf", "xlsx", "xls", "csv"],
            key=f"ad_up_{audit.get('audit_id')}",
        )

        if st.button("Upload Report", type="primary", disabled=(not can_submit or up is None), key=f"ad_btn_up_{audit.get('audit_id')}"):
            ok, msg = _engine_call(
                "save_report_file",
                audit_id=audit["audit_id"],
                uploaded_by=person_name,
                original_filename=up.name,
                file_bytes=up.getvalue(),
            )
            if ok:
                st.success(msg)
                _clear_caches_and_rerun()
            else:
                    st.error(msg)

        st.markdown("#### 2) Submit Report (mandatory before completing)")
        checklist_ok, checklist_msg = _engine_call("validate_audit_checklists_complete", audit["audit_id"])
        if not checklist_ok:
            st.info(checklist_msg)

        submit_disabled = (not can_submit) or (not checklist_ok) or (len(audit.get("reports", []) or []) == 0)

        if st.button("Submit Report", type="primary", disabled=submit_disabled, key=f"ad_btn_submit_{audit.get('audit_id')}"):
            ok, msg = _engine_call("submit_report", audit["audit_id"], person_name)
            if ok:
                st.success(msg)
                _clear_caches_and_rerun()
            else:
                    st.error(msg)

        st.markdown("#### 3) Complete Audit (blocked without submission)")
        if st.button("Complete Audit", disabled=(not can_submit), key=f"ad_btn_complete_{audit.get('audit_id')}"):
            ok, msg = _engine_call("complete_audit", audit["audit_id"], person_name)
            if ok:
                st.success(msg)
                _clear_caches_and_rerun()
            else:
                    st.error(msg)

    if role == "admin":
        st.write("")
        st.subheader("Admin Controls")

        _status_options = ["Created", "Assigned", "In Progress", "Report Submitted", "Closed"]
        _current_status = (audit.get("status") or "Assigned")
        if _current_status not in _status_options:
            _current_status = "Assigned"
        new_status = st.selectbox(
            "Set Status",
            _status_options,
            index=_status_options.index(_current_status),
            key=f"ad_status_{audit.get('audit_id')}",
        )
        if st.button("Update Status", key=f"ad_status_btn_{audit.get('audit_id')}"):
            ok, msg = _engine_call("set_audit_status", audit["audit_id"], new_status)
            if ok:
                st.success(msg)
                _clear_caches_and_rerun()
            else:
                    st.error(msg)

def page_reports():
    st.title("Reports")
    st.caption(
        "View submitted audit files and generated final PDFs. "
        "Admin can generate and delete final PDFs; auditors can only view/download."
    )

    import os
    import engine
    import report_generator

    auth = st.session_state.get("auth", {})
    tenant_id = auth.get("tenant_id")
    username = auth.get("username")
    role = auth.get("role")

    if not tenant_id:
        st.error("Tenant not found in session. Please log in again.")
        st.stop()

    def _download_abs_path_button(label: str, abs_path: str, key: str):
        try:
            with open(abs_path, "rb") as f:
                st.download_button(
                    label=label,
                    data=f.read(),
                    file_name=os.path.basename(abs_path),
                    mime="application/pdf",
                    key=key,
                )
        except Exception as e:
            st.warning(f"Download unavailable: {e}")

    if role == "admin":
        st.subheader("Generate Final Audit Report")

        status_filter = st.selectbox(
            "Select audit status",
            options=["Report Submitted", "Closed"],
            index=0,
        )

        all_audits = engine.list_audits(tenant_id=tenant_id)
        eligible_audits = [
            a for a in all_audits if a.get("status") == status_filter
        ]

        if not eligible_audits:
            st.info(f"No audits with status '{status_filter}'.")
        else:
            labels, label_to_id = engine.get_audit_dropdown_options(tenant_id=tenant_id)

            selected_labels = st.multiselect(
                "Select audits to include",
                options=[
                    lbl for lbl in labels
                    if label_to_id[lbl] in {a["audit_id"] for a in eligible_audits}
                ],
            )

            selected_ids = [label_to_id[lbl] for lbl in selected_labels]

            admin_summaries_by_audit_id = {}

            # Build a lookup: audit_id -> audit object for display
            _eligible_map = {a["audit_id"]: a for a in eligible_audits}

            for aid in selected_ids:
                _a       = _eligible_map.get(aid, {})
                _title   = _a.get("title") or "Untitled Audit"
                _auditor = _a.get("assigned_auditor") or "Unassigned"
                _dept    = _a.get("audited_department") or ""
                _dept_str = f" &nbsp;·&nbsp; {_dept}" if _dept else ""
                st.markdown(
                    f'<div style="margin:18px 0 6px;">'
                    f'<span style="font-size:15px;font-weight:700;color:#0f172a;">{_title}</span>'
                    f'<span style="font-size:12px;color:#64748b;margin-left:10px;">'
                    f'&#128100; {_auditor}{_dept_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                admin_summaries_by_audit_id[aid] = st.text_area(
                    label="",
                    placeholder='Enter summary for this audit...',
                    key=f"summary_{aid}",
                    height=120,
                )

            output_name = st.text_input(
                "Optional PDF filename (leave blank for auto-name)",
                placeholder="Final_Audit_Report_Q1_2026.pdf",
            )

            if st.button("Generate Final Report", type="primary"):
                with st.spinner("Generating PDF..."):
                    if not _HAS_REPORT_GEN:
                        st.error("PDF generation is unavailable because the report generator dependencies are missing (reportlab). Install reportlab in requirements.txt to enable PDF generation.")
                        ok, msg, pdf_path = False, "report_generator unavailable", None
                    else:
                        ok, msg, pdf_path = report_generator.generate_final_audit_report_pdf(
                        tenant_id=tenant_id,
                        generated_by=username,
                        selected_audit_ids=selected_ids,
                        admin_summaries_by_audit_id=admin_summaries_by_audit_id,
                        output_filename=output_name or None,
                    )

                if ok:
                    st.success(msg)
                    _rerun()
                else:
                    st.error(msg)

        st.divider()

    st.subheader("Generated Final Reports")

    reports = engine.list_final_generated_reports_for_user(
        username=username,
        role=role,
        tenant_id=tenant_id,
    )

    if not reports:
        st.info("No generated final reports available.")
    else:
        for r in reports:
            st.markdown(f"### Generated on {r['created_at']}")
            st.write("Created by:", r["created_by"])
            st.write("Summary:", r["summary"])

            abs_path = engine.resolve_final_report_pdf_abs_path(
                tenant_id, r["pdf_rel_path"]
            )

            if not os.path.exists(abs_path):
                st.error("PDF file missing on server.")
            else:
                _download_abs_path_button(
                    label="Download PDF",
                    abs_path=abs_path,
                    key=f"download_{r['id']}",
                )

            if role == "admin":
                if st.button(
                    "Delete Report",
                    key=f"delete_{r['id']}",
                ):
                    ok, msg = engine.delete_final_generated_report(
                        report_id=r["id"],
                        requester_role=role,
                        tenant_id=tenant_id,
                    )
                    if ok:
                        st.success(msg)
                        _rerun()
                    else:
                        st.error(msg)

            st.divider()

def page_auditor_my_audits():
    st.title("My Audits")
    render_panel("Assigned Audits", "Only audits assigned to your account are visible here.")
    st.write("")

    q = st.text_input("Search my audits", placeholder="Search by title, department, status, ID")
    render_status_legend()
    st.write("")
    audits_table(my_audits, search_query=q)

    st.info("Rule: Upload at least one report, submit it, then you can complete the audit.")

def page_auditor_my_timetable():
    import pandas as pd

    st.title("My Timetable")
    render_panel("Timetable View", "Slots assigned by Admin are displayed for the selected date range.")
    st.write("")

    start_date = st.date_input("From", value=date.today(), key="mytt_from")
    days = st.number_input("Number of days", min_value=1, max_value=60, value=7, step=1, key="mytt_days")

    schedule = _cached_timetable_schedule()
    days_map = schedule.get("days", {})

    rows = []
    for i in range(int(days)):
        d = (start_date + timedelta(days=i)).isoformat()
        day_slots = days_map.get(d, {})

        for slot, audits in day_slots.items():
            for a in audits:
                if a.get("auditor") == person_name:
                    rows.append({
                        "Date": d,
                        "Time Slot": slot,
                        "Department to Audit": a.get("department", ""),
                        "Auditor": a.get("auditor", ""),
                    })

    if not rows:
        st.info("No timetable slots assigned to you in this period.")
    else:
        df = pd.DataFrame(rows, columns=["Date", "Time Slot", "Department to Audit", "Auditor"])
        df = df.sort_values(by=["Date", "Time Slot"])
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("### Today’s schedule")
        today = date.today().isoformat()
        today_rows = [r for r in rows if r["Date"] == today]
        if not today_rows:
            st.write("No slots for today.")
        else:
            tdf = pd.DataFrame(today_rows, columns=["Date", "Time Slot", "Department to Audit", "Auditor"])
            tdf = tdf.sort_values(by=["Time Slot"])
            st.table(tdf[["Time Slot", "Department to Audit"]])

checklist_department: Optional[str] = None

role = (st.session_state.get("auth") or {}).get("role", "auditor")

with st.sidebar:
    _page_icons = {
        "Dashboard":         "&#9783;",
        "Audit Calender":    "&#128197;",
        "Audit Plan":        "&#128196;",
        "Auditors & Skills": "&#128100;",
        "Checklist":         "&#9989;",
        "Audit Details":     "&#128269;",
        "Reports":           "&#128202;",
        "My Audits":         "&#128203;",
    }
    if role == "admin":
        st.markdown('<div class="sb-nav-label">Main Menu</div>', unsafe_allow_html=True)
        _admin_pages = [
            "Dashboard",
            "Audit Calender",
            "Audit Plan",
            "Auditors & Skills",
            "Checklist",
            "Audit Details",
            "Reports",
        ]
        _nav_default = 0
        if st.session_state.get("_nav_to") in _admin_pages:
            _nav_default = _admin_pages.index(st.session_state.pop("_nav_to"))
        _admin_labels = [f'{_page_icons.get(p,"")}   {p}' for p in _admin_pages]
        _sel = st.radio("", _admin_labels, index=_nav_default, label_visibility="collapsed")
        page = _admin_pages[_admin_labels.index(_sel)]
    else:
        st.markdown('<div class="sb-nav-label">Main Menu</div>', unsafe_allow_html=True)
        _aud_pages = ["Dashboard","My Audits","Checklist","Audit Details","Reports"]
        _aud_labels = [f'{_page_icons.get(p,"")}   {p}' for p in _aud_pages]
        _sel = st.radio("", _aud_labels, label_visibility="collapsed")
        page = _aud_pages[_aud_labels.index(_sel)]

render_breadcrumb(role, page)

if role == "admin":
    if page == "Dashboard":
        page_admin_dashboard()
    elif page == "Audit Calender":
        page_audit_calendar()
    elif page == "Audit Plan":
        page_audit_plan()
    elif page == "Auditors & Skills":
        page_admin_auditors_skills()
    elif page == "Checklist":
        tenant_id = (st.session_state.get("auth") or {}).get("tenant_id")
        depts = _cached_departments_catalog(tenant_id) or []
        depts = [d for d in depts if str(d).strip()]
        depts = sorted(set(depts), key=lambda x: str(x).lower())

        add_key = "➕ Add new department"
        options = depts + ([add_key] if add_key not in depts else [])

        if not options:
            st.info("No departments found.")
        else:
            choice = st.selectbox("Department", options=options, key="chk_dept_select")
            if choice == add_key:
                new_dept = st.text_input("New Department Name", key="chk_new_dept_name").strip()
                if st.button("Add Department", type="primary", key="chk_add_dept_btn"):
                    if not new_dept:
                        st.error("Please enter a department name.")
                    else:
                        _engine_call("add_department_to_catalog", new_dept, tenant_id=tenant_id)
                        st.success(f"Added department: {new_dept}")
                        _clear_caches_and_rerun()
                st.stop()

            checklist_department = choice
            globals()["checklist_department"] = checklist_department
            page_admin_checklist()
    elif page == "Audit Details":
        page_audit_details()
    elif page == "Reports":
        page_reports()

else:
    if page == "Dashboard":
        render_panel("Auditor Dashboard", "Your assigned audits and actions.")
        st.metric("Assigned Audits", len(my_audits))

        st.markdown("---")

        st.markdown(
            """
            <style>.aog-card{background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;padding:16px 16px 12px 16px;box-shadow:0 6px 18px rgba(15,23,42,0.06);margin-top:10px}.aog-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}.aog-title{font-size:15px;font-weight:800;color:#0f172a;margin:0;letter-spacing:0.2px}.aog-sub{font-size:12.5px;color:#64748b;margin:4px 0 0 0;line-height:1.4}.aog-tag{font-size:12px;font-weight:700;color:#0f172a;background:#f8fafc;border:1px solid #e5e7eb;border-radius:999px;padding:6px 10px;white-space:nowrap}.aog-list{margin:0;padding-left:18px;color:#0f172a}.aog-list li{margin:8px 0;font-size:13px;line-height:1.45;color:#334155}.aog-list b{color:#0f172a}.aog-foot{margin-top:12px;padding-top:10px;border-top:1px dashed #e5e7eb;display:flex;gap:8px;flex-wrap:wrap;align-items:center;color:#64748b;font-size:12.3px;line-height:1.4}.aog-pill{display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#f8fafc;color:#0f172a;font-size:11.5px;font-weight:700}</style>

            <div class="aog-card">
              <div class="aog-head">
                <div>
                  <div class="aog-title">Auditor Operating Guide</div>
                  <div class="aog-sub">Follow this sequence to complete an audit with accurate records and clean closure.</div>
                </div>
                <div class="aog-tag">Quick Guide</div>
              </div>

              <ol class="aog-list">
                <li><b>Verify session:</b> Confirm the correct <b>Tenant</b>, <b>Username</b>, and <b>Role (Auditor)</b>.</li>
                <li><b>Review assigned audit:</b> Open <b>My Audits</b> and verify department, scope, and due date.</li>
                <li><b>Start audit:</b> Set status to <b>In Progress</b> before entering checklist data.</li>
                <li><b>Complete checklist:</b> Record clear <b>Observations</b> and attach/reference <b>Evidence</b> for each item.</li>
                <li><b>Validate details:</b> Review entries in <b>Audit Details</b> for completeness before submission.</li>
                <li><b>Submit report:</b> Upload the finalized report in <b>Reports</b> and submit as per workflow.</li>
                <li><b>Logout:</b> Sign out after completion, especially on shared systems.</li>
              </ol>

              <div class="aog-foot">
                Navigation:
                <span class="aog-pill">My Audits</span>
                <span class="aog-pill">Checklist</span>
                <span class="aog-pill">Audit Details</span>
                <span class="aog-pill">Reports</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif page == "My Audits":
        page_auditor_my_audits()
    elif page == "Checklist":
        my_depts = sorted(
            {
                (a.get("audited_department") or "").strip()
                for a in my_audits
                if (a.get("audited_department") or "").strip()

            },
            key=lambda x: x.lower(),
        )
        if not my_depts:
            st.info("No departments available.")
        else:
            checklist_department = st.selectbox("Department", options=my_depts)
            globals()["checklist_department"] = checklist_department
            page_auditor_checklist()
    elif page == "Audit Details":
        page_audit_details()
    elif page == "Reports":
        page_reports()
