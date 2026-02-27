import streamlit as st

# -----------------------------
# UI Theme (light/dark)
# -----------------------------
if "ui_theme" not in st.session_state:
    st.session_state["ui_theme"] = "light"

# -----------------------------
# Session State Defaults
# -----------------------------
def _ensure_auth_state():
    """Ensure st.session_state.auth exists to prevent AttributeError on first load."""
    if "auth" not in st.session_state or not isinstance(st.session_state.get("auth"), dict):
        st.session_state["auth"] = {}
    auth = st.session_state["auth"]
    auth.setdefault("logged_in", False)
    auth.setdefault("role", "auditor")
    auth.setdefault("username", "")
    auth.setdefault("tenant_id", "default")

_ensure_auth_state()

def _rerun():
    try:
        st.rerun()  # newer Streamlit
    except Exception:
        try:
            st.rerun()
 # older Streamlit (if available)
        except Exception:
            st.stop()  # last fallback

from typing import Any, List, Dict, Set, Optional
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import os
import json
import inspect
import glob

import engine

# Optional modules (kept optional to avoid hard-crashes on missing deps in deployment)
try:
    import timetable  # timetable.py must be in same folder
    _HAS_TIMETABLE = True
except Exception:
    timetable = None  # type: ignore
    _HAS_TIMETABLE = False

try:
    import report_generator  # final PDF report generation (depends on reportlab)
    _HAS_REPORT_GEN = True
except Exception:
    report_generator = None  # type: ignore
    _HAS_REPORT_GEN = False


# ============================================================
# ENTERPRISE (high-authority) UI THEME + COMPONENTS
# ============================================================
def inject_enterprise_css():
    st.markdown(
        """
<style>
/* ===============================
   ENTERPRISE INTERNAL TOOL UI
   (Matches shared screenshot)
   =============================== */

/* Page background */
.stApp {
    background: #f4f6f9;
    color: #0f172a;
}

/* Main container */
.block-container {
    max-width: 1200px;
    padding-top: 1.75rem;
    padding-bottom: 2.5rem;
}

/* Sidebar (unchanged layout, cleaner feel) */
section[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #e5e7eb;
}
section[data-testid="stSidebar"] * {
    color: #0f172a;
}

/* App title / headings */
h1 {
    font-size: 44px;
    font-weight: 800;
    letter-spacing: -0.4px;
    margin-bottom: 0.5rem;
}
h2 {
    font-size: 26px;
    font-weight: 700;
    margin-top: 1.2rem;
}
h3 {
    font-size: 18px;
    font-weight: 600;
}

/* Descriptive text */
p, span, li {
    color: #334155;
    font-size: 15px;
    line-height: 1.55;
}

/* Section labels (like "Portfolio Overview") */
.stMarkdown h4 {
    font-size: 16px;
    font-weight: 600;
    color: #0f172a;
}

/* Buttons – flat enterprise style */
.stButton button {
    background: #ffffff !important;
    color: #0f172a !important;
    border: 1px solid #d1d5db !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.1rem !important;
}
.stButton button:hover {
    background: #f8fafc !important;
    border-color: #94a3b8 !important;
}

/* Input fields */
input, textarea, select {
    background: #ffffff !important;
    border: 1px solid #d1d5db !important;
    border-radius: 10px !important;
    color: #0f172a !important;
}

/* Radio buttons (Admin menu look) */
div[role="radiogroup"] label {
    font-size: 15px;
    font-weight: 500;
    padding: 6px 2px;
}

/* Status pills (Assigned / In Progress / Closed) */
span[data-testid="stBadge"] {
    border-radius: 999px !important;
    font-weight: 600;
    padding: 4px 10px;
}

/* Dataframes / tables */
div[data-testid="stDataFrame"] {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    overflow: hidden;
}

/* Remove Streamlit branding */
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }

/* --- SAP/QMS spacing refinements --- */
.block-container {
    max-width: 1200px;
    padding-top: 1.4rem;   /* slightly tighter */
    padding-bottom: 2.2rem;
}
h1 { margin-top: 0.2rem; margin-bottom: 0.6rem; }
h2 { margin-top: 1.0rem; margin-bottom: 0.4rem; }
h3 { margin-top: 0.7rem; margin-bottom: 0.3rem; }

/* Breadcrumb */
.breadcrumb {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #64748b;
    font-weight: 600;
    margin: 6px 0 10px 0;
}
.breadcrumb .sep { color: #94a3b8; }
.breadcrumb .current { color: #0f172a; font-weight: 700; }

/* Status legend alignment */
.status-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
}


/* ===============================
   Calendar (modern year view)
   =============================== */
.cal-year {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1100px) {
  .cal-year { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 750px) {
  .cal-year { grid-template-columns: repeat(1, minmax(0, 1fr)); }
}
.cal-month {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 12px 12px 10px 12px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}
.cal-month-head {
  display:flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.cal-month-name {
  font-weight: 900;
  font-size: 16px;
  color: #0f172a;
}
.cal-month-meta {
  font-size: 12px;
  color: #64748b;
  font-weight: 700;
}
.cal-weekdays {
  display:grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
  margin-bottom: 6px;
}
.cal-weekday {
  font-size: 11px;
  color:#64748b;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  text-align:center;
}
.cal-days {
  display:grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}
.cal-cell {
  border: 1px solid #eef2f7;
  border-radius: 12px;
  min-height: 74px;
  padding: 6px 6px 8px 6px;
  background: #fbfdff;
  position: relative;
  overflow: hidden;
}
.cal-cell.muted {
  background: #f8fafc;
  color: #94a3b8;
}
.cal-cell:hover {
  border-color:#cbd5e1;
  box-shadow: 0 8px 16px rgba(15,23,42,0.06);
}
.cal-daynum {
  font-size: 12px;
  font-weight: 900;
  color: #0f172a;
}
.cal-cell.muted .cal-daynum {
  color: #94a3b8;
}
.cal-pills {
  margin-top: 6px;
  display:flex;
  flex-direction: column;
  gap: 4px;
}
.cal-pill {
  border-radius: 999px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1e3a8a;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 800;
  line-height: 16px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cal-pill.alt {
  border-color:#a7f3d0;
  background:#ecfdf5;
  color:#065f46;
}
.cal-pill.warn {
  border-color:#fed7aa;
  background:#fff7ed;
  color:#9a3412;
}
.cal-more {
  font-size: 11px;
  font-weight: 800;
  color: #475569;
  padding-left: 4px;
}

</style>


        """,
        unsafe_allow_html=True,
    )


