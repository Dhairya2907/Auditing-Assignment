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
    st.markdown(
        """<style>.stApp{background:#f4f6f9;color:#0f172a}.block-container{max-width:1200px;padding-top:1.75rem;padding-bottom:2.5rem}section[data-testid="stSidebar"]{background:#ffffff;border-right:1px solid #e5e7eb}section[data-testid="stSidebar"] *{color:#0f172a}h1{font-size:44px;font-weight:800;letter-spacing:-0.4px;margin-bottom:0.5rem}h2{font-size:26px;font-weight:700;margin-top:1.2rem}h3{font-size:18px;font-weight:600}p,span,li{color:#334155;font-size:15px;line-height:1.55}.stMarkdown h4{font-size:16px;font-weight:600;color:#0f172a}.stButton button{background:#ffffff !important;color:#0f172a !important;border:1px solid #d1d5db !important;border-radius:10px !important;font-weight:600 !important;padding:0.6rem 1.1rem !important}.stButton button:hover{background:#f8fafc !important;border-color:#94a3b8 !important}input,textarea,select{background:#ffffff !important;border:1px solid #d1d5db !important;border-radius:10px !important;color:#0f172a !important}div[role="radiogroup"] label{font-size:15px;font-weight:500;padding:6px 2px}span[data-testid="stBadge"]{border-radius:999px !important;font-weight:600;padding:4px 10px}div[data-testid="stDataFrame"]{background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden}footer{visibility:hidden}.block-container{max-width:1200px;padding-top:1.4rem;padding-bottom:2.2rem}h1{margin-top:0.2rem;margin-bottom:0.6rem}h2{margin-top:1.0rem;margin-bottom:0.4rem}h3{margin-top:0.7rem;margin-bottom:0.3rem}.breadcrumb{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:#64748b;font-weight:600;margin:6px 0 10px 0}.breadcrumb .sep{color:#94a3b8}.breadcrumb .current{color:#0f172a;font-weight:700}.status-legend{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.cal-year{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}@media (max-width:1100px){.cal-year{grid-template-columns:repeat(2,minmax(0,1fr))}}@media (max-width:750px){.cal-year{grid-template-columns:repeat(1,minmax(0,1fr))}}.cal-month{background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:12px 12px 10px 12px;box-shadow:0 10px 24px rgba(15,23,42,0.06)}.cal-month-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:10px}.cal-month-name{font-weight:900;font-size:16px;color:#0f172a}.cal-month-meta{font-size:12px;color:#64748b;font-weight:700}.cal-weekdays{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:6px}.cal-weekday{font-size:11px;color:#64748b;font-weight:800;text-transform:uppercase;letter-spacing:0.6px;text-align:center}.cal-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px}.cal-cell{border:1px solid #eef2f7;border-radius:12px;min-height:74px;padding:6px 6px 8px 6px;background:#fbfdff;position:relative;overflow:hidden}.cal-cell.muted{background:#f8fafc;color:#94a3b8}.cal-cell:hover{border-color:#cbd5e1;box-shadow:0 8px 16px rgba(15,23,42,0.06)}.cal-daynum{font-size:12px;font-weight:900;color:#0f172a}.cal-cell.muted .cal-daynum{color:#94a3b8}.cal-pills{margin-top:6px;display:flex;flex-direction:column;gap:4px}.cal-pill{border-radius:999px;border:1px solid #bfdbfe;background:#eff6ff;color:#1e3a8a;padding:2px 8px;font-size:11px;font-weight:800;line-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cal-pill.alt{border-color:#a7f3d0;background:#ecfdf5;color:#065f46}.cal-pill.warn{border-color:#fed7aa;background:#fff7ed;color:#9a3412}.cal-more{font-size:11px;font-weight:800;color:#475569;padding-left:4px}</style>""",
        unsafe_allow_html=True,
    )

def inject_theme_overrides():
    if (st.session_state.get("ui_theme") or "light").lower().strip() != "dark":
        return
    st.markdown(
        """<style>.stApp{background:#0b1220 !important;color:#e5e7eb !important}.block-container{background:transparent !important}section[data-testid="stSidebar"]{background:#0f172a !important;border-right:1px solid #223047 !important}section[data-testid="stSidebar"] *{color:#e5e7eb !important}h1,h2,h3,h4,h5,h6{color:#f1f5f9 !important}p,span,li{color:#cbd5e1 !important}.panel,.card,.hero,.kpi,.pill,.breadcrumb{background:#0f172a !important;border:1px solid #223047 !important}.panel-title,.title{color:#f1f5f9 !important}.panel-subtitle,.sub,.subtle{color:#94a3b8 !important}.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]>div,.stMultiSelect div[data-baseweb="select"]>div,.stDateInput input{background:#0b1220 !important;color:#e5e7eb !important;border:1px solid #223047 !important}.stButton button,button[kind="primary"]{background:#111c33 !important;color:#e5e7eb !important;border:1px solid #223047 !important}.stButton button:hover{border-color:#3b82f6 !important}[data-testid="stDataFrame"],.stDataFrame,.stTable{background:#0f172a !important;border:1px solid #223047 !important}</style>""",
        unsafe_allow_html=True,
    )

# ── UI components ─────────────────────────────────────────────────────────────
def render_topbar(username: str, role: str):
    left, right = st.columns([10, 1], vertical_alignment="center")
    with left:
        st.markdown(
            f"""<div class="hero"><div class="left"><div class="title">Audit Assignment System</div>
            <div class="sub">Controlled scheduling, skill matching, checklists, reports, and closure control</div>
            </div><div class="pill"><span class="dot"></span>{role.upper()} • {username}</div></div>""",
            unsafe_allow_html=True,
        )
    with right:
        theme = (st.session_state.get("ui_theme") or "light").lower().strip()
        if st.button("🌙" if theme == "light" else "☀️", key="btn_toggle_theme", help="Toggle light/dark mode"):
            st.session_state["ui_theme"] = "dark" if theme == "light" else "light"
            st.rerun()

