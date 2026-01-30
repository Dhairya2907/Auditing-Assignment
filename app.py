import streamlit as st

def _rerun():
    try:
        st.rerun()  # newer Streamlit
    except Exception:
        try:
            st.rerun()
 # older Streamlit (if available)
        except Exception:
            st.stop()  # last fallback

from typing import List, Dict, Set, Optional
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import os
import json
import inspect
import glob

import engine
import timetable  # timetable.py must be in same folder
import report_generator  # final PDF report generation


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

</style>


        """,
        unsafe_allow_html=True,
    )


def render_topbar(username: str, role: str):
    # Uses the .hero + .pill styles from injected CSS
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

# ✅ MULTI-TENANT: seed default tenant safely (no UI changes)
try:
    engine.ensure_seed_files(tenant_code="default", tenant_name="Default")
except TypeError:
    engine.ensure_seed_files()

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


ensure_checklist_seed_data()

# ============================================================
# ✅ MULTI-TENANT helpers (added only, UI stays same)
# ============================================================
def _current_tenant_id() -> Optional[str]:
    return st.session_state.auth.get("tenant_id")


def _engine_call(func_name: str, *args, **kwargs):
    """
    Calls engine.<func_name> and injects tenant_id automatically
    if the function supports it.
    """
    fn = getattr(engine, func_name)
    try:
        sig = inspect.signature(fn)
        if "tenant_id" in sig.parameters:
            kwargs.setdefault("tenant_id", _current_tenant_id())
    except Exception:
        pass
    return fn(*args, **kwargs)


# ============================================================
# Session state
# ============================================================
if "auth" not in st.session_state:
    st.session_state.auth = {
        "logged_in": False,
        "tenant_code": "default",
        "tenant_id": None,
        "username": None,
        "role": None,
        "person_name": None,
    }


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

    schedule = timetable.load_schedule()
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
    return _engine_call("load_departments_catalog") + ["Other"]


def get_skill_catalog() -> Dict[str, str]:
    return _engine_call("load_skills_catalog")


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
# Main App
# ============================================================
require_login()

role = st.session_state.auth["role"]
username = st.session_state.auth["username"]
person_name = st.session_state.auth.get("person_name")

render_topbar(username=username, role=role)

if role == "auditor" and person_name:
    show_auditor_timetable_reminder(person_name, remind_within_minutes=30)

all_audits = _engine_call("list_audits")
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
        st.button("Create & Assign Audit", use_container_width=True)
    with col2:
        st.button("Audit Plan", use_container_width=True)
    with col3:
        st.button("Checklist", use_container_width=True)
    with col4:
        st.button("Reports", use_container_width=True)
    st.info("Use the tabs above to navigate. This page is a launchpad for your most common tasks.")

def page_admin_dashboard():
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

    people = _engine_call("load_people")
    state = _engine_call("load_state")
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
                    st.rerun()
                else:
                    st.error(msg)

    with right:
        render_panel("Auditor Dashboard", "All auditors loaded from people.json.")
        st.write("")

        people_raw = _engine_call("list_people_records")
        state = _engine_call("load_state")
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
                st.rerun()
            else:
                st.error(msg)



def page_admin_create_assign():
    st.title("Create & Assign Audit")
    st.caption(
        "If department has no required skills defined yet, you can enter required skills and optionally save them as default."
    )

    skill_cat = get_skill_catalog()

    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Audit Title (optional)", placeholder="e.g., Internal Audit - Jan")

        dept_choice = st.selectbox("Department to Audit", get_department_options_with_other(), key="ca_dept")
        custom_dept = ""
        if dept_choice == "Other":
            custom_dept = st.text_input("Enter new department to audit", key="ca_new_dept")
        target_dept = custom_dept.strip() if dept_choice == "Other" else dept_choice

        allow_fallback = st.checkbox("Allow fresher fallback (still needs 100% skill match)", value=True)

        st.markdown("**Required skills**")
        existing_req = _engine_call("get_required_skills_for_dept", target_dept) if target_dept else set()

        required_override: Set[str] | None = None
        save_as_default = False

        if existing_req:
            st.success("Using saved required skills for this department.")
            st.write([skill_cat.get(k, k) for k in sorted(existing_req)])
        else:
            st.warning("No required skills defined for this department yet.")
            req_text = st.text_area(
                "Enter required skill(s) for this audit (one per line). These can be saved as default for the department.",
                placeholder="e.g.\nSupplier evaluation\nTraining record review",
                height=120,
            )
            labels = [s.strip() for s in req_text.splitlines() if s.strip()]
            req_keys: List[str] = []
            for lbl in labels:
                req_keys.append(_engine_call("ensure_skill_in_catalog", lbl))
            required_override = set(req_keys) if req_keys else set()
            save_as_default = st.checkbox("Save these required skills as default for this department", value=True)

    with col2:
        scope = st.text_area("Scope (optional)", placeholder="Write scope or checklist reference...")
        due_date = st.text_input("Due Date (optional)", placeholder="YYYY-MM-DD")

    if st.button("Assign Auditor", type="primary"):
        if not target_dept:
            st.error("Department is required.")
        else:
            audit, msg = _engine_call(
                "create_and_assign_audit",
                created_by=username,
                target_dept=target_dept,
                allow_fresher_fallback=allow_fallback,
                title=title,
                scope=scope,
                due_date=due_date,
                required_skill_keys_override=required_override
                if required_override is not None and len(required_override) > 0
                else None,
                save_required_skills_as_default=save_as_default,
            )
            if not audit:
                st.error(msg)
            else:
                st.success(msg)
                st.json(audit)



def page_admin_audit_plan():
        import pandas as pd

        st.title("Audit Plan")
        st.caption(
            "Rules: auditor cannot audit own department, 100% skill match, auditor FREE in main system, and FREE in selected slot."
        )

        skill_cat = get_skill_catalog()
        SLOTS = timetable.generate_daily_slots("09:30", "18:30", 60)

        selected_date = st.date_input("Select audit date", value=date.today(), key="tt_date")
        date_str = selected_date.isoformat()

        timetable.ensure_day_slots(date_str, SLOTS)

        st.divider()

        col1, col2 = st.columns([1, 2], gap="large")

        with col1:
            st.subheader("Add audit plan entry")

            slot = st.selectbox("Time slot", SLOTS, key="tt_slot")

            dept_choice = st.selectbox("Department to Audit", get_department_options_with_other(), key="tt_dept")
            custom_dept = ""
            if dept_choice == "Other":
                custom_dept = st.text_input("Enter new department to audit", key="tt_custom_dept")
            audited_dept = custom_dept.strip() if dept_choice == "Other" else dept_choice

            required = _engine_call("get_required_skills_for_dept", audited_dept) if audited_dept else set()
            save_as_default = False
            if required:
                st.write("Required skills (saved):")
                st.write([skill_cat.get(k, k) for k in sorted(required)])
            else:
                st.warning("No required skills defined. Enter required skills for matching.")
                req_text = st.text_area(
                    "Required skill(s) (one per line)",
                    key="tt_req_text",
                    height=120,
                    placeholder="e.g.\nProcess audit planning\nSupplier evaluation\nTraining record review",
                )
                labels = [s.strip() for s in req_text.splitlines() if s.strip()]
                req_keys = [_engine_call("ensure_skill_in_catalog", lbl) for lbl in labels]
                required = set(req_keys)
                save_as_default = st.checkbox("Save as default required skills for this department", value=True, key="tt_save_req")

            people = _engine_call("load_people")
            state = _engine_call("load_state")
            schedule = timetable.load_schedule()

            eligible_names = []
            for p in people:
                if p.department.strip().lower() == audited_dept.strip().lower():
                    continue
                if required and (not required.issubset(set(p.skills))):
                    continue
                if engine.is_busy(state, p.name):
                    continue
                if timetable.auditor_is_busy(schedule, date_str, slot, p.name):
                    continue
                eligible_names.append(p.name)

            eligible_names = sorted(set(eligible_names), key=lambda x: x.lower())

            if not eligible_names:
                st.warning("No eligible auditors available for this slot and department.")
                auditor = None
            else:
                auditor = st.selectbox("Eligible Auditor", eligible_names, key="tt_auditor")

            if st.button("Add to Audit Plan", type="primary", key="tt_add_btn"):
                if not audited_dept:
                    st.error("Department is required.")
                elif not required:
                    st.error("Required skills are required for matching.")
                elif auditor is None:
                    st.error("No eligible auditor available.")
                else:
                    _engine_call("add_department_to_catalog", audited_dept)
                    if save_as_default:
                        _engine_call("set_dept_required_skills", audited_dept, sorted(required))

                    ok, msg = timetable.add_audit_to_slot(
                        date_str=date_str,
                        slot=slot,
                        department=audited_dept,
                        auditor=auditor
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with col2:
            st.subheader(f"Audit Plan for {date_str}")

            rows = timetable.flatten_timetable(date_str)
            df = pd.DataFrame(rows, columns=["Date", "Time Slot", "Department", "Auditor", "Status"])
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown("### Remove a scheduled entry")
            remove_slot = st.selectbox("Slot to remove from", SLOTS, key="tt_remove_slot")
            audits_in_slot = timetable.get_slot_audits(date_str, remove_slot)

            if not audits_in_slot:
                st.info("No scheduled audits in this slot.")
            else:
                options = [f'{a["department"]} | {a["auditor"]}' for a in audits_in_slot]
                pick = st.selectbox("Select entry", options, key="tt_remove_pick")

                if st.button("Remove selected entry", key="tt_remove_btn"):
                    dep, aud = [x.strip() for x in pick.split("|", 1)]
                    ok, msg = timetable.remove_audit_from_slot(date_str, remove_slot, dep, aud)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)


    # ============================================================
    # Checklist pages
    # ============================================================

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

    sections = _engine_call("get_sections_for_department", dept_for_checklist)
    pick_section = st.selectbox("Section", ["(Create New)"] + sections, key=f"chk_admin_section_{dept_for_checklist}")

    new_section = ""
    if pick_section == "(Create New)":
        new_section = st.text_input("New Section Name", key=f"chk_admin_new_section_{dept_for_checklist}").strip()

    section_name = new_section if pick_section == "(Create New)" else pick_section

    existing_items = _engine_call("get_items_for_department_section", dept_for_checklist, section_name) if section_name else []
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
        st.caption("Fill Observation and Evidence for your assigned audits. You can also add extra checklist points for the selected audit.")

        import pandas as pd

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

        if audit.get("assigned_auditor") == person_name and audit.get("status") == "Assigned":
            _engine_call("set_audit_status", audit_id, "In Progress")
            audit = _engine_call("get_audit", audit_id)

        sections = _engine_call("get_sections_for_department", dept)
        if not sections:
            st.info(f"No checklist sections found for department '{dept}'. Ask admin to create sections in Admin → Checklist.")
            st.stop()

        st.subheader("Department Checklist (Section-wise)")
        section = st.selectbox("Select Checklist Section", options=sections, key=f"aud_chk_section_{audit_id}_{dept}")

        saved_rows = _engine_call("load_audit_section_table", audit_id, dept, section)
        if saved_rows:
            df = pd.DataFrame(saved_rows)
            df = df.rename(columns={
                "sr_no": "SR No",
                "checklist": "Checklist",
                "observation": "Observation",
                "evidence": "Evidence",
            })
        else:
            items = _engine_call("get_items_for_department_section", dept, section)
            df = pd.DataFrame({
                "SR No": list(range(1, len(items) + 1)),
                "Checklist": items,
                "Observation": ["" for _ in items],
                "Evidence": ["" for _ in items],
            })

        st.caption("Fill Observation and Evidence for every checklist point. You can add extra checklist points for this audit and section.")

        can_edit = (
            audit.get("assigned_auditor") == person_name
            and audit.get("status") == "In Progress"
        )

        if not can_edit:
            st.warning("Checklist is locked. You can edit only when this audit is 'In Progress' and assigned to you.")

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
                        st.rerun()
                    else:
                        st.error(msg)

        edited = st.data_editor(
            df,
            use_container_width=True,
            disabled=["SR No", "Checklist"] if can_edit else ["SR No", "Checklist", "Observation", "Evidence"],
            key=f"aud_chk_editor_{audit_id}_{dept}_{section}",
        )

        if st.button(
            "Save Checklist Observations",
            type="primary",
            key=f"aud_chk_save_{audit_id}_{dept}_{section}",
            disabled=not can_edit,
        ):
            rows_to_save = []
            for _, r in edited.iterrows():
                rows_to_save.append({
                    "sr_no": str(r.get("SR No", "")).strip(),
                    "checklist": str(r.get("Checklist", "")).strip(),
                    "observation": str(r.get("Observation", "")).strip(),
                    "evidence": str(r.get("Evidence", "")).strip(),
                })

            ok, msg = _engine_call(
                "save_audit_section_table",
                audit_id,
                dept,
                section,
                rows_to_save,
                auditor_name=person_name,
            )
            if ok:
                st.success("Checklist saved.")
                st.rerun()
            else:
                st.error(msg)


    # ============================================================
    # Audit Details (Admin + Auditor)
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
                    st.rerun()
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
                    st.rerun()
                else:
                    st.error(msg)

            st.markdown("#### 3) Complete Audit (blocked without submission)")
            if st.button("Complete Audit", disabled=(not can_submit), key=f"ad_btn_complete_{audit.get('audit_id')}"):
                ok, msg = _engine_call("complete_audit", audit["audit_id"], person_name)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        # ----------------------------
        # Admin Controls
        # ----------------------------
        if role == "admin":
            st.write("")
            st.subheader("Admin Controls")

            new_status = st.selectbox(
                "Set Status",
                ["Assigned", "In Progress", "Report Submitted", "Closed"],
                index=["Assigned", "In Progress", "Report Submitted", "Closed"].index(audit.get("status", "Assigned")),
                key=f"ad_status_{audit.get('audit_id')}",
            )
            if st.button("Update Status", key=f"ad_status_btn_{audit.get('audit_id')}"):
                ok, msg = _engine_call("set_audit_status", audit["audit_id"], new_status)
                if ok:
                    st.success(msg)
                    st.rerun()
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

    schedule = timetable.load_schedule()
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
                "Auditors & Skills",
                "Create & Assign Audit",
                "Audit Plan",
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
                "My Timetable",
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
    elif page == "Auditors & Skills":
        page_admin_auditors_skills()
    elif page == "Create & Assign Audit":
        page_admin_create_assign()
    elif page == "Audit Plan":
        page_admin_audit_plan()
    elif page == "Checklist":
        depts = _get_checklist_catalog_depts() or _engine_call("load_departments_catalog")
        if not depts:
            st.info("No departments found.")
        else:
            checklist_department = st.selectbox("Department", options=depts)
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
    elif page == "My Audits":
        page_auditor_my_audits()
    elif page == "My Timetable":
        page_auditor_my_timetable()
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
  