def inject_theme_overrides():
    """
    Lightweight light/dark overrides on top of enterprise CSS.
    Keeps layout intact; only adjusts colors and surfaces.
    """
    theme = (st.session_state.get("ui_theme") or "light").lower().strip()
    if theme != "dark":
        return

    st.markdown(
        """
<style>
/* ============ Dark mode overrides ============ */
.stApp { background: #0b1220 !important; color: #e5e7eb !important; }
.block-container { background: transparent !important; }

section[data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: 1px solid #223047 !important;
}
section[data-testid="stSidebar"] * { color: #e5e7eb !important; }

/* Headings and text */
h1,h2,h3,h4,h5,h6 { color: #f1f5f9 !important; }
p, span, li { color: #cbd5e1 !important; }

/* Panels/cards */
.panel, .card, .hero, .kpi, .pill, .breadcrumb {
    background: #0f172a !important;
    border: 1px solid #223047 !important;
}
.panel-title, .title { color: #f1f5f9 !important; }
.panel-subtitle, .sub, .subtle { color: #94a3b8 !important; }

/* Inputs */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div,
.stMultiSelect div[data-baseweb="select"] > div, .stDateInput input {
    background: #0b1220 !important;
    color: #e5e7eb !important;
    border: 1px solid #223047 !important;
}

/* Buttons */
.stButton button, button[kind="primary"] {
    background: #111c33 !important;
    color: #e5e7eb !important;
    border: 1px solid #223047 !important;
}
.stButton button:hover { border-color: #3b82f6 !important; }

/* Tables/Data editor */
[data-testid="stDataFrame"], .stDataFrame, .stTable {
    background: #0f172a !important;
    border: 1px solid #223047 !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )

def render_topbar(username: str, role: str):
    # Theme toggle is placed on the right; header layout stays enterprise.
    left, right = st.columns([10, 1], vertical_alignment="center")
    with left:
        st.markdown(
            f"""
            <div class="hero">
                <div class="left">
                    <div class="title">Audit Assignment System</div>
                    <div class="sub">Controlled scheduling, skill matching, checklists, reports, and closure control</div>
                </div>
                <div class="pill"><span class="dot"></span>{role.upper()} • {username}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        theme = (st.session_state.get("ui_theme") or "light").lower().strip()
        icon = "🌙" if theme == "light" else "☀️"
        if st.button(icon, key="btn_toggle_theme", help="Toggle light/dark mode"):
            st.session_state["ui_theme"] = "dark" if theme == "light" else "light"
            st.rerun()

def render_breadcrumb(role: str, page_name: str):
    role_label = "Admin" if (role or "").strip().lower() == "admin" else "Auditor"
    st.markdown(
        f"""<div class="breadcrumb">
        <span>{role_label}</span><span class="sep">→</span><span class="current">{page_name}</span>
        </div>""",
        unsafe_allow_html=True,
    )



def render_panel(title: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">{title}</div>
            <div class="panel-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi(label: str, value: str, meta: str = ""):
    st.markdown(
        f"""
        <div class="kpi">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="meta">{meta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_chip(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "closed":
        bg, fg, bd = "#ecfdf5", "#065f46", "#a7f3d0"
        label = "Closed"
    elif "report" in s:
        bg, fg, bd = "#eff6ff", "#1e3a8a", "#bfdbfe"
        label = "Report Submitted"
    elif "progress" in s:
        bg, fg, bd = "#fff7ed", "#9a3412", "#fed7aa"
        label = "In Progress"
    else:
        bg, fg, bd = "#f8fafc", "#0f172a", "#e5e7eb"
        label = status or "Assigned"

    return f"""
    <span style="
        display:inline-flex; align-items:center; gap:8px;
        padding:4px 10px;
        border-radius:999px;
        border:1px solid {bd};
        background:{bg};
        color:{fg};
        font-size:12px;
        line-height:18px;
        font-weight:900;
        vertical-align:middle;">
        {label}
    </span>
    """


def render_status_legend():
    st.markdown(
        status_chip("Assigned")
        + " "
        + status_chip("In Progress")
        + " "
        + status_chip("Report Submitted")
        + " "
        + status_chip("Closed"),
        unsafe_allow_html=True,
    )


# ============================================================
# Streamlit config
# ============================================================
st.set_page_config(
    page_title="Audit Assignment System",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_enterprise_css()
inject_theme_overrides()

# ✅ MULTI-TENANT: seed default tenant safely (run once per session for speed)
if "bootstrapped" not in st.session_state:
    try:
        engine.ensure_seed_files(tenant_code="default", tenant_name="Default")
    except TypeError:
        engine.ensure_seed_files()
    st.session_state["bootstrapped"] = True

# ============================================================
# Checklist catalog seeding (safe, additive only)
# ============================================================
CHECKLIST_CANDIDATE_FILES = [
    "checklist.catalog.json",
    "checklist_catalog.json",
    "checklists_catalog.json",
]


def _find_checklist_catalog_file() -> str:
    for fn in CHECKLIST_CANDIDATE_FILES:
        if os.path.exists(fn):
            return fn
    return CHECKLIST_CANDIDATE_FILES[0]


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
    """
    Seeds Management Review, Purchase and Supplier, and HR into checklist catalog file.
    Additive only; does not delete existing data.
    """
    path = _find_checklist_catalog_file()
    catalog = _ensure_dict(_load_json_file(path, {}))

    if not isinstance(catalog, dict):
        catalog = {}

    seed: Dict[str, Dict[str, List[str]]] = {
        "Management Review": {
            "General Requirements": [
                "Does top management conduct management reviews at planned intervals?",
                "Is MRM plan documented?",
                "Is the management review procedure defined and implemented?",
                "Are management review records maintained?",
                "Is MRM notice sent, acknowledged by respective personnel, and documented?",
                "Is the MRM attendance documented?",
            ],
            "Management Review Inputs": [
                "Results of internal and external audits reviewed and documented",
                "Customer feedback (including complaints) reviewed and documented",
                "Process performance and product conformity reviewed and documented",
                "Status of preventive and corrective actions reviewed and documented",
                "Follow-up actions from previous management reviews reviewed and documented",
                "Changes that could affect the QMS (regulatory, organizational, product-related) reviewed and documented",
                "Recommendations for improvement reviewed and documented",
                "New or revised regulatory requirements applicable to medical devices reviewed and documented",
                "Resource needs (human, infrastructure, work environment) reviewed and documented",
            ],
            "Conduct of Management Review": [
                "Is the management review chaired or attended by top management?",
                "Are relevant process owners involved as required?",
                "Are discussions aligned with the planned agenda?",
            ],
            "Management Review Outputs": [
                "Decisions/actions documented for improvement of the effectiveness of the QMS",
                "Decisions/actions documented for improvement of product-related processes",
                "Decisions/actions documented for improvement of medical device safety and performance",
                "Resource requirements documented",
                "Actions addressing identified risks documented",
                "Responsibilities and timelines assigned for actions",
            ],
            "Follow-up & Records": [
                "Is the effectiveness of previous actions reviewed in subsequent MRMs?",
                "Are management review minutes legible, dated, and approved?",
            ],
        },
        "Purchase and Supplier": {
            "Supplier Selection": [
                "Is supplier selection initiated when a new material, component, or service is required?",
                "Does the Purchase Department identify potential suppliers?",
                "Are supplier identification sources documented?",
                "Are suppliers evaluated based on defined selection criteria?",
                "Are suppliers categorized based on risk-based approach?",
            ],
            "Supplier Evaluation & Approval": [
                "Is Supplier Assessment completed for potential suppliers?",
                "Is the completed assessment reviewed?",
                "Are suppliers evaluated and scored as per defined criteria?",
                "Are approved suppliers included in Approved Supplier List?",
                "For critical suppliers, is Supplier Quality Agreement executed before approval?",
            ],
            "Control of Outsourced Processes": [
                "Are outsourced processes assigned only to approved suppliers?",
                "Is verification of certificates and reports from outsourced activities carried out?",
            ],
            "Purchase Order Control": [
                "Is supplier verification against the Approved Supplier List performed before PO issuance?",
                "Is Supplier Selection & Evaluation initiated if the supplier is not approved?",
                "Are POs reviewed and approved by authorized personnel?",
                "Are PO records maintained?",
            ],
            "Verification of Purchased Product": [
                "Is Incoming Inspection conducted as per approved procedure or specifications?",
                "Are inspection results documented?",
                "Are inspection outcomes (acceptance/rejection/deviation/concession) linked to the supplier?",
                "Are non-conforming items recorded?",
                "Are inspection results used for supplier performance monitoring?",
            ],
            "Supplier Performance Evaluation": [
                "Is supplier performance evaluated based on defined parameters?",
                "Are suppliers classified according to defined rating scale?",
                "Are suppliers evaluated as per defined time period?",
                "Are supplier audits conducted when required?",
                "Is SCAR issued to the suppliers when required?",
                "Are supplier ratings reviewed in Management Review Meetings?",
            ],
            "Supplier Re-evaluation": [
                "Is re-evaluation initiated based on performance monitoring results?",
                "Are re-evaluation outcomes documented?",
            ],
        },
        "HR": {
            "Resource Planning": [
                "Is manpower planning performed at planned intervals?",
                "Are roles and responsibilities defined for all positions?",
                "Are competency requirements defined for each role?",
            ],
            "Onboarding": [
                "Is an onboarding plan available for new joiners?",
                "Are onboarding records maintained (induction, training schedule, acknowledgements)?",
            ],
            "Training Planning": [
                "Is an annual training plan prepared based on role competency requirements?",
                "Is training need identification documented (gap assessment)?",
            ],
            "Training Execution & Records": [
                "Are training records maintained (attendance, trainer, topic, date)?",
                "Are trainees assessed where applicable (quiz, observation, supervision sign-off)?",
            ],
            "Training Effectiveness": [
                "Is training effectiveness evaluated and documented?",
                "Are re-trainings or corrective actions initiated if effectiveness is not met?",
            ],
            "Regulatory & QMS Awareness": [
                "Are personnel aware of applicable regulatory/QMS requirements relevant to their roles?",
                "Is awareness training conducted for changes to procedures or regulations?",
            ],
        },
        "Production": {
        "BMR": [
                "PICK UP A BATCH MANUFACTURING RECORD (BMR)",
                "Are the following details available – batch number, manufacturing start and completion date?",
                "Are raw material lot numbers mentioned?",
                "Check for the Certificate of Analysis (COA) of the Raw Materials",
                "Does the COA give test names, specified and achieved results",
                "Check the Quality Assurance Plan (QAP)",
                "Does the QAP give details such test stage, test name, method, sample size, acceptance criteria?",
                "Are the quantities produced and rejected mentioned in the BMR?",
                "Is a NCR form filled out in case of rejections?",
                "Is the NCR report approved by the designated authority?",
                "Are the instrument IDs mentioned in the BMR?",
                "Check the calibration log and report of the instruments.",
                "Do the calibration reports mention name of an accredited lab",
                "Do the calibration reports mention traceability to national or international standards?"
            ]
},
    }

    changed = False
    for dept, sections in seed.items():
        if dept not in catalog or not isinstance(catalog.get(dept), dict):
            catalog[dept] = {}
            changed = True
        for sec, items in sections.items():
            if (
                sec not in catalog[dept]
                or not isinstance(catalog[dept].get(sec), list)
                or len(catalog[dept].get(sec, [])) == 0
            ):
                catalog[dept][sec] = items
                changed = True

    if changed:
        _save_json_file(path, catalog)


if "checklist_seeded" not in st.session_state:
    ensure_checklist_seed_data()
    st.session_state["checklist_seeded"] = True

# ============================================================
# ✅ MULTI-TENANT helpers (added only, UI stays same)
# ============================================================
def _current_tenant_id() -> Optional[str]:
    return st.session_state.auth.get("tenant_id")


def _engine_call(func_name: str, *args, **kwargs):
    """
    Calls engine.<func_name> and injects tenant_id automatically
    if the function supports it.

    Important: avoids passing tenant_id twice (positional + keyword).
    """
    fn = getattr(engine, func_name)
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        if "tenant_id" in params:
            # Only inject tenant_id if caller did not already supply it.
            if "tenant_id" not in kwargs:
                tenant_pos = params.index("tenant_id")
                if len(args) <= tenant_pos:
                    kwargs["tenant_id"] = _current_tenant_id()
    except Exception:
        pass
    return fn(*args, **kwargs)

# ============================================================
# Performance: cache high-frequency read calls to Supabase/Postgres
# Streamlit reruns the script on every interaction; caching avoids repeated network round-trips.
# ============================================================
@st.cache_data(show_spinner=False, ttl=60)
def _cached_list_audits(tenant_id: Optional[str]):
    return engine.list_audits(tenant_id=tenant_id) if hasattr(engine, "list_audits") else _engine_call("list_audits")

@st.cache_data(show_spinner=False, ttl=60)
def _cached_list_audit_calendar(tenant_id: Optional[str]):
    # calendar audits are tenant-scoped in engine
    try:
        return _engine_call("list_audit_calendar", tenant_id=tenant_id)
    except TypeError:
        return _engine_call("list_audit_calendar")

@st.cache_data(show_spinner=False, ttl=60)
def _cached_departments_catalog(tenant_id: Optional[str]):
    return _engine_call("load_departments_catalog", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_skills_catalog(tenant_id: Optional[str]):
    return _engine_call("load_skills_catalog", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=60)
def _cached_people(tenant_id: Optional[str]):
    return _engine_call("list_people_records", tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_state(tenant_id: Optional[str]):
    return _engine_call("load_state", tenant_id=tenant_id) or {}

@st.cache_data(show_spinner=False, ttl=60)
def _cached_sections_for_dept(tenant_id: Optional[str], dept: str):
    return _engine_call("get_sections_for_department", dept, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_items_for_section(tenant_id: Optional[str], dept: str, section: str):
    return _engine_call("get_items_for_department_section", dept, section, tenant_id=tenant_id) or []

@st.cache_data(show_spinner=False, ttl=60)
def _cached_timetable_schedule():
    if not _HAS_TIMETABLE or timetable is None:
        return {"days": {}}
    return timetable.load_schedule() or {"days": {}}

def _clear_caches_and_rerun():
    # Call after any write action (add/update/delete) so UI refreshes immediately.
    st.cache_data.clear()
    _rerun()


def logout():
    st.session_state.auth = {
        "logged_in": False,
        "tenant_code": "default",
        "tenant_id": None,
        "username": None,
        "role": None,
        "person_name": None,
    }
    st.rerun()


def require_login():
    if not st.session_state.auth["logged_in"]:
        st.stop()


# ============================================================
# Timetable reminder helpers
# ============================================================
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

    schedule = _cached_timetable_schedule()
    day = schedule.get("days", {}).get(today, {})

    my_today = []
    for slot, audits in day.items():
        for a in audits:
            if a.get("auditor") == auditor_name:
                my_today.append({"slot": slot, "department": a.get("department", "")})

    if not my_today:
        return

    ongoing_msg = None
    upcoming_candidates = []

    for item in my_today:
        slot = item["slot"]
        dept = item["department"]
        try:
            start_s, end_s = _parse_slot_start_end(slot)
            start_dt = datetime.combine(
                date.fromisoformat(today),
                datetime.strptime(start_s, "%H:%M").time(),
            )
            end_dt = datetime.combine(
                date.fromisoformat(today),
                datetime.strptime(end_s, "%H:%M").time(),
            )
            if tz:
                start_dt = start_dt.replace(tzinfo=tz)
                end_dt = end_dt.replace(tzinfo=tz)

            if start_dt <= now < end_dt:
                ongoing_msg = f"Active now: {slot} | Department: {dept}"
                break

            if now < start_dt:
                mins = int((start_dt - now).total_seconds() // 60)
                upcoming_candidates.append((mins, slot, dept))
        except Exception:
            continue

    if ongoing_msg:
        st.warning(ongoing_msg)
        return

    if upcoming_candidates:
        upcoming_candidates.sort(key=lambda x: x[0])
        mins, slot, dept = upcoming_candidates[0]
        if mins <= remind_within_minutes:
            st.info(f"Upcoming audit: in {mins} minutes | Start: {slot.split('-')[0]} | Department: {dept}")


# ============================================================
# Helpers: persistent dropdown options
# ============================================================
def get_department_options_with_other() -> List[str]:
    tenant_id = _current_tenant_id()
    return _cached_departments_catalog(tenant_id) + ["Other"]


def get_skill_catalog() -> Dict[str, str]:
    tenant_id = _current_tenant_id()
    return _cached_skills_catalog(tenant_id)


def _get_checklist_catalog_depts() -> List[str]:
    path = _find_checklist_catalog_file()
    catalog = _ensure_dict(_load_json_file(path, {}))
    return sorted([k for k in catalog.keys() if str(k).strip()], key=lambda x: str(x).lower())


# ============================================================
# Audit dropdown labels (Title-first) for UI
# ============================================================
def build_audit_dropdown(
    audits: List[Dict],
    *,
    restrict_to_auditor: bool,
    auditor_name: Optional[str],
) -> tuple[list[str], dict[str, str]]:
    visible = audits
    if restrict_to_auditor and auditor_name:
        visible = [a for a in audits if a.get("assigned_auditor") == auditor_name]

    labels: list[str] = []
    label_to_id: dict[str, str] = {}

    for a in visible:
        aid = (a.get("audit_id") or "").strip()
        if not aid:
            continue

        title = (a.get("title") or "").strip()
        dept = (a.get("audited_department") or "").strip()
        status = (a.get("status") or "").strip()

        base = title if title else f"{dept or 'Audit'} | {aid[:8]}"
        extras = []
        if dept:
            extras.append(dept)
        if status:
            extras.append(status)

        label = f"{base}  ({' | '.join(extras)})" if extras else base

        uniq = label
        n = 2
        while uniq in label_to_id:
            uniq = f"{label} [{n}]"
            n += 1

        labels.append(uniq)
        label_to_id[uniq] = aid

    labels = sorted(labels, key=lambda x: x.lower())
    return labels, label_to_id


# ============================================================
# Audits table
# ============================================================
def audits_table(audits: List[Dict], *, search_query: str = ""):
    if not audits:
        st.info("No audits found.")
        return

    q = (search_query or "").strip().lower()

    rows = []
    for a in audits:
        row = {
            "Audit ID": a.get("audit_id"),
            "Title": a.get("title"),
            "Dept": a.get("audited_department"),
            "Auditor": a.get("assigned_auditor"),
            "Status": a.get("status"),
            "Created": a.get("created_at"),
            "Due": a.get("due_date"),
            "Reports": len(a.get("reports", [])),
        }

        if q:
            blob = " ".join([str(v or "") for v in row.values()]).lower()
            if q not in blob:
                continue

        rows.append(row)

    if not rows:
        st.info("No results for the current search filter.")
        return

    st.dataframe(rows, use_container_width=True, hide_index=True)


# ============================================================
# ✅ Login UI
# ============================================================
if not st.session_state.auth["logged_in"]:
    render_topbar(username="Not signed in", role="Access")

    render_panel(
        "Secure Login",
        "RBAC enabled. Admin has full access; Auditor sees assigned audits only; report submission required before closure.",
    )
    st.write("")

    with st.form("login_form"):
        tenant_code = st.text_input(
            "Tenant Code (Company)",
            value=st.session_state.auth.get("tenant_code") or "default",
            placeholder="e.g., acme, beta, default",
        )
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
            st.session_state.auth = {
                "logged_in": True,
                "tenant_code": tenant_code,
                "tenant_id": u.get("tenant_id"),
                "username": u["username"],
                "role": u["role"],
                "person_name": u.get("person_name"),
            }
            st.success("Logged in.")
            st.rerun()

    st.write("")
    render_panel("Default seed credentials", "Use these only for initial testing.")
    st.write("- Admin: **admin / admin123**")
    st.write("- Auditor: username is lowercase name (no spaces), password: **auditor123**")
    st.stop()


# ============================================================
# Audit Calender (Year view)
# ============================================================
import calendar as _calendar
import pandas as _pd


def page_audit_calendar():
    st.title("Audit Calendar")
    st.caption("Create audits and view them in a clean monthly calendar.")

    tenant_id = st.session_state.auth.get("tenant_id")
    username = st.session_state.auth.get("username", "")

    # ---------- Styles ----------
    st.markdown(
        """
        <style>
        .cal-wrap { background:#ffffff; border:1px solid #e5e7eb; border-radius:18px; padding:14px 14px 10px 14px;
                    box-shadow:0 10px 24px rgba(15,23,42,0.06); }
        .cal-head { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:6px 6px 12px 6px; }
        .cal-title { font-weight:900; color:#0f172a; font-size:16px; letter-spacing:0.2px; }
        .cal-sub { color:#64748b; font-size:12px; margin-top:2px; }
        .cal-grid { display:grid; grid-template-columns:repeat(7, 1fr); gap:10px; padding:8px 6px 8px 6px; }
        .cal-dow { color:#64748b; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:0.08em;
                   padding:6px 10px; border-radius:12px; background:#f8fafc; border:1px solid #e5e7eb; text-align:center; }
        .cal-cell { border:1px solid #e5e7eb; border-radius:16px; padding:10px; min-height:92px; background:#ffffff;
                    box-shadow:0 6px 14px rgba(15,23,42,0.04); }
        .cal-cell.muted { background:#fbfdff; border-style:dashed; opacity:0.7; }
        .cal-day { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
        .cal-num { font-weight:900; color:#0f172a; font-size:13px; }
        .cal-badge { font-size:11px; font-weight:800; padding:4px 8px; border-radius:999px; border:1px solid #e5e7eb;
                     background:#f8fafc; color:#334155; }
        .cal-chip { display:block; padding:6px 8px; border-radius:12px; margin-top:6px;
                    font-size:12px; font-weight:750; line-height:1.15; border:1px solid #e2e8f0;
                    background:linear-gradient(180deg,#ffffff 0%, #f8fafc 100%);
                    color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .cal-chip small { display:block; font-weight:700; color:#64748b; margin-top:2px; }
        .cal-chip.planned { border-color:#bfdbfe; background:linear-gradient(180deg,#eff6ff 0%, #ffffff 100%); }
        .cal-chip.progress { border-color:#fde68a; background:linear-gradient(180deg,#fffbeb 0%, #ffffff 100%); }
        .cal-chip.closed { border-color:#bbf7d0; background:linear-gradient(180deg,#ecfdf5 0%, #ffffff 100%); }
        .cal-chip.other { border-color:#e5e7eb; }
        .cal-more { color:#64748b; font-size:12px; margin-top:8px; font-weight:700; }
        .cal-legend { display:flex; gap:8px; flex-wrap:wrap; padding:0 6px 10px 6px; }
        .cal-dot { width:10px; height:10px; border-radius:999px; display:inline-block; margin-right:6px; }
        .cal-pill { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px;
                    border:1px solid #e5e7eb; background:#ffffff; color:#334155; font-size:12px; font-weight:750; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---------- Create audit ----------
    with st.expander("Create a calendar audit", expanded=False):
        with st.form("create_calendar_audit_form"):
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                start = st.date_input("Start date *", value=None, key="cal_start")
            with c2:
                end = st.date_input("End date *", value=None, key="cal_end")
            with c3:
                title = st.text_input("Audit title *", key="cal_title")

            scope = st.text_area("Scope *", height=90, key="cal_scope")

            submitted = st.form_submit_button("Create audit", use_container_width=True)
            if submitted:
                if start is None or end is None:
                    st.error("Start date and end date are required.")
                elif not str(title).strip():
                    st.error("Audit title is required.")
                elif not str(scope).strip():
                    st.error("Scope is required.")
                elif end < start:
                    st.error("End date cannot be before start date.")
                else:
                    audit, msg = _engine_call(
                        "create_audit_calendar",
                        title=str(title).strip(),
                        scope=str(scope).strip(),
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                        created_by=username,
                    )
                    if audit:
                        st.success(msg)
                        _rerun()
                    else:
                        st.error(msg)

    # ---------- Filters ----------
    today = date.today()
    f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
    with f1:
        year = st.selectbox(
            "Year",
            options=list(range(today.year - 2, today.year + 6)),
            index=2,
            key="cal_year",
        )
    with f2:
        month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda m: _calendar.month_name[m],
            key="cal_month",
        )
    with f3:
        view = st.selectbox("View", options=["Calendar", "List"], index=0, key="cal_view")
    with f4:
        q = st.text_input("Search", placeholder="Type to filter by title, scope, or owner", key="cal_search")

    cal = _cached_list_audit_calendar(tenant_id) or []

    # ---------- Normalize + filter ----------
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
        blob = " ".join(
            [
                str(a.get("title", "")),
                str(a.get("scope", "")),
                str(a.get("created_by", "")),
                str(a.get("auditor", "")),
                str(a.get("owner", "")),
            ]
        ).lower()
        return q.lower() in blob

    items = []
    for a in cal:
        sd = _safe_date(a.get("start_date"))
        ed = _safe_date(a.get("end_date"))
        if ed < sd:
            sd, ed = ed, sd
        month_start = date(year, month, 1)
        month_end = date(year, month, _calendar.monthrange(year, month)[1])
        if ed < month_start or sd > month_end:
            continue
        if not _matches(a):
            continue
        items.append({**a, "_sd": sd, "_ed": ed, "_bucket": _status_bucket(a)})

    # ---------- Legend ----------
    st.markdown(
        """
        <div class="cal-legend">
          <span class="cal-pill"><span class="cal-dot" style="background:#93c5fd"></span>Planned</span>
          <span class="cal-pill"><span class="cal-dot" style="background:#fbbf24"></span>In progress</span>
          <span class="cal-pill"><span class="cal-dot" style="background:#34d399"></span>Closed</span>
          <span class="cal-pill"><span class="cal-dot" style="background:#cbd5e1"></span>Other</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if view == "List":
        if not items:
            st.info("No audits found for this month.")
            return
        items_sorted = sorted(items, key=lambda x: (x["_sd"], x.get("title", "")))
        for a in items_sorted:
            sd, ed = a["_sd"], a["_ed"]
            title = str(a.get("title", "Untitled")).strip() or "Untitled"
            scope = str(a.get("scope", "")).strip()
            owner = str(a.get("created_by", "")).strip() or str(a.get("auditor", "")).strip()
            st.markdown(
                f"""
                <div class="cal-wrap" style="margin-bottom:10px;">
                  <div class="cal-head">
                    <div>
                      <div class="cal-title">{title}</div>
                      <div class="cal-sub">{sd.strftime('%d %b %Y')} → {ed.strftime('%d %b %Y')} • Owner: {owner or '—'}</div>
                    </div>
                    <div class="cal-badge">{str(a.get('status','Planned')).strip() or 'Planned'}</div>
                  </div>
                  <div style="padding:0 6px 6px 6px; color:#334155; font-size:13px;">
                    {scope if scope else "<span style='color:#94a3b8;'>No scope provided.</span>"}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        return

    month_start = date(year, month, 1)
    first_weekday, days_in_month = _calendar.monthrange(year, month)  # Monday=0
    offset = first_weekday
    total_cells = offset + days_in_month
    rows = (total_cells + 6) // 7

    by_day = {}
    for a in items:
        d = max(a["_sd"], month_start)
        last = min(a["_ed"], date(year, month, days_in_month))
        while d <= last:
            by_day.setdefault(d, []).append(a)
            d = d + timedelta(days=1)

    dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    st.markdown(f"<div class='cal-wrap'>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="cal-head">
          <div>
            <div class="cal-title">{_calendar.month_name[month]} {year}</div>
            <div class="cal-sub">Showing {len(items)} audit(s) in this month</div>
          </div>
          <div class="cal-badge">{tenant_id or "Tenant"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='cal-grid'>" + "".join([f"<div class='cal-dow'>{d}</div>" for d in dow]) + "</div>", unsafe_allow_html=True)

    cells_html = ["<div class='cal-grid'>"]
    day_num = 1
    for r in range(rows):
        for c in range(7):
            cell_idx = r * 7 + c
            if cell_idx < offset or day_num > days_in_month:
                cells_html.append("<div class='cal-cell muted'></div>")
                continue

            d = date(year, month, day_num)
            day_num += 1

            is_today = (d == today)
            badge_html = "<span class='cal-badge'>Today</span>" if is_today else ""

            audits = sorted(by_day.get(d, []), key=lambda x: (x["_sd"], str(x.get("title",""))))
            max_show = 3
            chips = []
            for a in audits[:max_show]:
                bucket = a["_bucket"]
                title = (str(a.get("title", "Untitled")).strip() or "Untitled")
                sd, ed = a["_sd"], a["_ed"]
                if sd == ed:
                    tag = "Single day"
                elif d == sd:
                    tag = f"Starts • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}"
                elif d == ed:
                    tag = f"Ends • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}"
                else:
                    tag = f"Ongoing • {sd.strftime('%d %b')} → {ed.strftime('%d %b')}"
                scope = str(a.get("scope", "")).strip()
                tooltip = (title + (" | " + scope if scope else "")).replace('"', "&quot;")
                chips.append(f"<span class='cal-chip {bucket}' title=\"{tooltip}\">{title}<small>{tag}</small></span>")

            more = f"<div class='cal-more'>+{len(audits) - max_show} more</div>" if len(audits) > max_show else ""

            cells_html.append(
                "<div class='cal-cell'>"
                f"<div class='cal-day'><span class='cal-num'>{d.day}</span>{badge_html}</div>"
                + "".join(chips)
                + more
                + "</div>"
            )

    cells_html.append("</div>")
    st.markdown("".join(cells_html), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# Audit Plan (Working days only)
# ============================================================

def page_audit_plan():
    st.title("Audit Plan")
    st.caption("Select an audit from Audit Calender, then create a working-days schedule with 1-hour slots.")

    tenant_id = st.session_state.auth.get("tenant_id")
    username = st.session_state.auth.get("username", "")

    cal = _cached_list_audit_calendar(tenant_id) or []
    if not cal:
        st.info("No audits found in Audit Calender. Create an audit first.")
        return

    labels = []
    by_label = {}
    for a in cal:
        label = f"{a.get('title','')} ({a.get('start_date','')} -> {a.get('end_date','')})"
        labels.append(label)
        by_label[label] = a

    sel_label = st.selectbox("Select Audit", options=labels)
    audit = by_label[sel_label]
    calendar_audit_id = audit.get("id")

    st.markdown(
        "<div style='padding:12px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;'>"
        + f"<div style='font-weight:800;color:#0f172a;'>{audit.get('title','')}</div>"
        + f"<div style='color:#475569;font-size:13px;'>{audit.get('start_date','')} -> {audit.get('end_date','')}</div>"
        + f"<div style='color:#0f172a;margin-top:6px;'><b>Scope:</b> {audit.get('scope','')}</div>"
        + "</div>",
        unsafe_allow_html=True,
    )
    st.write("")

    plan = _engine_call("get_audit_plan_by_calendar_audit", calendar_audit_id=calendar_audit_id)

    with st.form("plan_create_form"):
        days_default = int(plan["working_days"]) if plan and plan.get("working_days") else 1
        days = st.number_input("How many working days will the audit run? *", min_value=1, step=1, value=days_default)
        create_btn = st.form_submit_button("Create / Reset Plan")
        if create_btn:
            p, msg = _engine_call(
                "create_or_reset_audit_plan",
                calendar_audit_id=calendar_audit_id,
                working_days=int(days),
                created_by=username,
            )
            if p:
                st.success(msg)
                _rerun()
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

    # Build a working copy of slots for editing (slot-wise UI)
    dept_list = _engine_call("list_departments_simple", tenant_id) or []
    dept_options = [""] + [d for d in dept_list if d]

    people = _cached_people(tenant_id) or []
    state = _cached_state(tenant_id) or {}
    schedule = timetable.load_schedule() if _HAS_TIMETABLE and timetable is not None else {"days": {}}

    def _norm(s: str) -> str:
        return " ".join(str(s or "").strip().split()).lower()

    def eligible_auditors_for(department: str, date_str: str, slot_str: str) -> List[str]:
        dep = (department or "").strip()
        if not dep:
            return []
        required = _engine_call("get_required_skills_for_dept", dep, tenant_id=tenant_id) if dep else set()
        required = set(required or set())

        eligible: List[str] = []
        for p in people:
            p_name = getattr(p, "name", "")
            p_dept = getattr(p, "department", "")
            p_skills = set(getattr(p, "skills", set()) or set())

            # Rule 1: must not audit own department
            if _norm(p_dept) and _norm(p_dept) == _norm(dep):
                continue

            # Rule 2: must have all required skills (if configured)
            if required and not required.issubset(p_skills):
                continue

            # Rule 3: must not be globally busy
            if engine.is_busy(state, p_name):
                continue

            # Rule 4: must not clash in timetable for this date+slot
            if _HAS_TIMETABLE and timetable is not None:
                if timetable.auditor_is_busy(schedule, date_str, slot_str, p_name):
                    continue

            eligible.append(p_name)

        return sorted(set([x for x in eligible if x]))

    st.subheader("Plan schedule")
    st.caption("Auditor dropdown follows rules: not same department, required skills match, not busy, no slot clash.")

    # Keep edited values in session_state so changes persist across reruns
    ss_key = f"plan_edits_{plan.get('plan_id')}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = {
            s.get("id"): {
                "department": s.get("department") or "",
                "auditor_name": s.get("auditor_name") or "",
                "notes": s.get("notes") or "",
            }
            for s in slots
        }

    edits = st.session_state[ss_key]

    # Render slot-wise editor
    for d in sorted(set([s.get("plan_date") for s in slots if s.get("plan_date")])):
        st.markdown(f"### {d}")
        day_slots = [s for s in slots if s.get("plan_date") == d]
        for s in day_slots:
            sid = s.get("id")
            slot_start = s.get("slot_start")
            slot_end = s.get("slot_end")
            slot_str = f"{slot_start}-{slot_end}"

            row = edits.get(sid, {"department": "", "auditor_name": "", "notes": ""})

            c1, c2, c3, c4 = st.columns([2.2, 2.2, 2.2, 3.4])
            with c1:
                st.text_input("Slot", value=slot_str, key=f"slot_lbl_{sid}", disabled=True)

            with c2:
                dept_val = st.selectbox(
                    "Department",
                    options=dept_options,
                    index=dept_options.index(row.get("department", "")) if row.get("department", "") in dept_options else 0,
                    key=f"slot_dept_{sid}",
                )

            # compute eligible list after dept selection
            elig = eligible_auditors_for(dept_val, d, slot_str)
            auditor_options = [""] + elig

            with c3:
                aud_val = st.selectbox(
                    "Auditor",
                    options=auditor_options,
                    index=auditor_options.index(row.get("auditor_name", "")) if row.get("auditor_name", "") in auditor_options else 0,
                    key=f"slot_aud_{sid}",
                )

            with c4:
                notes_val = st.text_input("Notes", value=row.get("notes", ""), key=f"slot_notes_{sid}")

            # persist edits
            edits[sid] = {"department": dept_val or "", "auditor_name": aud_val or "", "notes": notes_val or ""}

        st.divider()

    c1, c2 = st.columns(2)
    if c1.button("Auto-assign missing auditors"):
        ok, msg = _engine_call("auto_assign_auditors", tenant_id, plan["plan_id"])
        if ok:
            st.success(msg)
            # refresh edits from DB
            plan = _engine_call("get_audit_plan_by_calendar_audit", calendar_audit_id=calendar_audit_id)
            slots = plan.get("slots", []) or []
            st.session_state[ss_key] = {
                s.get("id"): {
                    "department": s.get("department") or "",
                    "auditor_name": s.get("auditor_name") or "",
                    "notes": s.get("notes") or "",
                }
                for s in slots
            }
            _rerun()
        else:
            st.error(msg)

    if c2.button("Save Audit Plan"):
        payload = []
        for s in slots:
            sid = s.get("id")
            row = edits.get(sid, {})
            payload.append(
                {
                    "plan_date": s.get("plan_date"),
                    "slot_start": s.get("slot_start"),
                    "slot_end": s.get("slot_end"),
                    "department": row.get("department", "") or "",
                    "auditor_name": row.get("auditor_name", "") or "",
                    "notes": row.get("notes", "") or "",
                }
            )
        ok, msg = _engine_call("update_audit_plan_slots", tenant_id, plan["plan_id"], payload)
        if ok:
            st.success(msg)
        else:
            st.error(msg)



# ============================================================
# Main App
# ============================================================
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


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.markdown(
        """
        <div style="
            padding:12px 12px;
            border:1px solid #e5e7eb;
            border-radius:14px;
            background:#ffffff;
            box-shadow:0 8px 18px rgba(15,23,42,0.05);
            margin-bottom:12px;">
          <div style="font-weight:950; font-size:14px; color:#0f172a;">Audit Assignment</div>
          <div style="font-size:12px; color:#64748b;">Enterprise scheduling and audit closure</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Session")
    st.markdown(
        f"<div class='subtle'>Tenant: <b>{st.session_state.auth.get('tenant_code','default')}</b></div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='subtle'>User: <b>{username}</b></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='subtle'>Role: <b>{role}</b></div>", unsafe_allow_html=True)
    st.write("")
    st.button("Logout", on_click=logout, use_container_width=True)
    st.write("")


# ==============

def page_admin_menu():
    render_panel("Admin Menu", "Quick actions and shortcuts for admin operations.")
    st.write("")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.button("Audit Calender", use_container_width=True)
    with col2:
        st.button("Audit Plan", use_container_width=True)
    with col3:
        st.button("Checklist", use_container_width=True)
    with col4:
        st.button("Reports", use_container_width=True)
    st.info("Use the tabs above to navigate. This page is a launchpad for your most common tasks.")

def page_admin_dashboard():
    tenant_id = _current_tenant_id()
    st.title("Admin Dashboard")
    render_panel("Portfolio Overview", "Visibility into audits, reports, and auditor availability.")
    st.write("")

    qa1, qa2, qa3 = st.columns(3)
    with qa1:
        st.button("Create Audit", use_container_width=True)
    with qa2:
        st.button("Open Audit Plan", use_container_width=True)
    with qa3:
        st.button("Generate Final PDF", use_container_width=True)

    st.write("")
    render_status_legend()
    st.write("")

    total = len(all_audits)
    open_count = sum(1 for a in all_audits if str(a.get("status", "")).strip().lower() != "closed")
    closed_count = sum(1 for a in all_audits if str(a.get("status", "")).strip().lower() == "closed")
    pending_reports = sum(
        1
        for a in all_audits
        if len(a.get("reports", [])) == 0 and str(a.get("status", "")).strip().lower() != "closed"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_kpi("Total Audits", str(total), "All time")
    with c2:
        render_kpi("Open Audits", str(open_count), "Assigned or in progress")
    with c3:
        render_kpi("Closed Audits", str(closed_count), "Completed")
    with c4:
        render_kpi("No Report Yet", str(pending_reports), "Open audits without uploads")

    st.write("")
    render_panel("All Audits", "Search and review audit assignments and status.")
    st.write("")

    q = st.text_input("Search audits", placeholder="Search by title, department, auditor, status, ID")
    audits_table(all_audits, search_query=q)

    st.write("")
    render_panel("Auditor Availability", "FREE or BUSY based on active audit assignments.")
    st.write("")

    people = _cached_people(tenant_id)
    state = _cached_state(tenant_id)
    skill_cat = get_skill_catalog()

    rows = []
    for p in sorted(people, key=lambda x: (x.department, x.name.lower())):
        rows.append(
            {
                "Name": p.name,
                "Dept": p.department,
                "Level": p.level,
                "Status": "BUSY" if engine.is_busy(state, p.name) else "FREE",
                "Skills": ", ".join([skill_cat.get(k, k) for k in sorted(p.skills)]),
                "Username": p.name.strip().lower().replace(" ", ""),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


    # ----------------------------
    # Scheduled Audits (from Audit Calender)
    # ----------------------------
    cal = _cached_list_audit_calendar(tenant_id) or []
    if cal:
        st.subheader("Scheduled Audits")
        st.dataframe(
            [
                {
                    "Start Date": a.get("start_date"),
                    "End Date": a.get("end_date"),
                    "Audit Title": a.get("title"),
                    "Scope": a.get("scope"),
                }
                for a in cal
            ],
            use_container_width=True,
            hide_index=True,
        )
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
            tenant_id = st.session_state.auth.get("tenant_id")
            ok, msg = engine.change_password(
                username=st.session_state.auth.get("username"),
                old_password=old_pw,
                new_password=new_pw,
                tenant_id=tenant_id,
            )
            if ok:
                st.success(msg)
            else:
                st.error(msg)



def page_admin_auditors_skills():
    st.title("Auditors & Skills")
    st.caption(
        "Add auditors (name, dept, skills). New departments/skills added via 'Other' will appear in dropdowns next time."
    )

    left, right = st.columns([1, 1])

    with left:
        render_panel("Add New Auditor", "Create auditor profiles and maintain the controlled skill library.")
        st.write("")

        skill_cat = get_skill_catalog()
        skill_keys = sorted(skill_cat.keys())

        with st.form("add_auditor_form"):
            name = st.text_input("Auditor Name", placeholder="e.g., Suman Kumar")

            dept_choice = st.selectbox("Department", get_department_options_with_other())
            custom_dept = ""
            if dept_choice == "Other":
                custom_dept = st.text_input("Enter new department", placeholder="e.g., Production, QA, Stores")
            department = custom_dept.strip() if dept_choice == "Other" else dept_choice

            level = st.selectbox("Level", ["experienced", "fresher"])

            selected_skill_keys = st.multiselect(
                "Skills",
                options=skill_keys + ["OTHER"],
                format_func=lambda k: (skill_cat.get(k, k) if k != "OTHER" else "Other"),
            )

            custom_skill_keys: List[str] = []
            if "OTHER" in selected_skill_keys:
                custom_skills_text = st.text_area(
                    "Enter new skill(s) (one per line). These will be saved and appear in dropdown next time.",
                    placeholder="e.g.\nCAPA effectiveness review\nCleanroom audit basics",
                    height=120,
                )
                custom_labels = [s.strip() for s in custom_skills_text.splitlines() if s.strip()]
                for lbl in custom_labels:
                    k = _engine_call("ensure_skill_in_catalog", lbl)
                    custom_skill_keys.append(k)

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

                ok, msg = _engine_call(
                    "add_auditor",
                    name=name,
                    department=department,
                    level=level,
                    skills=final_skill_keys,
                    password=password.strip() or "auditor123",
                )
                if ok:
                    st.success(msg)
                    _clear_caches_and_rerun()
                else:
                    st.error(msg)

    with right:
        render_panel("Auditor Dashboard", "All auditors loaded from people.json.")
        st.write("")

        people_raw = _engine_call("list_people_records")
        state = _cached_state(tenant_id)
        skill_cat = get_skill_catalog()

        rows = []
        for p in sorted(people_raw, key=lambda x: (str(x.get("department", "")), str(x.get("name", "")).lower())):
            nm = str(p.get("name", "")).strip()
            skill_keys = p.get("skills", [])
            rows.append(
                {
                    "Name": nm,
                    "Department": p.get("department"),
                    "Level": p.get("level"),
                    "Skills": ", ".join([skill_cat.get(k, k) for k in skill_keys]),
                    "Status": "BUSY" if engine.is_busy(state, nm) else "FREE",
                    "Username": nm.strip().lower().replace(" ", ""),
                }
            )

        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("### Delete Auditor")
        delete_name = st.text_input("Enter exact auditor name to delete", placeholder="e.g., Suman Kumar")
        if st.button("Delete Auditor"):
            ok, msg = _engine_call("delete_auditor", delete_name)
            if ok:
                st.success(msg)
                _clear_caches_and_rerun()
            else:
                st.error(msg)




def page_admin_create_assign():
    st.title("Audit Calendar")
    st.info("This module has been disabled. We will rebuild it later.")

def page_admin_audit_plan():
    st.title("Audit Plan")
    st.info("This module has been disabled. We will rebuild it later.")

def page_admin_checklist():
    st.title("Checklist (Admin)")
    st.caption("Create department-wise checklists with sections. Auditors will fill Observation and Evidence during audits.")

    import pandas as pd

    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu.")
        st.stop()

    dept_for_checklist = checklist_department
    render_panel("Checklist Library", f"Department: {dept_for_checklist}")
    st.write("")

    sections = _cached_sections_for_dept(_current_tenant_id(), dept_for_checklist)
    pick_section = st.selectbox("Section", ["(Create New)"] + sections, key=f"chk_admin_section_{dept_for_checklist}")

    new_section = ""
    if pick_section == "(Create New)":
        new_section = st.text_input("New Section Name", key=f"chk_admin_new_section_{dept_for_checklist}").strip()

    section_name = new_section if pick_section == "(Create New)" else pick_section

    existing_items = _cached_items_for_section(_current_tenant_id(), dept_for_checklist, section_name) if section_name else []
    st.write("Edit checklist items below. One row = one checklist point.")

    df_items = pd.DataFrame({"Checklist": existing_items if existing_items else [""]})

    edited_df = st.data_editor(
        df_items,
        use_container_width=True,
        num_rows="dynamic",
        key=f"chk_admin_editor_{dept_for_checklist}_{section_name or 'blank'}",
    )

    cA, cB, cC = st.columns([1, 1, 2])

    with cA:
        if st.button("Save Section Checklist", type="primary", key=f"chk_admin_save_{dept_for_checklist}"):
            if not section_name:
                st.error("Please select an existing section or enter a new section name.")
            else:
                cleaned = [str(x).strip() for x in edited_df["Checklist"].tolist() if str(x).strip()]
                _engine_call("upsert_section_items", dept_for_checklist, section_name, cleaned)
                st.success(f"Saved checklist for: {dept_for_checklist} → {section_name}")
                st.rerun()

    with cB:
        if pick_section != "(Create New)" and st.button("Delete Section", key=f"chk_admin_delete_{dept_for_checklist}_{pick_section}"):
            _engine_call("delete_section", dept_for_checklist, pick_section)
            st.success(f"Deleted section: {dept_for_checklist} → {pick_section}")
            st.rerun()

    with cC:
        st.info("Tip: Create sections like General Requirements, Inputs, Outputs, etc.")




def page_auditor_checklist():
    st.title("Checklist (Auditor)")
    st.caption("Answer checklist points one-by-one. The next question unlocks only after you save Observation and Evidence for the current one.")

    if not person_name:
        st.error("Auditor profile not linked to this account.")
        st.stop()

    if not my_audits:
        st.info("No audits assigned to you yet.")
        st.stop()

    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu.")
        st.stop()

    dept = checklist_department.strip()
    dept_audits = [
        a for a in my_audits
        if (a.get("audited_department") or "").strip().lower() == dept.lower()
    ]

    if not dept_audits:
        st.info(f"No audits assigned to you for department: {dept}")
        st.stop()

    labels, label_to_id = build_audit_dropdown(
        dept_audits,
        restrict_to_auditor=False,
        auditor_name=None,
    )
    selected_label = st.selectbox("Select Audit", options=labels, key=f"aud_chk_pick_audit_{dept}")
    audit_id = label_to_id[selected_label]

    audit = _engine_call("get_audit", audit_id)
    if not audit:
        st.error("Audit not found.")
        st.stop()

    # Auto-start audit on first checklist interaction
    if audit.get("assigned_auditor") == person_name and audit.get("status") == "Assigned":
        _engine_call("set_audit_status", audit_id, "In Progress")
        audit = _engine_call("get_audit", audit_id)

    sections = _cached_sections_for_dept(_current_tenant_id(), dept)
    if not sections:
        st.info(f"No checklist sections found for department '{dept}'. Ask admin to create sections in Admin → Checklist.")
        st.stop()

    st.subheader("Department Checklist (Sequential)")
    section = st.selectbox("Select Checklist Section", options=sections, key=f"aud_chk_section_{audit_id}_{dept}")

    can_edit = (
        audit.get("assigned_auditor") == person_name
        and audit.get("status") == "In Progress"
    )
    if not can_edit:
        st.warning("Checklist is locked. You can edit only when this audit is 'In Progress' and assigned to you.")

    # Load rows (initializes from catalog if empty)
    rows = _engine_call("get_checklist_rows_for_audit_section", audit_id, dept, section)
    prog = _engine_call("get_checklist_progress", audit_id, dept, section)

    total = int(prog.get("total", 0) or 0)
    unlocked = int(prog.get("unlocked", 0) or 0)
    completed_prefix = int(prog.get("completed_prefix", 0) or 0)

    if total == 0:
        st.info("No checklist items found in this section.")
        return

    # Progress UI
    st.progress(completed_prefix / total if total else 0.0)
    st.caption(f"Progress: {completed_prefix}/{total} completed in sequence. Unlocked: {unlocked}/{total}.")

    # Add extra checklist point (still allowed, but it will appear at the end)
    with st.expander("Add extra checklist point (optional)", expanded=False):
        extra_text = st.text_input("New checklist point", key=f"aud_extra_item_{audit_id}_{dept}_{section}")
        if st.button("Add checklist point", key=f"aud_extra_add_{audit_id}_{dept}_{section}", disabled=not can_edit):
            if not extra_text.strip():
                st.error("Please enter a checklist point.")
            else:
                ok, msg = _engine_call(
                    "add_audit_section_checklist_item",
                    audit_id=audit_id,
                    dept=dept,
                    section=section,
                    checklist_text=extra_text.strip(),
                    auditor_name=person_name,
                )
                if ok:
                    st.success(msg)
                    _clear_caches_and_rerun()
                else:
                    st.error(msg)

    # Determine which row to show (one at a time)
    ss_idx_key = f"seq_idx::{audit_id}::{dept}::{section}"
    default_idx = min(completed_prefix, max(total - 1, 0))  # next unanswered, or last if done
    if ss_idx_key not in st.session_state:
        st.session_state[ss_idx_key] = default_idx

    # Clamp index inside unlocked range (auditor cannot jump ahead)
    max_allowed_idx = max(unlocked - 1, 0)
    cur_idx = int(st.session_state[ss_idx_key] or 0)
    cur_idx = max(0, min(cur_idx, max_allowed_idx))
    st.session_state[ss_idx_key] = cur_idx

    current = rows[cur_idx]
    sr_no = str(current.get("sr_no", "")).strip() or str(cur_idx + 1)
    q_text = str(current.get("checklist", "")).strip()

    st.markdown(
        f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:14px 14px 10px 14px;
                    box-shadow:0 10px 24px rgba(15,23,42,0.06);">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
            <div style="font-weight:950;color:#0f172a;font-size:14px;">Question {cur_idx + 1} of {total}</div>
            <div style="font-weight:900;color:#64748b;font-size:12px;">SR No: {sr_no}</div>
          </div>
          <div style="margin-top:8px;color:#0f172a;font-size:14px;font-weight:800;">{q_text if q_text else "—"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")

    obs_key = f"seq_obs::{audit_id}::{dept}::{section}::{sr_no}"
    ev_key = f"seq_ev::{audit_id}::{dept}::{section}::{sr_no}"

    # Pre-fill inputs from saved values
    if obs_key not in st.session_state:
        st.session_state[obs_key] = str(current.get("observation", "") or "")
    if ev_key not in st.session_state:
        st.session_state[ev_key] = str(current.get("evidence", "") or "")

    observation = st.text_area("Observation *", key=obs_key, height=110, disabled=not can_edit)
    evidence = st.text_area("Evidence *", key=ev_key, height=90, disabled=not can_edit)

    nav1, nav2, nav3, nav4 = st.columns([1.2, 1.2, 2.5, 2.0])
    with nav1:
        prev_disabled = (cur_idx <= 0)
        if st.button("← Previous", disabled=prev_disabled, use_container_width=True, key=f"seq_prev_{audit_id}_{dept}_{section}"):
            st.session_state[ss_idx_key] = max(0, cur_idx - 1)
            st.rerun()

    with nav2:
        # Save without advancing (useful for edits)
        if st.button("Save", type="secondary", disabled=not can_edit, use_container_width=True, key=f"seq_save_{audit_id}_{dept}_{section}_{sr_no}"):
            if not str(observation or "").strip() or not str(evidence or "").strip():
                st.error("Observation and Evidence are required to save.")
            else:
                ok, msg = _engine_call(
                    "save_single_checklist_response",
                    audit_id=audit_id,
                    dept=dept,
                    section=section,
                    sr_no=sr_no,
                    observation=observation,
                    evidence=evidence,
                    auditor_name=person_name,
                )
                if ok:
                    st.success("Saved.")
                    st.rerun()
                else:
                    st.error(msg)

    with nav4:
        # Save and move to next unlocked row (which becomes unlocked by this save)
        next_label = "Save & Next →" if (cur_idx < total - 1) else "Save"
        if st.button(next_label, type="primary", disabled=not can_edit, use_container_width=True, key=f"seq_next_{audit_id}_{dept}_{section}_{sr_no}"):
            if not str(observation or "").strip() or not str(evidence or "").strip():
                st.error("Observation and Evidence are required to continue.")
            else:
                ok, msg = _engine_call(
                    "save_single_checklist_response",
                    audit_id=audit_id,
                    dept=dept,
                    section=section,
                    sr_no=sr_no,
                    observation=observation,
                    evidence=evidence,
                    auditor_name=person_name,
                )
                if ok:
                    # Recompute unlocked after save, then jump to next if allowed
                    prog2 = _engine_call("get_checklist_progress", audit_id, dept, section)
                    unlocked2 = int(prog2.get("unlocked", 0) or 0)
                    max_allowed2 = max(unlocked2 - 1, 0)

                    if cur_idx < max_allowed2:
                        st.session_state[ss_idx_key] = cur_idx + 1
                    else:
                        st.session_state[ss_idx_key] = min(cur_idx, max_allowed2)
                    st.rerun()
                else:
                    st.error(msg)

    # Optional: show already-unlocked answers for review (does NOT unlock future questions)
    with st.expander("Review unlocked answers", expanded=False):
        shown = rows[:unlocked]
        if not shown:
            st.write("Nothing unlocked yet.")
        else:
            for i, r in enumerate(shown, start=1):
                st.markdown(f"**{i}. {r.get('checklist','')}**")
                st.write("Observation:", r.get("observation","") or "—")
                st.write("Evidence:", r.get("evidence","") or "—")
                st.markdown("---")


    # ============================================================
    # Audit Details (Admin + Auditor)
    # ============================================================

    # ============================================================

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

    # ----------------------------
    # Reports (list + download)
    # ----------------------------
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

    # ----------------------------
    # Auditor Actions (Upload + Submit + Complete) on Audit Details page
    # ----------------------------
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

    # ----------------------------
    # Admin Controls
    # ----------------------------
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


    # ============================================================
    # Reports Page (Admin + Auditor)
    # ============================================================

def page_reports():
    st.title("Reports")
    st.caption(
        "View submitted audit files and generated final PDFs. "
        "Admin can generate and delete final PDFs; auditors can only view/download."
    )

    import os
    import engine
    import report_generator

    # ------------------------------------------------------------------
    # Session essentials
    # ------------------------------------------------------------------
    auth = st.session_state.get("auth", {})
    tenant_id = auth.get("tenant_id")
    username = auth.get("username")
    role = auth.get("role")

    if not tenant_id:
        st.error("Tenant not found in session. Please log in again.")
        st.stop()

    # ------------------------------------------------------------------
    # Helper: download button from absolute path
    # ------------------------------------------------------------------
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

    # ==============================================================
    # ADMIN: Generate Final Audit Report
    # ==============================================================
    if role == "admin":
        st.subheader("Generate Final Audit Report")

        # Filter audits by status
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

            for aid in selected_ids:
                st.markdown(f"**Summary for audit `{aid}`**")
                admin_summaries_by_audit_id[aid] = st.text_area(
                    label="",
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

    # ==============================================================
    # VIEW & DOWNLOAD GENERATED FINAL REPORTS (ADMIN + AUDITOR)
    # ==============================================================
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

            # Admin-only delete
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



# ============================================================
# Navigation (Sidebar Radio – Enterprise style)
# ============================================================

checklist_department: Optional[str] = None

with st.sidebar:
    st.markdown("### Admin Menu" if role == "admin" else "### Menu")

    if role == "admin":
        page = st.radio(
            "",
            [
                "Dashboard",
                "Audit Calender",
                "Audit Plan",
                "Auditors & Skills",
                "Checklist",
                "Audit Details",
                "Reports",
            ],
            label_visibility="collapsed",
        )
    else:
        page = st.radio(
            "",
            [
                "Dashboard",
                "My Audits",
                "Checklist",
                "Audit Details",
                "Reports",
            ],
            label_visibility="collapsed",
        )
        
# ============================================================
# Page Routing
# ============================================================

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
            <style>
              /* Auditor Operating Guide: enterprise card */
              .aog-card{
                background:#ffffff;
                border:1px solid #e5e7eb;
                border-radius:14px;
                padding:16px 16px 12px 16px;
                box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
                margin-top:10px;
              }

              .aog-head{
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:12px;
                margin-bottom:10px;
              }

              .aog-title{
                font-size:15px;
                font-weight:800;
                color:#0f172a;
                margin:0;
                letter-spacing:0.2px;
              }

              .aog-sub{
                font-size:12.5px;
                color:#64748b;
                margin:4px 0 0 0;
                line-height:1.4;
              }

              .aog-tag{
                font-size:12px;
                font-weight:700;
                color:#0f172a;
                background:#f8fafc;
                border:1px solid #e5e7eb;
                border-radius:999px;
                padding:6px 10px;
                white-space:nowrap;
              }

              .aog-list{
                margin:0;
                padding-left:18px;
                color:#0f172a;
              }

              .aog-list li{
                margin:8px 0;
                font-size:13px;
                line-height:1.45;
                color:#334155;
              }

              .aog-list b{
                color:#0f172a;
              }

              .aog-foot{
                margin-top:12px;
                padding-top:10px;
                border-top:1px dashed #e5e7eb;
                display:flex;
                gap:8px;
                flex-wrap:wrap;
                align-items:center;
                color:#64748b;
                font-size:12.3px;
                line-height:1.4;
              }

              .aog-pill{
                display:inline-block;
                padding:2px 8px;
                border-radius:999px;
                border:1px solid #e5e7eb;
                background:#f8fafc;
                color:#0f172a;
                font-size:11.5px;
                font-weight:700;
              }
            </style>

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