def render_breadcrumb(role: str, page_name: str):
    role_label = "Admin" if (role or "").strip().lower() == "admin" else "Auditor"
    st.markdown(
        f"""<div class="breadcrumb"><span>{role_label}</span><span class="sep">→</span><span class="current">{page_name}</span></div>""",
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

@st.cache_data(show_spinner=False, ttl=60)
def _cached_departments_catalog(tenant_id):
    return _engine_call("load_departments_catalog", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_skills_catalog(tenant_id):
    return _engine_call("load_skills_catalog", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=60)
def _cached_people(tenant_id):
    return _engine_call("list_people_records", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_state(tenant_id):
    return _engine_call("load_state", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=60)
def _cached_sections_for_dept(tenant_id, dept: str):
    return _engine_call("get_sections_for_department", dept, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_items_for_section(tenant_id, dept: str, section: str):
    return _engine_call("get_items_for_department_section", dept, section, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_timetable_schedule():
    return (timetable.load_schedule() if _HAS_TIMETABLE and timetable else {}) or {"days": {}}

def _clear_caches_and_rerun():
    st.cache_data.clear()
    _rerun()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def logout():
    st.session_state.auth = {"logged_in": False, "tenant_code": "default", "tenant_id": None, "username": None, "role": None, "person_name": None}
    st.rerun()

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
    render_topbar(username="Not signed in", role="Access")
    render_panel("Secure Login", "RBAC enabled. Admin has full access; Auditor sees assigned audits only; report submission required before closure.")
    st.write("")
    with st.form("login_form"):
        tenant_code = st.text_input("Tenant Code (Company)", value=st.session_state.auth.get("tenant_code") or "default", placeholder="e.g., acme, beta, default")
        username = st.text_input("Username", placeholder="admin or auditor username")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        submitted = st.form_submit_button("Login")
    if submitted:
        tenant_code = (tenant_code or "").strip().lower()
        username = (username or "").strip().lower()
        if hasattr(engine, "authenticate_tenant"):
            ok, u, msg = engine.authenticate_tenant(tenant_code, username, password)
        else:
            ok, u, msg = engine.authenticate(username, password)
        if not ok:
            st.error(msg)
        else:
            st.session_state.auth = {"logged_in": True, "tenant_code": tenant_code, "tenant_id": u.get("tenant_id"), "username": u["username"], "role": u["role"], "person_name": u.get("person_name")}
            st.success("Logged in.")
            st.rerun()
    st.write("")
    render_panel("Default seed credentials", "Use these only for initial testing.")
    st.write("- Admin: **admin / admin123**")
    st.write("- Auditor: username is lowercase name (no spaces), password: **auditor123**")
    st.stop()

import calendar as _calendar
import pandas as _pd

# ── Audit Calendar page ───────────────────────────────────────────────────────
def page_audit_calendar():
    st.title("Audit Calendar")
    st.caption("Create audits and view them in a clean monthly calendar.")
    tenant_id = st.session_state.auth.get("tenant_id")
    username = st.session_state.auth.get("username", "")

    st.markdown("""<style>.cal-wrap{background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;padding:14px 14px 10px 14px;box-shadow:0 10px 24px rgba(15,23,42,0.06)}.cal-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 6px 12px 6px}.cal-title{font-weight:900;color:#0f172a;font-size:16px;letter-spacing:0.2px}.cal-sub{color:#64748b;font-size:12px;margin-top:2px}.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;padding:8px 6px 8px 6px}.cal-dow{color:#64748b;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;padding:6px 10px;border-radius:12px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center}.cal-cell{border:1px solid #e5e7eb;border-radius:16px;padding:10px;min-height:92px;background:#ffffff;box-shadow:0 6px 14px rgba(15,23,42,0.04)}.cal-cell.muted{background:#fbfdff;border-style:dashed;opacity:0.7}.cal-day{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}.cal-num{font-weight:900;color:#0f172a;font-size:13px}.cal-badge{font-size:11px;font-weight:800;padding:4px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#f8fafc;color:#334155}.cal-chip{display:block;padding:6px 8px;border-radius:12px;margin-top:6px;font-size:12px;font-weight:750;line-height:1.15;border:1px solid #e2e8f0;background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%);color:#0f172a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cal-chip small{display:block;font-weight:700;color:#64748b;margin-top:2px}.cal-chip.planned{border-color:#bfdbfe;background:linear-gradient(180deg,#eff6ff 0%,#ffffff 100%)}.cal-chip.progress{border-color:#fde68a;background:linear-gradient(180deg,#fffbeb 0%,#ffffff 100%)}.cal-chip.closed{border-color:#bbf7d0;background:linear-gradient(180deg,#ecfdf5 0%,#ffffff 100%)}.cal-chip.other{border-color:#e5e7eb}.cal-more{color:#64748b;font-size:12px;margin-top:8px;font-weight:700}.cal-legend{display:flex;gap:8px;flex-wrap:wrap;padding:0 6px 10px 6px}.cal-dot{width:10px;height:10px;border-radius:999px;display:inline-block;margin-right:6px}.cal-pill{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;border:1px solid #e5e7eb;background:#ffffff;color:#334155;font-size:12px;font-weight:750}</style>""", unsafe_allow_html=True)

    with st.expander("Create a calendar audit", expanded=False):
        with st.form("create_calendar_audit_form"):
            c1, c2, c3 = st.columns([1, 1, 2])
            start = c1.date_input("Start date *", value=None, key="cal_start")
            end = c2.date_input("End date *", value=None, key="cal_end")
            title = c3.text_input("Audit title *", key="cal_title")
            scope = st.text_area("Scope *", height=90, key="cal_scope")
            if st.form_submit_button("Create audit", use_container_width=True):
                if start is None or end is None:
                    st.error("Start date and end date are required.")
                elif not str(title).strip():
                    st.error("Audit title is required.")
                elif not str(scope).strip():
                    st.error("Scope is required.")
                elif end < start:
                    st.error("End date cannot be before start date.")
                else:
                    audit, msg = _engine_call("create_audit_calendar", title=str(title).strip(), scope=str(scope).strip(), start_date=start.isoformat(), end_date=end.isoformat(), created_by=username)
                    if audit:
                        st.success(msg); _rerun()
                    else:
                        st.error(msg)

    today = date.today()
    f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
    year = f1.selectbox("Year", list(range(today.year - 2, today.year + 6)), index=2, key="cal_year")
    month = f2.selectbox("Month", list(range(1, 13)), index=today.month - 1, format_func=lambda m: _calendar.month_name[m], key="cal_month")
    view = f3.selectbox("View", ["Calendar", "List"], index=0, key="cal_view")
    q = f4.text_input("Search", placeholder="Type to filter by title, scope, or owner", key="cal_search")

    cal = _cached_list_audit_calendar(tenant_id) or []

    def _safe_date(s, default="1900-01-01"):
        try:
            return date.fromisoformat(str(s or default))
        except Exception:
            return date.fromisoformat(default)

    def _status_bucket(a):
        s = str(a.get("status", "")).strip().lower()
        if s in ("planned", "open", "assigned", "scheduled"):
            return "planned"
        if s in ("in progress", "in-progress", "progress", "ongoing", "active"):
            return "progress"
        if s in ("closed", "done", "complete", "completed"):
            return "closed"
        return "other"

    def _matches(a):
        if not q:
            return True
        blob = " ".join(str(a.get(k, "")) for k in ["title", "scope", "created_by", "auditor", "owner"]).lower()
        return q.lower() in blob

    month_start = date(year, month, 1)
    month_end = date(year, month, _calendar.monthrange(year, month)[1])
    items = []
    for a in cal:
        sd, ed = _safe_date(a.get("start_date")), _safe_date(a.get("end_date"))
        if ed < sd:
            sd, ed = ed, sd
        if ed < month_start or sd > month_end or not _matches(a):
            continue
        items.append({**a, "_sd": sd, "_ed": ed, "_bucket": _status_bucket(a)})

    st.markdown("""<div class="cal-legend"><span class="cal-pill"><span class="cal-dot" style="background:#93c5fd"></span>Planned</span><span class="cal-pill"><span class="cal-dot" style="background:#fbbf24"></span>In progress</span><span class="cal-pill"><span class="cal-dot" style="background:#34d399"></span>Closed</span><span class="cal-pill"><span class="cal-dot" style="background:#cbd5e1"></span>Other</span></div>""", unsafe_allow_html=True)

    if view == "List":
        if not items:
            st.info("No audits found for this month.")
            return
        for a in sorted(items, key=lambda x: (x["_sd"], x.get("title", ""))):
            sd, ed = a["_sd"], a["_ed"]
            title = str(a.get("title", "Untitled")).strip() or "Untitled"
            scope = str(a.get("scope", "")).strip()
            owner = str(a.get("created_by", "")).strip() or str(a.get("auditor", "")).strip()
            st.markdown(
                f"""<div class="cal-wrap" style="margin-bottom:10px;"><div class="cal-head"><div><div class="cal-title">{title}</div><div class="cal-sub">{sd.strftime('%d %b %Y')} → {ed.strftime('%d %b %Y')} • Owner: {owner or '—'}</div></div><div class="cal-badge">{str(a.get('status','Planned')).strip() or 'Planned'}</div></div><div style="padding:0 6px 6px 6px; color:#334155; font-size:13px;">{scope if scope else "<span style='color:#94a3b8;'>No scope provided.</span>"}</div></div>""",
                unsafe_allow_html=True,
            )
        return

    _, days_in_month = _calendar.monthrange(year, month)
    offset = date(year, month, 1).weekday()
    rows = (offset + days_in_month + 6) // 7

    by_day: dict = {}
    for a in items:
        d = max(a["_sd"], month_start)
        last = min(a["_ed"], date(year, month, days_in_month))
        while d <= last:
            by_day.setdefault(d, []).append(a)
            d += timedelta(days=1)

    dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    st.markdown(f"<div class='cal-wrap'>", unsafe_allow_html=True)
    st.markdown(f"""<div class="cal-head"><div><div class="cal-title">{_calendar.month_name[month]} {year}</div><div class="cal-sub">Showing {len(items)} audit(s) in this month</div></div><div class="cal-badge">{tenant_id or "Tenant"}</div></div>""", unsafe_allow_html=True)
    st.markdown("<div class='cal-grid'>" + "".join(f"<div class='cal-dow'>{d}</div>" for d in dow) + "</div>", unsafe_allow_html=True)

    cells_html = ["<div class='cal-grid'>"]
    day_num = 1
    for r in range(rows):
        for c in range(7):
            ci = r * 7 + c
            if ci < offset or day_num > days_in_month:
                cells_html.append("<div class='cal-cell muted'></div>")
                continue
            d = date(year, month, day_num); day_num += 1
            badge = "<span class='cal-badge'>Today</span>" if d == today else ""
            audits_day = sorted(by_day.get(d, []), key=lambda x: (x["_sd"], str(x.get("title", ""))))
            max_show = 3
            chips = []
            for a in audits_day[:max_show]:
                t = (str(a.get("title", "Untitled")).strip() or "Untitled")
                sd, ed = a["_sd"], a["_ed"]
                tag = "Single day" if sd == ed else (f"Starts • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}" if d == sd else (f"Ends • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}" if d == ed else f"Ongoing • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}"))
                scope = str(a.get("scope", "")).strip()
                tooltip = (t + (" | " + scope if scope else "")).replace('"', "&quot;")
                chips.append(f"<span class='cal-chip {a['_bucket']}' title=\"{tooltip}\">{t}<small>{tag}</small></span>")
            more = f"<div class='cal-more'>+{len(audits_day) - max_show} more</div>" if len(audits_day) > max_show else ""
            cells_html.append(f"<div class='cal-cell'><div class='cal-day'><span class='cal-num'>{d.day}</span>{badge}</div>{''.join(chips)}{more}</div>")
    cells_html.append("</div>")
    st.markdown("".join(cells_html), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ── Audit Plan page ───────────────────────────────────────────────────────────
def page_audit_plan():
    st.title("Audit Plan")
    st.caption("Select an audit from Audit Calender, then create a working-days schedule with 1-hour slots.")
    tenant_id = st.session_state.auth.get("tenant_id")
    username = st.session_state.auth.get("username", "")

    cal = _cached_list_audit_calendar(tenant_id) or []
    if not cal:
        st.info("No audits found in Audit Calender. Create an audit first.")
        return

    by_label = {f"{a.get('title','')} ({a.get('start_date','')} -> {a.get('end_date','')})": a for a in cal}
    sel_label = st.selectbox("Select Audit", options=list(by_label.keys()))
    audit = by_label[sel_label]
    calendar_audit_id = audit.get("id")

    st.markdown(
        "<div style='padding:12px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;'>"
        + f"<div style='font-weight:800;color:#0f172a;'>{audit.get('title','')}</div>"
        + f"<div style='color:#475569;font-size:13px;'>{audit.get('start_date','')} -> {audit.get('end_date','')}</div>"
        + f"<div style='color:#0f172a;margin-top:6px;'><b>Scope:</b> {audit.get('scope','')}</div></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    plan = _engine_call("get_audit_plan_by_calendar_audit", calendar_audit_id=calendar_audit_id)
    with st.form("plan_create_form"):
        days_default = int(plan["working_days"]) if plan and plan.get("working_days") else 1
        days = st.number_input("How many working days will the audit run? *", min_value=1, step=1, value=days_default)
        if st.form_submit_button("Create / Reset Plan"):
            p, msg = _engine_call("create_or_reset_audit_plan", calendar_audit_id=calendar_audit_id, working_days=int(days), created_by=username)
            if p:
                st.success(msg); _rerun()
            else:
                st.error(msg)

    plan = _engine_call("get_audit_plan_by_calendar_audit", calendar_audit_id=calendar_audit_id)
    if not plan:
        st.info("Create the audit plan to start scheduling.")
        return
    slots = plan.get("slots", []) or []
    if not slots:
        st.warning("No plan slots found; reset the plan once.")
        return

    dept_list = _engine_call("list_departments_simple", tenant_id) or []
    dept_options = [""] + [d for d in dept_list if d]
    people = _cached_people(tenant_id) or []
    state = _cached_state(tenant_id) or {}
    schedule = (timetable.load_schedule() if _HAS_TIMETABLE and timetable else {}) or {"days": {}}

    def _norm(s):
        return " ".join(str(s or "").strip().split()).lower()

    def eligible_auditors_for(department: str, date_str: str, slot_str: str) -> List[str]:
        dep = (department or "").strip()
        if not dep:
            return []
        required = set(_engine_call("get_required_skills_for_dept", dep, tenant_id=tenant_id) or set())
        eligible = []
        for p in people:
            p_name, p_dept, p_skills = getattr(p, "name", ""), getattr(p, "department", ""), set(getattr(p, "skills", set()) or set())
            if _norm(p_dept) and _norm(p_dept) == _norm(dep):
                continue
            if required and not required.issubset(p_skills):
                continue
            if engine.is_busy(state, p_name):
                continue
            if _HAS_TIMETABLE and timetable and timetable.auditor_is_busy(schedule, date_str, slot_str, p_name):
                continue
            eligible.append(p_name)
        return sorted(set(x for x in eligible if x))

    st.subheader("Plan schedule")
    st.caption("Auditor dropdown follows rules: not same department, required skills match, not busy, no slot clash.")

    ss_key = f"plan_edits_{plan.get('plan_id')}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = {s.get("id"): {"department": s.get("department") or "", "auditor_name": s.get("auditor_name") or "", "notes": s.get("notes") or ""} for s in slots}
    edits = st.session_state[ss_key]

    for d in sorted({s.get("plan_date") for s in slots if s.get("plan_date")}):
        st.markdown(f"### {d}")
        for s in [s for s in slots if s.get("plan_date") == d]:
            sid = s.get("id")
            slot_str = f"{s.get('slot_start')}-{s.get('slot_end')}"
            row = edits.get(sid, {"department": "", "auditor_name": "", "notes": ""})
            c1, c2, c3, c4 = st.columns([2.2, 2.2, 2.2, 3.4])
            c1.text_input("Slot", value=slot_str, key=f"slot_lbl_{sid}", disabled=True)
            dept_val = c2.selectbox("Department", options=dept_options, index=dept_options.index(row.get("department", "")) if row.get("department", "") in dept_options else 0, key=f"slot_dept_{sid}")
            auditor_options = [""] + eligible_auditors_for(dept_val, d, slot_str)
            aud_val = c3.selectbox("Auditor", options=auditor_options, index=auditor_options.index(row.get("auditor_name", "")) if row.get("auditor_name", "") in auditor_options else 0, key=f"slot_aud_{sid}")
            notes_val = c4.text_input("Notes", value=row.get("notes", ""), key=f"slot_notes_{sid}")
            edits[sid] = {"department": dept_val or "", "auditor_name": aud_val or "", "notes": notes_val or ""}
        st.divider()

    c1, c2 = st.columns(2)
    if c1.button("Auto-assign missing auditors"):
        ok, msg = _engine_call("auto_assign_auditors", tenant_id, plan["plan_id"])
        if ok:
            st.success(msg)
            plan = _engine_call("get_audit_plan_by_calendar_audit", calendar_audit_id=calendar_audit_id)
            slots = plan.get("slots", []) or []
            st.session_state[ss_key] = {s.get("id"): {"department": s.get("department") or "", "auditor_name": s.get("auditor_name") or "", "notes": s.get("notes") or ""} for s in slots}
            _rerun()
        else:
            st.error(msg)

    if c2.button("Save Audit Plan"):
        payload = [{"plan_date": s.get("plan_date"), "slot_start": s.get("slot_start"), "slot_end": s.get("slot_end"), "department": edits.get(s.get("id"), {}).get("department", "") or "", "auditor_name": edits.get(s.get("id"), {}).get("auditor_name", "") or "", "notes": edits.get(s.get("id"), {}).get("notes", "") or ""} for s in slots]
        ok, msg = _engine_call("update_audit_plan_slots", tenant_id, plan["plan_id"], payload)
        if ok:
            st.success(msg)
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
    st.markdown("""<div style="padding:12px 12px;border:1px solid #e5e7eb;border-radius:14px;background:#ffffff;box-shadow:0 8px 18px rgba(15,23,42,0.05);margin-bottom:12px;"><div style="font-weight:950; font-size:14px; color:#0f172a;">Audit Assignment</div><div style="font-size:12px; color:#64748b;">Enterprise scheduling and audit closure</div></div>""", unsafe_allow_html=True)
    st.markdown("### Session")
    st.markdown(f"<div class='subtle'>Tenant: <b>{st.session_state.auth.get('tenant_code','default')}</b></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='subtle'>User: <b>{username}</b></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='subtle'>Role: <b>{role}</b></div>", unsafe_allow_html=True)
    st.write("")
    st.button("Logout", on_click=logout, use_container_width=True)
    st.write("")

# ── Page functions ────────────────────────────────────────────────────────────
def page_admin_dashboard():
    tenant_id = _current_tenant_id()
    st.title("Admin Dashboard")
    render_panel("Portfolio Overview", "Visibility into audits, reports, and auditor availability.")
    st.write("")
    qa1, qa2, qa3 = st.columns(3)
    qa1.button("Create Audit", use_container_width=True)
    qa2.button("Open Audit Plan", use_container_width=True)
    qa3.button("Generate Final PDF", use_container_width=True)
    st.write("")
    render_status_legend()
    st.write("")

    closed_count = sum(1 for a in all_audits if str(a.get("status", "")).strip().lower() == "closed")
    open_count = len(all_audits) - closed_count
    pending_reports = sum(1 for a in all_audits if not a.get("reports") and str(a.get("status", "")).strip().lower() != "closed")

    c1, c2, c3, c4 = st.columns(4)
    render_kpi("Total Audits", str(len(all_audits)), "All time") if c1 else None
    with c1: render_kpi("Total Audits", str(len(all_audits)), "All time")
    with c2: render_kpi("Open Audits", str(open_count), "Assigned or in progress")
    with c3: render_kpi("Closed Audits", str(closed_count), "Completed")
    with c4: render_kpi("No Report Yet", str(pending_reports), "Open audits without uploads")

    st.write("")
    render_panel("All Audits", "Search and review audit assignments and status.")
    st.write("")
    audits_table(all_audits, search_query=st.text_input("Search audits", placeholder="Search by title, department, auditor, status, ID"))

    st.write("")
    render_panel("Auditor Availability", "FREE or BUSY based on active audit assignments.")
    st.write("")
    people = _cached_people(tenant_id)
    state = _cached_state(tenant_id)
    skill_cat = get_skill_catalog()
    rows = [{"Name": p.name, "Dept": p.department, "Level": p.level, "Status": "BUSY" if engine.is_busy(state, p.name) else "FREE", "Skills": ", ".join(skill_cat.get(k, k) for k in sorted(p.skills)), "Username": p.name.strip().lower().replace(" ", "")} for p in sorted(people, key=lambda x: (x.department, x.name.lower()))]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    cal = _cached_list_audit_calendar(tenant_id) or []
    if cal:
        st.subheader("Scheduled Audits")
        st.dataframe([{"Start Date": a.get("start_date"), "End Date": a.get("end_date"), "Audit Title": a.get("title"), "Scope": a.get("scope")} for a in cal], use_container_width=True, hide_index=True)
        st.caption("Created in Audit Calender; shown here for quick visibility.")
        st.divider()

    st.divider()
    st.subheader("Security: Change Password")
    st.caption("Change your login password. This affects only your account.")
    with st.form("admin_change_password_form"):
        old_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password", type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")
        submit_pw = st.form_submit_button("Update Password")
    if submit_pw:
        if not old_pw or not new_pw:
            st.error("All fields are required.")
        elif new_pw != confirm_pw:
            st.error("New password and confirm password do not match.")
        else:
            ok, msg = engine.change_password(username=st.session_state.auth.get("username"), old_password=old_pw, new_password=new_pw, tenant_id=st.session_state.auth.get("tenant_id"))
            st.success(msg) if ok else st.error(msg)

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
    st.title("Checklist (Auditor)")
    st.caption("Answer checklist points one-by-one. The next question unlocks only after you save Observation and Evidence for the current one.")
    if not person_name:
        st.error("Auditor profile not linked to this account."); st.stop()
    if not my_audits:
        st.info("No audits assigned to you yet."); st.stop()
    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu."); st.stop()

    dept = checklist_department.strip()
    dept_audits = [a for a in my_audits if (a.get("audited_department") or "").strip().lower() == dept.lower()]
    if not dept_audits:
        st.info(f"No audits assigned to you for department: {dept}"); st.stop()

    labels, label_to_id = build_audit_dropdown(dept_audits, restrict_to_auditor=False, auditor_name=None)
    audit_id = label_to_id[st.selectbox("Select Audit", options=labels, key=f"aud_chk_pick_audit_{dept}")]
    audit = _engine_call("get_audit", audit_id)
    if not audit:
        st.error("Audit not found."); st.stop()

    if audit.get("assigned_auditor") == person_name and audit.get("status") == "Assigned":
        _engine_call("set_audit_status", audit_id, "In Progress")
        audit = _engine_call("get_audit", audit_id)

    sections = _cached_sections_for_dept(_current_tenant_id(), dept)
    if not sections:
        st.info(f"No checklist sections found for department '{dept}'. Ask admin to create sections in Admin → Checklist."); st.stop()

    st.subheader("Department Checklist")
    section = st.selectbox("Select Checklist Section", options=sections, key=f"aud_chk_section_{audit_id}_{dept}")
    can_edit = audit.get("assigned_auditor") == person_name and audit.get("status") == "In Progress"
    if not can_edit:
        st.warning("Checklist is locked. You can edit only when this audit is 'In Progress' and assigned to you.")

    rows = _engine_call("get_checklist_rows_for_audit_section", audit_id, dept, section)
    prog = _engine_call("get_checklist_progress", audit_id, dept, section)
    total_main = int(prog.get("total", 0) or 0)
    unlocked_main = int(prog.get("unlocked", 0) or 0)
    completed_main = int(prog.get("completed_prefix", 0) or 0)

    if not rows:
        st.info("No checklist items found in this section.")
        return

    # Separate main questions from sub/subsub items
    main_rows = [r for r in rows if str(r.get("item_level", "main")) == "main"]

    if not main_rows:
        st.info("No checklist items found in this section.")
        return

    st.progress(completed_main / total_main if total_main else 0.0)
    st.caption(f"Progress: {completed_main}/{total_main} main questions completed · {unlocked_main}/{total_main} unlocked")

    # CSS for tree styling
    st.markdown("""<style>
    .chk-main{background:#fff;border:1px solid #e4e7ec;border-radius:8px;padding:12px 16px;margin-bottom:4px;box-shadow:none;transition:border-color 0.15s;}
    .chk-main.unlocked{border-left:3px solid #94a3b8;}
    .chk-main.locked{opacity:0.4;background:#fafafa;}
    .chk-main.done{border-left:3px solid #4ade80;background:#fafffe;}
    .chk-main-label{font-size:14px;font-weight:600;color:#1e293b;letter-spacing:-0.1px;}
    .chk-badge{font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;margin-left:10px;vertical-align:middle;letter-spacing:0.2px;}
    .badge-done{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;}
    .badge-pending{background:#f8fafc;color:#64748b;border:1px solid #e2e8f0;}
    .badge-locked{background:#f8fafc;color:#cbd5e1;border:1px solid #f1f5f9;}
    .chk-sub{background:#fafafa;border:1px solid #f1f5f9;border-left:2px solid #cbd5e1;border-radius:6px;padding:9px 14px;margin:3px 0 3px 20px;}
    .chk-sub.done{border-left-color:#4ade80;background:#fafffe;}
    .chk-sub-label{font-size:13px;font-weight:500;color:#475569;}
    .chk-subsub{background:#fafafa;border:1px solid #f1f5f9;border-left:2px solid #e2e8f0;border-radius:5px;padding:7px 12px;margin:3px 0 3px 40px;}
    .chk-subsub.done{border-left-color:#86efac;}
    .chk-subsub-label{font-size:12px;font-weight:400;color:#64748b;}
    .chk-connector{border-left:1px solid #e2e8f0;margin-left:16px;padding-left:14px;margin-bottom:4px;padding-top:4px;}
    </style>""", unsafe_allow_html=True)

    # Track which main question is expanded
    active_key = f"chk_active::{audit_id}::{dept}::{section}"
    if active_key not in st.session_state:
        st.session_state[active_key] = completed_main if completed_main < total_main else 0

    def _row_complete(r):
        return bool(str(r.get("observation","") or "").strip()) and bool(str(r.get("evidence","") or "").strip())

    def _get_children(parent_sr, level):
        """Get immediate children of a parent item."""
        try:
            parent_int = int(str(parent_sr))
        except Exception:
            return []
        return [r for r in rows if r.get("parent_order") == parent_int and str(r.get("item_level","")) == level]

    def _subtree_complete(main_row):
        """Check if main question + all its sub/subsub items are answered."""
        if not _row_complete(main_row): return False
        sr = main_row.get("sr_no")
        for sub in _get_children(sr, "sub"):
            if not _row_complete(sub): return False
            for subsub in _get_children(sub.get("sr_no"), "subsub"):
                if not _row_complete(subsub): return False
        return True

    def _render_answer_fields(row, indent_label, key_prefix):
        """Render observation+evidence fields for a single row."""
        sr_no = str(row.get("sr_no","")).strip()
        obs_k = f"chk_obs::{audit_id}::{dept}::{section}::{sr_no}"
        ev_k  = f"chk_ev::{audit_id}::{dept}::{section}::{sr_no}"
        if obs_k not in st.session_state:
            st.session_state[obs_k] = str(row.get("observation","") or "")
        if ev_k not in st.session_state:
            st.session_state[ev_k] = str(row.get("evidence","") or "")
        obs = st.text_area(f"Observation * ({indent_label})", key=obs_k, height=90, disabled=not can_edit)
        ev  = st.text_area(f"Evidence * ({indent_label})", key=ev_k, height=70, disabled=not can_edit)
        sc, nc, _ = st.columns([1, 1.3, 3.5])
        saved_ok = False
        with sc:
            if st.button("💾 Save", key=f"save_{key_prefix}_{sr_no}", disabled=not can_edit, use_container_width=True):
                if not str(obs or "").strip() or not str(ev or "").strip():
                    st.error("Observation and Evidence required.")
                else:
                    ok, msg = _engine_call("save_single_checklist_response", audit_id=audit_id, dept=dept, section=section, sr_no=sr_no, observation=obs, evidence=ev, auditor_name=person_name)
                    if ok: saved_ok = True; st.success("Saved."); st.rerun()
                    else: st.error(msg)
        return saved_ok

    # ── Render each main question ──────────────────────────────────────────────
    for mi, main_row in enumerate(main_rows):
        sr_no = str(main_row.get("sr_no","")).strip() or str(mi + 1)
        q_text = str(main_row.get("checklist","")).strip() or "—"
        is_locked = mi >= unlocked_main
        is_done_full = _subtree_complete(main_row)
        is_active = st.session_state[active_key] == mi

        # Status badge
        if is_locked:
            badge_html = '<span class="chk-badge badge-locked">🔒 Locked</span>'
            main_cls = "locked"
        elif is_done_full:
            badge_html = '<span class="chk-badge badge-done">✅ Done</span>'
            main_cls = "done"
        else:
            badge_html = '<span class="chk-badge badge-pending">📝 In Progress</span>'
            main_cls = "unlocked"

        st.markdown(
            f'<div class="chk-main {main_cls}">'
            f'<span class="chk-main-label">Q{mi+1}. {q_text}</span>{badge_html}'
            f'</div>',
            unsafe_allow_html=True
        )

        if not is_locked:
            btn_c1, btn_c2, _ = st.columns([1.2, 1.2, 5])
            with btn_c1:
                toggle_lbl = "▼ Close" if is_active else "▶ Open"
                if st.button(toggle_lbl, key=f"chk_toggle_{audit_id}_{dept}_{section}_{mi}", use_container_width=True):
                    st.session_state[active_key] = -1 if is_active else mi
                    st.rerun()
            with btn_c2:
                if mi > 0 and not is_active:
                    if st.button("↑ Back", key=f"chk_back_{audit_id}_{dept}_{section}_{mi}", use_container_width=True):
                        st.session_state[active_key] = mi - 1
                        st.rerun()

        # ── Expanded tree for this main question ────────────────────────────
        if is_active and not is_locked:
            with st.container():
                st.markdown('<div class="chk-connector">', unsafe_allow_html=True)

                # Main question answer fields
                st.markdown(f'<div style="font-size:12px;font-weight:700;color:#6366f1;margin-bottom:4px;">Q{mi+1} — {q_text}</div>', unsafe_allow_html=True)
                _render_answer_fields(main_row, f"Q{mi+1}", f"main_{mi}")

                # Sub-questions (A, B, C...)
                sub_rows = _get_children(sr_no, "sub")
                for si, sub_row in enumerate(sub_rows):
                    sub_letter = chr(65 + si)  # A, B, C...
                    sub_sr = str(sub_row.get("sr_no","")).strip()
                    sub_text = str(sub_row.get("checklist","")).strip() or "—"
                    sub_done = _row_complete(sub_row)
                    sub_cls = "done" if sub_done else ""

                    st.markdown(
                        f'<div class="chk-sub {sub_cls}">'
                        f'<div class="chk-sub-label">{sub_letter}) {sub_text}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    _render_answer_fields(sub_row, f"{sub_letter})", f"sub_{mi}_{si}")

                    # Sub-sub questions (a, b, c...)
                    subsub_rows = _get_children(sub_sr, "subsub")
                    for ssi, subsub_row in enumerate(subsub_rows):
                        subsub_letter = chr(97 + ssi)  # a, b, c...
                        subsub_text = str(subsub_row.get("checklist","")).strip() or "—"
                        subsub_done = _row_complete(subsub_row)
                        subsub_cls = "done" if subsub_done else ""

                        st.markdown(
                            f'<div class="chk-subsub {subsub_cls}">'
                            f'<div class="chk-subsub-label">{subsub_letter}) {subsub_text}</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        _render_answer_fields(subsub_row, f"{subsub_letter})", f"subsub_{mi}_{si}_{ssi}")

                # "Mark complete & next" button when all fields in this main Q are answered
                if _subtree_complete(main_row) and mi < total_main - 1:
                    st.success("✅ This question is fully answered!")
                    if st.button("Next Question ➜", key=f"chk_next_{audit_id}_{dept}_{section}_{mi}", type="primary"):
                        prog2 = _engine_call("get_checklist_progress", audit_id, dept, section)
                        unlocked2 = int(prog2.get("unlocked", 0) or 0)
                        if mi + 1 < unlocked2:
                            st.session_state[active_key] = mi + 1
                        st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

        st.write("")

def page_audit_details():
    st.title("Audit Details")
    render_status_legend()
    st.write("")
    labels, label_to_id = build_audit_dropdown(all_audits, restrict_to_auditor=(role == "auditor"), auditor_name=person_name)
    if not labels:
        st.warning("No audits available."); st.stop()
    selected_id = label_to_id[st.selectbox("Select Audit ID", options=labels, key="audit_details_select")]
    audit = _engine_call("get_audit", selected_id) if selected_id else None
    if not audit:
        st.warning("Select an audit."); st.stop()
    if role == "auditor" and audit.get("assigned_auditor") != person_name:
        st.error("Access denied. You can view only audits assigned to you."); st.stop()

    skill_cat = get_skill_catalog()
    st.subheader("Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", audit.get("status"))
    c2.metric("Department", audit.get("audited_department"))
    c3.metric("Auditor", audit.get("assigned_auditor"))
    c4.metric("Reports Uploaded", len(audit.get("reports", [])))
    st.write("**Title:**", audit.get("title") or "-")
    st.write("**Scope:**", audit.get("scope") or "-")
    st.write("**Required Skills:**", ", ".join(skill_cat.get(k, k) for k in audit.get("required_skills", [])) or "-")
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
            saved_path = r.get("saved_path") or ""
            with st.container(border=True):
                st.write(f"**{file_name}**")
                st.write(f"Uploaded by: {r.get('uploaded_by') or '-'}")
                st.write(f"Uploaded at: {r.get('uploaded_at') or '-'}")
                if saved_path and os.path.exists(saved_path):
                    try:
                        with open(saved_path, "rb") as f:
                            st.download_button("Download", f.read(), file_name=file_name, mime="application/octet-stream", key=f"dl_report_{audit.get('audit_id')}_{idx}")
                    except Exception:
                        st.warning("Download unavailable for this file.")
                else:
                    st.warning("File path not found on server.")

    if role == "auditor":
        st.write("")
        st.subheader("Auditor Actions")
        can_submit = audit.get("assigned_auditor") == person_name and audit.get("status") == "In Progress"
        st.markdown("#### 1) Upload Report (PDF/XLSX/XLS/CSV)")
        up = st.file_uploader("Choose a file", type=["pdf", "xlsx", "xls", "csv"], key=f"ad_up_{audit.get('audit_id')}")
        if st.button("Upload Report", type="primary", disabled=(not can_submit or up is None), key=f"ad_btn_up_{audit.get('audit_id')}"):
            ok, msg = _engine_call("save_report_file", audit_id=audit["audit_id"], uploaded_by=person_name, original_filename=up.name, file_bytes=up.getvalue())
            if ok:
                st.success(msg); _clear_caches_and_rerun()
            else:
                st.error(msg)

        st.markdown("#### 2) Submit Report (mandatory before completing)")
        checklist_ok, checklist_msg = _engine_call("validate_audit_checklists_complete", audit["audit_id"])
        if not checklist_ok:
            st.info(checklist_msg)
        if st.button("Submit Report", type="primary", disabled=(not can_submit or not checklist_ok or not audit.get("reports")), key=f"ad_btn_submit_{audit.get('audit_id')}"):
            ok, msg = _engine_call("submit_report", audit["audit_id"], person_name)
            if ok:
                st.success(msg); _clear_caches_and_rerun()
            else:
                st.error(msg)

        st.markdown("#### 3) Complete Audit (blocked without submission)")
        if st.button("Complete Audit", disabled=not can_submit, key=f"ad_btn_complete_{audit.get('audit_id')}"):
            ok, msg = _engine_call("complete_audit", audit["audit_id"], person_name)
            if ok:
                st.success(msg); _clear_caches_and_rerun()
            else:
                st.error(msg)

    if role == "admin":
        st.write("")
        st.subheader("Admin Controls")
        _status_options = ["Created", "Assigned", "In Progress", "Report Submitted", "Closed"]
        _current_status = audit.get("status") or "Assigned"
        if _current_status not in _status_options:
            _current_status = "Assigned"
        new_status = st.selectbox("Set Status", _status_options, index=_status_options.index(_current_status), key=f"ad_status_{audit.get('audit_id')}")
        if st.button("Update Status", key=f"ad_status_btn_{audit.get('audit_id')}"):
            ok, msg = _engine_call("set_audit_status", audit["audit_id"], new_status)
            if ok:
                st.success(msg); _clear_caches_and_rerun()
            else:
                st.error(msg)

def page_reports():
    st.title("Reports")
    st.caption("View submitted audit files and generated final PDFs. Admin can generate and delete final PDFs; auditors can only view/download.")
    auth = st.session_state.get("auth", {})
    tenant_id = auth.get("tenant_id")
    username = auth.get("username")
    role = auth.get("role")

    if not tenant_id:
        st.error("Tenant not found in session. Please log in again."); st.stop()

    def _download_abs_path_button(label, abs_path, key):
        try:
            with open(abs_path, "rb") as f:
                st.download_button(label=label, data=f.read(), file_name=os.path.basename(abs_path), mime="application/pdf", key=key)
        except Exception as e:
            st.warning(f"Download unavailable: {e}")

    if role == "admin":
        st.subheader("Generate Final Audit Report")
        status_filter = st.selectbox("Select audit status", ["Report Submitted", "Closed"], index=0)
        all_audits_r = engine.list_audits(tenant_id=tenant_id)
        eligible_audits = [a for a in all_audits_r if a.get("status") == status_filter]
        if not eligible_audits:
            st.info(f"No audits with status '{status_filter}'.")
        else:
            labels, label_to_id = engine.get_audit_dropdown_options(tenant_id=tenant_id)
            eligible_ids = {a["audit_id"] for a in eligible_audits}
            selected_labels = st.multiselect("Select audits to include", options=[lbl for lbl in labels if label_to_id[lbl] in eligible_ids])
            selected_ids = [label_to_id[lbl] for lbl in selected_labels]
            admin_summaries_by_audit_id = {}
            if selected_ids:
                st.markdown("**Audit Summaries**")
                for i, aid in enumerate(selected_ids):
                    lbl = selected_labels[i] if i < len(selected_labels) else aid
                    st.markdown(f"**Summary for: {lbl}**")
                    admin_summaries_by_audit_id[aid] = st.text_area(
                        label="",
                        key=f"summary_{aid}",
                        placeholder="Enter summary for this audit...",
                        height=120,
                    )
            output_name = st.text_input("Optional PDF filename (leave blank for auto-name)", placeholder="Final_Audit_Report_Q1_2026.pdf")
            if st.button("Generate Final Report", type="primary"):
                with st.spinner("Generating PDF..."):
                    if not _HAS_REPORT_GEN:
                        st.error("PDF generation is unavailable because the report generator dependencies are missing (reportlab). Install reportlab in requirements.txt to enable PDF generation.")
                        ok, pdf_path = False, None
                    else:
                        ok, msg, pdf_path = report_generator.generate_final_audit_report_pdf(tenant_id=tenant_id, generated_by=username, selected_audit_ids=selected_ids, admin_summaries_by_audit_id=admin_summaries_by_audit_id, output_filename=output_name or None)
                        if ok:
                            st.success(msg); _rerun()
                        else:
                            st.error(msg)
        st.divider()

    st.subheader("Generated Final Reports")
    reports = engine.list_final_generated_reports_for_user(username=username, role=role, tenant_id=tenant_id)
    if not reports:
        st.info("No generated final reports available.")
    else:
        for r in reports:
            st.markdown(f"### Generated on {r['created_at']}")
            st.write("Created by:", r["created_by"])
            st.write("Summary:", r["summary"])
            abs_path = engine.resolve_final_report_pdf_abs_path(tenant_id, r["pdf_rel_path"])
            if not os.path.exists(abs_path):
                st.error("PDF file missing on server.")
            else:
                _download_abs_path_button(label="Download PDF", abs_path=abs_path, key=f"download_{r['id']}")
            if role == "admin":
                if st.button("Delete Report", key=f"delete_{r['id']}"):
                    ok, msg = engine.delete_final_generated_report(report_id=r["id"], requester_role=role, tenant_id=tenant_id)
                    if ok:
                        st.success(msg); _rerun()
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
    st.title("My Timetable")
    render_panel("Timetable View", "Slots assigned by Admin are displayed for the selected date range.")
    st.write("")
    start_date = st.date_input("From", value=date.today(), key="mytt_from")
    days = st.number_input("Number of days", min_value=1, max_value=60, value=7, step=1, key="mytt_days")
    days_map = _cached_timetable_schedule().get("days", {})
    rows = [{"Date": (start_date + timedelta(days=i)).isoformat(), "Time Slot": slot, "Department to Audit": a.get("department", ""), "Auditor": a.get("auditor", "")} for i in range(int(days)) for slot, audits in days_map.get((start_date + timedelta(days=i)).isoformat(), {}).items() for a in audits if a.get("auditor") == person_name]
    if not rows:
        st.info("No timetable slots assigned to you in this period.")
    else:
        df = _pd.DataFrame(rows, columns=["Date", "Time Slot", "Department to Audit", "Auditor"]).sort_values(by=["Date", "Time Slot"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown("### Today's schedule")
        today = date.today().isoformat()
        today_rows = [r for r in rows if r["Date"] == today]
        if not today_rows:
            st.write("No slots for today.")
        else:
            st.table(_pd.DataFrame(today_rows).sort_values("Time Slot")[["Time Slot", "Department to Audit"]])

# ── Sidebar navigation ────────────────────────────────────────────────────────
checklist_department: Optional[str] = None

with st.sidebar:
    st.markdown("### Admin Menu" if role == "admin" else "### Menu")
    admin_pages = ["Dashboard", "Audit Calender", "Audit Plan", "Auditors & Skills", "Checklist", "Audit Details", "Reports"]
    auditor_pages = ["Dashboard", "My Audits", "Checklist", "Audit Details", "Reports"]
    page = st.radio("", admin_pages if role == "admin" else auditor_pages, label_visibility="collapsed")

render_breadcrumb(role, page)

# ── Page routing ──────────────────────────────────────────────────────────────
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
        depts = sorted({d for d in _cached_departments_catalog(tenant_id) if str(d).strip()}, key=lambda x: str(x).lower())
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
        st.markdown("""<style>.aog-card{background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;padding:16px 16px 12px 16px;box-shadow:0 6px 18px rgba(15,23,42,0.06);margin-top:10px}.aog-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}.aog-title{font-size:15px;font-weight:800;color:#0f172a;margin:0;letter-spacing:0.2px}.aog-sub{font-size:12.5px;color:#64748b;margin:4px 0 0 0;line-height:1.4}.aog-tag{font-size:12px;font-weight:700;color:#0f172a;background:#f8fafc;border:1px solid #e5e7eb;border-radius:999px;padding:6px 10px;white-space:nowrap}.aog-list{margin:0;padding-left:18px;color:#0f172a}.aog-list li{margin:8px 0;font-size:13px;line-height:1.45;color:#334155}.aog-list b{color:#0f172a}.aog-foot{margin-top:12px;padding-top:10px;border-top:1px dashed #e5e7eb;display:flex;gap:8px;flex-wrap:wrap;align-items:center;color:#64748b;font-size:12.3px;line-height:1.4}.aog-pill{display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #e5e7eb;background:#f8fafc;color:#0f172a;font-size:11.5px;font-weight:700}</style><div class="aog-card"><div class="aog-head"><div><div class="aog-title">Auditor Operating Guide</div><div class="aog-sub">Follow this sequence to complete an audit with accurate records and clean closure.</div></div><div class="aog-tag">Quick Guide</div></div><ol class="aog-list"><li><b>Verify session:</b> Confirm the correct <b>Tenant</b>, <b>Username</b>, and <b>Role (Auditor)</b>.</li><li><b>Review assigned audit:</b> Open <b>My Audits</b> and verify department, scope, and due date.</li><li><b>Start audit:</b> Set status to <b>In Progress</b> before entering checklist data.</li><li><b>Complete checklist:</b> Record clear <b>Observations</b> and attach/reference <b>Evidence</b> for each item.</li><li><b>Validate details:</b> Review entries in <b>Audit Details</b> for completeness before submission.</li><li><b>Submit report:</b> Upload the finalized report in <b>Reports</b> and submit as per workflow.</li><li><b>Logout:</b> Sign out after completion, especially on shared systems.</li></ol><div class="aog-foot">Navigation: <span class="aog-pill">My Audits</span><span class="aog-pill">Checklist</span><span class="aog-pill">Audit Details</span><span class="aog-pill">Reports</span></div></div>""", unsafe_allow_html=True)
    elif page == "My Audits":
        page_auditor_my_audits()
    elif page == "Checklist":
        my_depts = sorted({(a.get("audited_department") or "").strip() for a in my_audits if (a.get("audited_department") or "").strip()}, key=str.lower)
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
