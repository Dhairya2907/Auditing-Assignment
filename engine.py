from __future__ import annotations

import os
import re
import json
import uuid
import hashlib
import hmac
import sqlite3

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Set, Optional, Tuple

import timetable  # keep your existing import


# ============================================================
# SQLite (NO external service) + Multi-tenant storage
# ============================================================

# Where SQLite DB will be stored
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join("data", "app.db"))

# Uploads root (tenant-separated subfolders)
UPLOADS_DIR = "uploads"

# Default tenant code used when your UI does not ask for tenant yet
DEFAULT_TENANT_CODE = os.getenv("DEFAULT_TENANT_CODE", "default")

# -----------------------------
# Default seed data (per tenant)
# -----------------------------
DEFAULT_DEPARTMENTS = ["HR", "MR", "Purchase", "Sales and Marketing"]

DEFAULT_SKILLS = {
    # HR
    "hr_competency_training_requirements": "Understanding of competency and training requirements",
    "hr_review_training_records_effectiveness": "Ability to review training records and effectiveness",
    "hr_personnel_regulatory_awareness": "Awareness of regulatory requirements related to personnel",

    # Purchase
    "pur_supplier_selection_evaluation": "Understanding of supplier selection and evaluation criteria",
    "pur_incoming_inspection_linkage": "Ability to assess incoming inspection linkage with purchasing",
    "pur_supplier_agreements_quality_clauses": "Awareness of supplier agreements and quality clauses",

    # Sales and Marketing
    "sm_labeling_claims_control": "Knowledge of labelling and claims control",
    "sm_customer_communication_feedback": "Skill in reviewing customer communication and feedback",
    "sm_complaint_intake_escalation": "Awareness of complaint intake and escalation",
}

DEFAULT_DEPT_REQUIRED_SKILLS = {
    "HR": [
        "hr_competency_training_requirements",
        "hr_review_training_records_effectiveness",
        "hr_personnel_regulatory_awareness",
    ],
    "Purchase": [
        "pur_supplier_selection_evaluation",
        "pur_incoming_inspection_linkage",
        "pur_supplier_agreements_quality_clauses",
    ],
    "Sales and Marketing": [
        "sm_labeling_claims_control",
        "sm_customer_communication_feedback",
        "sm_complaint_intake_escalation",
    ],
    "MR": [],
}


# ============================================================
# Data models
# ============================================================
@dataclass(frozen=True)
class Person:
    name: str
    department: str
    skills: Set[str]  # skill KEYS
    level: str        # "experienced" or "fresher"


# ============================================================
# Helpers
# ============================================================
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _normalize_username(name: str) -> str:
    return name.strip().lower().replace(" ", "")

def _normalize_text(s: str) -> str:
    return " ".join(str(s or "").strip().split())

def ensure_dirs() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    db_dir = os.path.dirname(SQLITE_DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

def _uuid() -> str:
    return str(uuid.uuid4())


# ============================================================
# Tenant upload folder helpers (used across modules)
# ============================================================
def _tenant_root_dir(tenant_id: str) -> str:
    return os.path.join(UPLOADS_DIR, "tenants", str(tenant_id))

def _tenant_generated_reports_dir(tenant_id: str) -> str:
    d = os.path.join(_tenant_root_dir(tenant_id), "generated_reports")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
# Password hashing (PBKDF2) - keep your existing approach
# ============================================================
def _pbkdf2_hash(password: str, salt_hex: str, iterations: int) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return dk.hex()

def make_password_record(password: str) -> Dict[str, Any]:
    salt = os.urandom(16).hex()
    iterations = 150_000
    return {
        "salt": salt,
        "iterations": iterations,
        "hash": _pbkdf2_hash(password, salt, iterations),
    }

def verify_password(password: str, rec: Dict[str, Any]) -> bool:
    salt = rec.get("salt", "")
    it = int(rec.get("iterations", 150_000))
    expected = rec.get("hash", "")
    if not salt or not expected:
        return False
    got = _pbkdf2_hash(password, salt, it)
    return hmac.compare_digest(got, expected)

def _verify_password_columns(password: str, salt_hex: str, iterations: int, hash_hex: str) -> bool:
    if not salt_hex or not hash_hex:
        return False
    try:
        iterations = int(iterations)
    except Exception:
        return False
    got = _pbkdf2_hash(password, salt_hex, iterations)
    return hmac.compare_digest(got, hash_hex)


# ============================================================
# SQLite DB layer
# ============================================================
def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # safer multi-user usage
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

def _fetch_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

def _fetch_all(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

def _execute(sql: str, params: Tuple[Any, ...] = ()) -> int:
    with _connect() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount

def _executescript(script: str) -> None:
    with _connect() as conn:
        conn.executescript(script)


# ============================================================
# Schema + seed
# ============================================================
_SCHEMA = """
create table if not exists tenants (
  id text primary key,
  tenant_code text not null unique,
  name text not null,
  created_at text not null default (datetime('now'))
);

create table if not exists users (
  id text primary key,
  tenant_id text not null,
  username text not null,
  role text not null check (role in ('admin','manager','auditor')),
  person_name text,
  password_salt text not null,
  password_iterations integer not null,
  password_hash text not null,
  is_active integer not null default 1,
  created_at text not null default (datetime('now')),
  unique (tenant_id, username),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_users_tenant on users(tenant_id);

create table if not exists departments (
  id text primary key,
  tenant_id text not null,
  name text not null,
  created_at text not null default (datetime('now')),
  unique (tenant_id, name),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_departments_tenant on departments(tenant_id);

create table if not exists skills_catalog (
  id text primary key,
  tenant_id text not null,
  skill_key text not null,
  skill_label text not null,
  created_at text not null default (datetime('now')),
  unique (tenant_id, skill_key),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_skills_tenant on skills_catalog(tenant_id);

create table if not exists dept_required_skills (
  id text primary key,
  tenant_id text not null,
  department_name text not null,
  skill_key text not null,
  unique (tenant_id, department_name, skill_key),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_deptreq_tenant on dept_required_skills(tenant_id);

create table if not exists people (
  id text primary key,
  tenant_id text not null,
  name text not null,
  department text not null,
  level text not null check (level in ('experienced','fresher')),
  is_active integer not null default 1,
  created_at text not null default (datetime('now')),
  unique (tenant_id, name),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_people_tenant on people(tenant_id);

create table if not exists person_skills (
  id text primary key,
  tenant_id text not null,
  person_name text not null,
  skill_key text not null,
  unique (tenant_id, person_name, skill_key),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_personskills_tenant on person_skills(tenant_id);

create table if not exists audits (
  audit_id text primary key,
  tenant_id text not null,
  title text,
  scope text,
  audited_department text not null,
  required_skills_json text not null,
  assigned_auditor text not null,
  auditor_level text not null,
  status text not null,
  created_by text not null,
  created_at text not null,
  due_date text,
  reports_json text not null,
  report_submitted_at text,
  closed_at text,
  checklists_json text not null,
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_audits_tenant on audits(tenant_id);

create table if not exists audit_state (
  tenant_id text primary key,
  busy_by_name_json text not null,
  audit_history_json text not null,
  foreign key (tenant_id) references tenants(id) on delete cascade
);

create table if not exists checklists_catalog (
  id text primary key,
  tenant_id text not null,
  department text not null,
  section text not null,
  item_order integer not null,
  item_text text not null,
  unique (tenant_id, department, section, item_order),
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_chk_tenant on checklists_catalog(tenant_id);

-- ============================================================
-- Final Generated Reports (multi-audit PDF)
-- ============================================================
create table if not exists generated_final_reports (
  id text primary key,
  tenant_id text not null,
  created_by text not null,
  created_at text not null,
  summary text not null,
  audit_ids_json text not null,
  allowed_users_json text not null,
  pdf_rel_path text not null,
  is_deleted integer not null default 0,
  deleted_at text,
  deleted_by text,
  foreign key (tenant_id) references tenants(id) on delete cascade
);
create index if not exists idx_finalreports_tenant on generated_final_reports(tenant_id);
create index if not exists idx_finalreports_createdat on generated_final_reports(created_at);
"""

def init_db() -> None:
    _executescript(_SCHEMA)

def _get_tenant_by_code(tenant_code: str) -> Optional[Dict[str, Any]]:
    tenant_code = _normalize_text(tenant_code).lower()
    return _fetch_one(
        "select id, tenant_code, name from tenants where tenant_code = ? limit 1;",
        (tenant_code,),
    )

def ensure_tenant(tenant_code: str, tenant_name: str = "") -> str:
    """
    Create tenant if missing. Returns tenant_id.
    """
    init_db()
    tenant_code = _normalize_text(tenant_code).lower()
    if not tenant_code:
        tenant_code = DEFAULT_TENANT_CODE

    row = _get_tenant_by_code(tenant_code)
    if row:
        return str(row["id"])

    tenant_id = _uuid()
    name = _normalize_text(tenant_name) or tenant_code.upper()
    _execute(
        "insert into tenants (id, tenant_code, name) values (?, ?, ?);",
        (tenant_id, tenant_code, name),
    )
    return tenant_id

def _ensure_state_row(tenant_id: str) -> None:
    row = _fetch_one("select tenant_id from audit_state where tenant_id = ?;", (tenant_id,))
    if row:
        return
    _execute(
        "insert into audit_state (tenant_id, busy_by_name_json, audit_history_json) values (?, ?, ?);",
        (tenant_id, json.dumps({}), json.dumps([])),
    )

def _seed_checklists_if_empty(tenant_id: str) -> None:
    existing = _fetch_one("select id from checklists_catalog where tenant_id = ? limit 1;", (tenant_id,))
    if existing:
        return

    # Seed (same content you had, minimal changes)
    seed = {
        "HR": {
            "Resource Planning": [
                "Has top management determined the need for resources and documented it?",
                "Was the Resource Plan prepared as per the decided time period?",
                "Were process owners involved in preparing the Resource Plan?",
                "Is there evidence of consultation with Top Management and MR?",
                "Is the Resource Plan reviewed during Management Review Meetings (MRM) and documented?",
            ],
            "Pre-Boarding & Onboarding": [
                "Are pre-boarding details completed by the process owner for selected candidates?",
                "Is the Employee Boarding Checklist used and completed?",
                "Are education, experience, and training records collected and maintained?",
                "Is the Employee Master List updated after joining?",
            ],
            "Job Roles, Responsibilities & Communication": [
                "Are job roles, authorities, and responsibilities documented in Job Roles, Tasks, Competency Profile?",
                "Has top management communicated job roles and responsibilities?",
                "Is acknowledgement of JD communication recorded?",
            ],
            "Competency & Skill Management": [
                "Are employee skills identified within 7 days of joining?",
                "Is the Skill Matrix available and updated?",
                "Is the Skill Matrix reviewed as per the decided time period?",
                "Are improvements in skills documented and updated?",
            ],
            "Exit Management": [
                "Are exit formalities maintained for employees leaving the organization?",
                "Is employee list updated post-exit?",
            ],
            "Training Planning": [
                "Has top management planned training for all employees and documented them?",
                "Is a Training List maintained and used to select training topics?",
                "Is the Training planning documented as per the time period?",
                "Are planned trainings communicated to employees?",
            ],
            "Conduct of Trainings": [
                "Are trainings conducted as per the approved Training Plan?",
                "Are email or documented communications available as evidence?",
            ],
            "Evaluation of Trainings": [
                "Is training effectiveness evaluated upon completion?",
                "Is evaluation documented appropriately?",
                "Are appropriate evaluation methods selected?",
            ],
        },
        "MR": {
            "General Requirements": [
                "Does top management conduct management reviews at planned intervals?",
                "Is MRM plan documented",
                "Is the management review procedure defined and implemented?",
                "Are management review records maintained",
                "Is MRM notice sent acknowledged by respective personnel and is it documented?",
                "Is the MRM attendance documented?",
            ],
            "Management Review Inputs": [
                "Results of internal and external audits",
                "Customer feedback (including complaints)",
                "Process performance and product conformity",
                "Status of preventive and corrective actions",
                "Follow-up actions from previous management reviews",
                "Changes that could affect the QMS (regulatory, organizational, product-related)",
                "Recommendations for improvement",
                "New or revised regulatory requirements applicable to medical devices",
                "Resource needs (human, infrastructure, work environment)",
            ],
            "Conduct of Management Review": [
                "Is the management review chaired or attended by top management?",
                "Are relevant process owners involved as required?",
                "Are discussions aligned with the planned agenda?",
            ],
            "Management Review Outputs": [
                "Improvement of the effectiveness of the QMS",
                "Improvement of product-related processes",
                "Improvement of medical device safety and performance",
                "Resource requirements",
                "Actions addressing identified risks",
                "Responsibilities and timelines assigned for actions",
            ],
            "Follow-up & Records": [
                "Is the effectiveness of previous actions reviewed in subsequent MRMs?",
                "Are management review minutes legible, dated, and approved?",
            ],
        },
        "Purchase": {
            "Supplier Selection": [
                "Is supplier selection initiated when a new material, component, or service is required?",
                "Does the Purchase Department identify potential suppliers?",
                "Are supplier identification sources documented",
                "Are suppliers evaluated based on defined selection criteria?",
                "Are suppliers categorized on risk based approach?",
            ],
            "Supplier Evaluation & Approval": [
                "Is Supplier Assessment completed for potential suppliers",
                "Is the completed assessment reviewed",
                "Are suppliers evaluated and scored as per defined criteria?",
                "Are approved suppliers included in Approved Supplier List",
                "For critical suppliers, is Supplier Quality Agreement executed before approval?",
            ],
            "Control of Outsourced Processes": [
                "Are outsourced processes assigned only to approved suppliers?",
                "Is verification of certificates and reports from outsourced activities carried out?",
            ],
            "Purchase Order Control": [
                "Is supplier verification against the Approved Supplier List performed before PO issuance?",
                "Is Supplier Selection & Evaluation initiated if the supplier is not approved",
                "Are POs reviewed and approved by authorized personnel?",
                "Are PO records maintained?",
            ],
            "Verification of Purchased Product": [
                "Is Incoming Inspection conducted as per approved procedure or specifications?",
                "Are inspection results documented?",
                "Are inspection outcomes (acceptance/rejection/deviation/concession) linked to the supplier?",
                "Are non-conforming items recorded",
                "Are inspection results used for supplier performance monitoring",
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
    }

    for dept, sections in seed.items():
        for section, items in sections.items():
            for i, item in enumerate(items, start=1):
                _execute(
                    """
                    insert into checklists_catalog
                    (id, tenant_id, department, section, item_order, item_text)
                    values (?, ?, ?, ?, ?, ?);
                    """,
                    (_uuid(), tenant_id, dept, section, i, item),
                )

def ensure_seed_files(tenant_code: str = "", tenant_name: str = "") -> str:
    """
    OLD name kept for compatibility with your existing app.
    Now it creates DB schema + tenant + per-tenant seeds.
    Returns tenant_id.
    """
    init_db()
    ensure_dirs()

    tenant_code = _normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE
    tenant_id = ensure_tenant(tenant_code, tenant_name)

    # ensure tenant upload folders exist (including final reports folder)
    _tenant_generated_reports_dir(tenant_id)

    # seed departments
    for d in DEFAULT_DEPARTMENTS:
        add_department_to_catalog(d, tenant_id=tenant_id)

    # seed skills catalog
    for k, v in DEFAULT_SKILLS.items():
        ensure_skill_key_exists(k, fallback_label=v, tenant_id=tenant_id)

    # seed dept required skills
    for dept, keys in DEFAULT_DEPT_REQUIRED_SKILLS.items():
        set_dept_required_skills(dept, keys, tenant_id=tenant_id)

    # seed checklists (only if empty)
    _seed_checklists_if_empty(tenant_id)

    # seed state row
    _ensure_state_row(tenant_id)

    # seed admin + sample auditors only if tenant has no users
    has_user = _fetch_one("select id from users where tenant_id = ? limit 1;", (tenant_id,))
    if not has_user:
        # admin
        admin_pw = make_password_record("admin123")
        _execute(
            """
            insert into users
            (id, tenant_id, username, role, person_name, password_salt, password_iterations, password_hash, is_active, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 1, ?);
            """,
            (
                _uuid(), tenant_id, "admin", "admin", None,
                admin_pw["salt"], int(admin_pw["iterations"]), admin_pw["hash"],
                _now_iso(),
            ),
        )

        # sample people + auditor logins
        sample_people = [
            {
                "name": "Priya",
                "department": "HR",
                "skills": [
                    "hr_competency_training_requirements",
                    "hr_review_training_records_effectiveness",
                    "hr_personnel_regulatory_awareness",
                ],
                "level": "experienced",
            },
            {
                "name": "Amit",
                "department": "Purchase",
                "skills": [
                    "pur_supplier_selection_evaluation",
                    "pur_incoming_inspection_linkage",
                    "pur_supplier_agreements_quality_clauses",
                ],
                "level": "experienced",
            },
            {
                "name": "Ravi",
                "department": "Sales and Marketing",
                "skills": [
                    "sm_labeling_claims_control",
                    "sm_customer_communication_feedback",
                    "sm_complaint_intake_escalation",
                ],
                "level": "experienced",
            },
        ]
        for p in sample_people:
            add_auditor(
                name=p["name"],
                department=p["department"],
                level=p["level"],
                skills=set(p["skills"]),
                password="auditor123",
                tenant_id=tenant_id,
            )

    return tenant_id


# ============================================================
# Tenant helpers for UI
# ============================================================
def get_tenant_id(tenant_code: str = "") -> str:
    return ensure_seed_files(tenant_code=tenant_code)

def get_tenant_code_from_id(tenant_id: str) -> str:
    row = _fetch_one("select tenant_code from tenants where id = ?;", (tenant_id,))
    return str(row["tenant_code"]) if row else DEFAULT_TENANT_CODE


# ============================================================
# Catalog: departments (tenant-aware)
# ============================================================
def load_departments_catalog(tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        "select name from departments where tenant_id = ? order by lower(name);",
        (tenant_id,),
    )
    return [str(r["name"]) for r in rows]

def add_department_to_catalog(dept: str, tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    if not dept:
        return
    _execute(
        "insert or ignore into departments (id, tenant_id, name, created_at) values (?, ?, ?, ?);",
        (_uuid(), tenant_id, dept, _now_iso()),
    )

# ============================================================
# Catalog: skills (key -> label) (tenant-aware)
# ============================================================
def load_skills_catalog(tenant_id: Optional[str] = None) -> Dict[str, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        "select skill_key, skill_label from skills_catalog where tenant_id = ?;",
        (tenant_id,),
    )
    out: Dict[str, str] = {}
    for r in rows:
        out[str(r["skill_key"]).strip().lower()] = _normalize_text(r["skill_label"])
    return out

def ensure_skill_key_exists(skill_key: str, fallback_label: str = "", tenant_id: Optional[str] = None) -> str:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    kk = str(skill_key).strip().lower()
    if not kk:
        raise ValueError("Skill key cannot be empty.")

    row = _fetch_one(
        "select skill_key from skills_catalog where tenant_id = ? and skill_key = ?;",
        (tenant_id, kk),
    )
    if row:
        return kk

    label = _normalize_text(fallback_label) or kk
    _execute(
        """
        insert into skills_catalog (id, tenant_id, skill_key, skill_label, created_at)
        values (?, ?, ?, ?, ?);
        """,
        (_uuid(), tenant_id, kk, label, _now_iso()),
    )
    return kk

def ensure_skill_in_catalog(label: str, tenant_id: Optional[str] = None) -> str:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    label = _normalize_text(label)
    if not label:
        raise ValueError("Skill label cannot be empty.")

    rows = _fetch_all(
        "select skill_key, skill_label from skills_catalog where tenant_id = ?;",
        (tenant_id,),
    )
    for r in rows:
        if str(r["skill_label"]).strip().lower() == label.lower():
            return str(r["skill_key"]).strip().lower()

    new_key = f"custom_{uuid.uuid4().hex[:10]}"
    ensure_skill_key_exists(new_key, fallback_label=label, tenant_id=tenant_id)
    return new_key

# ============================================================
# Required skills per department (tenant-aware)
# Stored as rows (dept, skill_key)
# ============================================================
def load_dept_required_skills(tenant_id: Optional[str] = None) -> Dict[str, List[str]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        """
        select department_name, skill_key
        from dept_required_skills
        where tenant_id = ?
        order by lower(department_name), lower(skill_key);
        """,
        (tenant_id,),
    )
    out: Dict[str, List[str]] = {}
    for r in rows:
        dept = _normalize_text(r["department_name"])
        key = str(r["skill_key"]).strip().lower()
        out.setdefault(dept, []).append(key)

    for d in list(out.keys()):
        seen = set()
        uniq = []
        for k in out[d]:
            if k in seen:
                continue
            seen.add(k)
            uniq.append(k)
        out[d] = uniq
    return out

def set_dept_required_skills(dept: str, skill_keys: List[str], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    if not dept:
        raise ValueError("Department cannot be empty.")

    add_department_to_catalog(dept, tenant_id=tenant_id)

    cleaned: List[str] = []
    seen = set()
    for k in (skill_keys or []):
        kk = str(k).strip().lower()
        if not kk:
            continue
        kk = ensure_skill_key_exists(kk, fallback_label=kk, tenant_id=tenant_id)
        if kk in seen:
            continue
        seen.add(kk)
        cleaned.append(kk)

    _execute(
        "delete from dept_required_skills where tenant_id = ? and department_name = ?;",
        (tenant_id, dept),
    )
    for kk in cleaned:
        _execute(
            """
            insert or ignore into dept_required_skills
            (id, tenant_id, department_name, skill_key)
            values (?, ?, ?, ?);
            """,
            (_uuid(), tenant_id, dept, kk),
        )

def get_required_skills_for_dept(dept: str, tenant_id: Optional[str] = None) -> Set[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    rows = _fetch_all(
        """
        select skill_key
        from dept_required_skills
        where tenant_id = ? and department_name = ?;
        """,
        (tenant_id, dept),
    )
    return {str(r["skill_key"]).strip().lower() for r in rows}


# ============================================================
# Checklists catalog (Admin-managed) (tenant-aware)
# ============================================================
def get_checklist_catalog(tenant_id: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        """
        select department, section, item_order, item_text
        from checklists_catalog
        where tenant_id = ?
        order by lower(department), lower(section), item_order;
        """,
        (tenant_id,),
    )
    out: Dict[str, Dict[str, List[str]]] = {}
    for r in rows:
        dept = _normalize_text(r["department"])
        section = _normalize_text(r["section"])
        out.setdefault(dept, {}).setdefault(section, []).append(str(r["item_text"]))
    return out

def get_sections_for_department(dept: str, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    rows = _fetch_all(
        """
        select distinct section
        from checklists_catalog
        where tenant_id = ? and department = ?
        order by lower(section);
        """,
        (tenant_id, dept),
    )
    return [str(r["section"]) for r in rows]

def get_items_for_department_section(dept: str, section: str, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    rows = _fetch_all(
        """
        select item_text
        from checklists_catalog
        where tenant_id = ? and department = ? and section = ?
        order by item_order;
        """,
        (tenant_id, dept, section),
    )
    return [str(r["item_text"]) for r in rows]

def upsert_section_items(dept: str, section: str, items: List[str], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    if not dept or not section:
        return

    _execute(
        "delete from checklists_catalog where tenant_id = ? and department = ? and section = ?;",
        (tenant_id, dept, section),
    )
    clean_items = [str(x).strip() for x in (items or []) if str(x).strip()]
    for idx, txt in enumerate(clean_items, start=1):
        _execute(
            """
            insert into checklists_catalog
            (id, tenant_id, department, section, item_order, item_text)
            values (?, ?, ?, ?, ?, ?);
            """,
            (_uuid(), tenant_id, dept, section, idx, txt),
        )

def delete_section(dept: str, section: str, tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    if not dept or not section:
        return
    _execute(
        "delete from checklists_catalog where tenant_id = ? and department = ? and section = ?;",
        (tenant_id, dept, section),
    )

# -----------------------------
# Per-audit checklist extras (auditor-added)
# -----------------------------
def get_checklist_extras(audit: Dict[str, Any], dept: str, section: str) -> List[str]:
    """Return auditor-added checklist items stored within the audit record."""
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    try:
        extras = (((audit.get("checklist_extras") or {}).get(dept) or {}).get(section) or [])
    except Exception:
        extras = []
    if not isinstance(extras, list):
        return []
    out: List[str] = []
    for x in extras:
        s = str(x).strip()
        if s:
            out.append(s)
    return out

def get_effective_checklist_items(
    audit_id: str,
    dept: str,
    section: str,
    tenant_id: Optional[str] = None,
) -> List[str]:
    """Catalog checklist items + per-audit extras (deduped, preserves order)."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)

    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return []

    catalog_items = get_items_for_department_section(dept, section, tenant_id=tenant_id) or []
    catalog_items = [str(x).strip() for x in catalog_items if str(x).strip()]
    extras = get_checklist_extras(a, dept, section)

    seen = set()
    out: List[str] = []
    for it in catalog_items + extras:
        k = it.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it.strip())
    return out

def add_checklist_extra_item(
    audit_id: str,
    dept: str,
    section: str,
    item_text: str,
    auditor_name: str,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    item_text = str(item_text or "").strip()

    if not item_text:
        return False, "Checklist item cannot be empty."

    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    if a.get("status") != "In Progress":
        return False, "Checklist can be edited only when the audit is 'In Progress'."

    if a.get("assigned_auditor") != auditor_name:
        return False, "You are not assigned to this audit."

    a.setdefault("checklist_extras", {})
    a["checklist_extras"].setdefault(dept, {})
    a["checklist_extras"][dept].setdefault(section, [])

    current = a["checklist_extras"][dept][section]
    if not isinstance(current, list):
        current = []
        a["checklist_extras"][dept][section] = current

    if item_text.lower() in {str(x).strip().lower() for x in current}:
        return False, "This checklist item already exists."

    current.append(item_text)
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Added checklist item."

def delete_checklist_extra_item(
    audit_id: str,
    dept: str,
    section: str,
    item_text: str,
    auditor_name: str,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    item_text = str(item_text or "").strip()

    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    if a.get("assigned_auditor") != auditor_name:
        return False, "You are not assigned to this audit."

    if a.get("status") != "In Progress":
        return False, "You can edit extra checklist items only when the audit is 'In Progress'."

    sec_list = (((a.get("checklist_extras") or {}).get(dept) or {}).get(section) or [])
    if not isinstance(sec_list, list) or not sec_list:
        return False, "No extra checklist items to delete."

    new_list = [x for x in sec_list if str(x).strip().lower() != item_text.lower()]
    if len(new_list) == len(sec_list):
        return False, "Item not found."

    a.setdefault("checklist_extras", {})
    a["checklist_extras"].setdefault(dept, {})
    a["checklist_extras"][dept][section] = new_list
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Deleted checklist item."


# ============================================================
# Reports: Save uploaded report file + attach to audit
# ============================================================
def _safe_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal and weird characters."""
    name = (name or "").strip()
    if not name:
        return "report"
    name = name.replace("\\", "/").split("/")[-1]  # drop any path
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:180] or "report"


# ============================================================
# Final Generated Reports (multi-audit PDF) - tenant-aware
# ============================================================
def _safe_relpath_under_tenant(tenant_id: str, rel_path: str) -> str:
    """
    Ensures rel_path stays within tenant root (prevents path traversal).
    Stores and uses relative paths, but validates with absolute comparison.
    """
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel_path:
        raise ValueError("rel_path is required.")

    tenant_root = os.path.abspath(_tenant_root_dir(tenant_id))
    abs_path = os.path.abspath(os.path.join(tenant_root, rel_path))

    if not abs_path.startswith(tenant_root + os.sep) and abs_path != tenant_root:
        raise ValueError("Invalid path (outside tenant root).")

    return rel_path

def resolve_final_report_pdf_abs_path(tenant_id: str, pdf_rel_path: str) -> str:
    rel = _safe_relpath_under_tenant(tenant_id, pdf_rel_path)
    tenant_root = os.path.abspath(_tenant_root_dir(tenant_id))
    return os.path.abspath(os.path.join(tenant_root, rel))

def _normalize_users_list(users: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for u in (users or []):
        uu = _normalize_text(u)
        if not uu:
            continue
        key = uu.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(uu)
    return out

def _audit_ids_to_auditors(audit_ids: List[str], tenant_id: str) -> List[str]:
    """
    Returns unique auditor usernames for audits. In your system, auditor login is normalize_username(person_name).
    """
    if not audit_ids:
        return []
    rows = _fetch_all(
        """
        select audit_id, assigned_auditor
        from audits
        where tenant_id = ? and audit_id in ({})
        """.format(",".join(["?"] * len(audit_ids))),
        tuple([tenant_id] + audit_ids),
    )
    auditors: List[str] = []
    seen = set()
    for r in rows:
        person_name = _normalize_text(r.get("assigned_auditor", ""))
        if not person_name:
            continue
        uname = _normalize_username(person_name)
        if uname and uname.lower() not in seen:
            seen.add(uname.lower())
            auditors.append(uname)
    return auditors


def save_report_file(
    audit_id: str,
    uploaded_by: str,
    original_filename: str,
    file_bytes: bytes,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Saves uploaded file to disk and appends it into audit['reports'].
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    audit_id = str(audit_id or "").strip()
    if not audit_id:
        return False, "audit_id is required."

    if not file_bytes:
        return False, "File is empty."

    uploaded_by = _normalize_text(uploaded_by) or "unknown"
    safe_name = _safe_filename(original_filename)

    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    tenant_root = os.path.join(UPLOADS_DIR, "tenants", str(tenant_id))
    report_dir = os.path.join(tenant_root, "audits", audit_id, "reports")
    os.makedirs(report_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(safe_name)
    if not ext:
        ext = ".bin"
    saved_name = f"{base}_{ts}{ext}"
    saved_path = os.path.join(report_dir, saved_name)

    try:
        with open(saved_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        return False, f"Failed to save file: {e}"

    reports = a.get("reports", [])
    if not isinstance(reports, list):
        reports = []

    reports.append(
        {
            "file_name": safe_name,
            "saved_path": saved_path,
            "uploaded_by": uploaded_by,
            "uploaded_at": _now_iso(),
        }
    )
    a["reports"] = reports
    _save_updated_audit(a, tenant_id=tenant_id)

    return True, "Report uploaded successfully."


# ============================================================
# People (tenant-aware)
# ============================================================
def load_people(tenant_id: Optional[str] = None) -> List[Person]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    people_rows = _fetch_all(
        "select name, department, level from people where tenant_id = ? and is_active = 1 order by lower(name);",
        (tenant_id,),
    )
    skills_rows = _fetch_all(
        "select person_name, skill_key from person_skills where tenant_id = ?;",
        (tenant_id,),
    )

    skill_map: Dict[str, Set[str]] = {}
    for r in skills_rows:
        nm = _normalize_text(r["person_name"])
        sk = str(r["skill_key"]).strip().lower()
        skill_map.setdefault(nm, set()).add(sk)

    out: List[Person] = []
    for r in people_rows:
        nm = _normalize_text(r["name"])
        dept = _normalize_text(r["department"])
        level = str(r["level"]).strip().lower()
        if level not in {"experienced", "fresher"}:
            level = "experienced"
        out.append(Person(name=nm, department=dept, skills=skill_map.get(nm, set()), level=level))
    return out

def list_people_records(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        "select name, department, level, is_active, created_at from people where tenant_id = ? order by lower(name);",
        (tenant_id,),
    )
    out: List[Dict[str, Any]] = []
    skill_rows = _fetch_all(
        "select person_name, skill_key from person_skills where tenant_id = ?;",
        (tenant_id,),
    )
    smap: Dict[str, List[str]] = {}
    for r in skill_rows:
        smap.setdefault(_normalize_text(r["person_name"]), []).append(str(r["skill_key"]).strip().lower())
    for r in rows:
        nm = _normalize_text(r["name"])
        out.append(
            {
                "name": nm,
                "department": _normalize_text(r["department"]),
                "skills": sorted(set(smap.get(nm, []))),
                "level": str(r["level"]).strip().lower(),
                "is_active": bool(int(r["is_active"])),
                "created_at": r["created_at"],
            }
        )
    return out


# ============================================================
# Users + auth (tenant-aware)
# ============================================================
def load_users(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        """
        select username, role, person_name, password_salt, password_iterations, password_hash, created_at, is_active
        from users
        where tenant_id = ?
        order by lower(username);
        """,
        (tenant_id,),
    )
    users = []
    for r in rows:
        users.append(
            {
                "username": r["username"],
                "role": r["role"],
                "person_name": r["person_name"],
                "password": {
                    "salt": r["password_salt"],
                    "iterations": r["password_iterations"],
                    "hash": r["password_hash"],
                },
                "created_at": r["created_at"],
                "is_active": bool(int(r["is_active"])),
            }
        )
    return {"users": users}

def find_user(username: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    username = _normalize_text(username).lower()
    row = _fetch_one(
        """
        select id, username, role, person_name, password_salt, password_iterations, password_hash, is_active
        from users
        where tenant_id = ? and lower(username) = ?
        limit 1;
        """,
        (tenant_id, username),
    )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "tenant_id": tenant_id,
        "username": row["username"],
        "role": row["role"],
        "person_name": row["person_name"],
        "password_salt": row["password_salt"],
        "password_iterations": row["password_iterations"],
        "password_hash": row["password_hash"],
        "is_active": bool(int(row["is_active"])),
    }

def authenticate(username: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Backward compatible: uses DEFAULT_TENANT_CODE.
    """
    return authenticate_tenant(DEFAULT_TENANT_CODE, username, password)

def authenticate_tenant(tenant_code: str, username: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    tenant_code = _normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE
    tenant_id = ensure_seed_files(tenant_code)

    u = find_user(username, tenant_id=tenant_id)
    if not u:
        return False, None, "Invalid username or password."
    if not u.get("is_active", True):
        return False, None, "User is disabled."

    ok = _verify_password_columns(
        password=password,
        salt_hex=u.get("password_salt"),
        iterations=u.get("password_iterations"),
        hash_hex=u.get("password_hash"),
    )
    if not ok:
        return False, None, "Invalid username or password."

    user = {
        "id": u["id"],
        "tenant_id": tenant_id,
        "tenant_code": tenant_code,
        "username": u["username"],
        "role": u["role"],
        "person_name": u["person_name"],
    }
    return True, user, "Login successful."


# ============================================================
# Password change (tenant-aware)
# ============================================================
def change_password(
    username: str,
    old_password: str,
    new_password: str,
    *,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    username = _normalize_text(username).lower()
    if not username:
        return False, "Username is required."
    if not old_password:
        return False, "Current password is required."
    if not new_password or len(new_password) < 6:
        return False, "New password must be at least 6 characters."

    u = find_user(username, tenant_id=tenant_id)
    if not u:
        return False, "User not found."
    if not u.get("is_active", True):
        return False, "User is disabled."

    ok_old = _verify_password_columns(
        password=old_password,
        salt_hex=u.get("password_salt"),
        iterations=u.get("password_iterations"),
        hash_hex=u.get("password_hash"),
    )
    if not ok_old:
        return False, "Current password is incorrect."

    pw = make_password_record(new_password)

    _execute(
        """
        update users
        set password_salt = ?, password_iterations = ?, password_hash = ?
        where tenant_id = ? and lower(username) = ?;
        """,
        (pw["salt"], int(pw["iterations"]), pw["hash"], tenant_id, username),
    )

    return True, "Password updated successfully."

def admin_reset_password(
    target_username: str,
    new_password: str,
    *,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    target_username = _normalize_text(target_username).lower()
    if not target_username:
        return False, "Target username is required."
    if not new_password or len(new_password) < 6:
        return False, "New password must be at least 6 characters."

    u = find_user(target_username, tenant_id=tenant_id)
    if not u:
        return False, "User not found."

    pw = make_password_record(new_password)

    _execute(
        """
        update users
        set password_salt = ?, password_iterations = ?, password_hash = ?
        where tenant_id = ? and lower(username) = ?;
        """,
        (pw["salt"], int(pw["iterations"]), pw["hash"], tenant_id, target_username),
    )

    return True, f"Password reset successfully for '{target_username}'."


# ============================================================
# State (busy auditors, audit_history) (tenant-aware)
# ============================================================
def load_state(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    _ensure_state_row(tenant_id)
    row = _fetch_one(
        "select busy_by_name_json, audit_history_json from audit_state where tenant_id = ?;",
        (tenant_id,),
    )
    busy = json.loads(row["busy_by_name_json"] or "{}") if row else {}
    hist = json.loads(row["audit_history_json"] or "[]") if row else []
    return {"busy_by_name": busy, "audit_history": hist}

def save_state(state: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    _ensure_state_row(tenant_id)
    busy_json = json.dumps(state.get("busy_by_name", {}) or {})
    hist_json = json.dumps(state.get("audit_history", []) or [])
    _execute(
        """
        update audit_state
        set busy_by_name_json = ?, audit_history_json = ?
        where tenant_id = ?;
        """,
        (busy_json, hist_json, tenant_id),
    )


# ============================================================
# Eligibility / assignment rules (tenant-aware)
# ============================================================
def is_busy(state: Dict[str, Any], person_name: str) -> bool:
    return person_name in state.get("busy_by_name", {})

def has_all_required_skills(person: Person, required_skills: Set[str]) -> bool:
    return required_skills.issubset(person.skills)

def eligible_people(
    people: List[Person],
    state: Dict[str, Any],
    target_dept: str,
    required_skills: Set[str],
    level: str,
) -> List[Person]:
    out: List[Person] = []
    for p in people:
        if p.level != level:
            continue
        if p.department.strip().lower() == target_dept.strip().lower():
            continue
        if is_busy(state, p.name):
            continue
        if not has_all_required_skills(p, required_skills):
            continue
        out.append(p)
    return out

def _new_audit_id() -> str:
    return str(uuid.uuid4())

def lock_auditor(state: Dict[str, Any], auditor_name: str, audit_id: str, target_dept: str, required_skills: Set[str], level: str) -> None:
    state["busy_by_name"][auditor_name] = {
        "audit_id": audit_id,
        "audited_department": target_dept,
        "required_skills": sorted(required_skills),
        "level": level,
        "started_at": _now_iso(),
        "status": "ongoing",
    }

def unlock_auditor(state: Dict[str, Any], auditor_name: str) -> None:
    if auditor_name in state.get("busy_by_name", {}):
        del state["busy_by_name"][auditor_name]


# ============================================================
# Audits (tenant-aware)
# ============================================================
def load_audits(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all(
        "select * from audits where tenant_id = ? order by created_at desc;",
        (tenant_id,),
    )
    audits: List[Dict[str, Any]] = []
    for r in rows:
        audits.append(
            {
                "audit_id": r["audit_id"],
                "title": r["title"] or "",
                "scope": r["scope"] or "",
                "audited_department": r["audited_department"],
                "required_skills": json.loads(r["required_skills_json"] or "[]"),
                "assigned_auditor": r["assigned_auditor"],
                "auditor_level": r["auditor_level"],
                "status": r["status"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
                "due_date": r["due_date"] or "",
                "reports": json.loads(r["reports_json"] or "[]"),
                "report_submitted_at": r["report_submitted_at"] or "",
                "closed_at": r["closed_at"] or "",
                "checklists": json.loads(r["checklists_json"] or "{}"),
            }
        )
    return {"audits": audits}

def save_audits(data: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    for a in data.get("audits", []):
        _save_updated_audit(a, tenant_id=tenant_id)

def list_audits(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return load_audits(tenant_id=tenant_id).get("audits", [])

def get_audit(audit_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    r = _fetch_one(
        "select * from audits where tenant_id = ? and audit_id = ? limit 1;",
        (tenant_id, audit_id),
    )
    if not r:
        return None
    return {
        "audit_id": r["audit_id"],
        "title": r["title"] or "",
        "scope": r["scope"] or "",
        "audited_department": r["audited_department"],
        "required_skills": json.loads(r["required_skills_json"] or "[]"),
        "assigned_auditor": r["assigned_auditor"],
        "auditor_level": r["auditor_level"],
        "status": r["status"],
        "created_by": r["created_by"],
        "created_at": r["created_at"],
        "due_date": r["due_date"] or "",
        "reports": json.loads(r["reports_json"] or "[]"),
        "report_submitted_at": r["report_submitted_at"] or "",
        "closed_at": r["closed_at"] or "",
        "checklists": json.loads(r["checklists_json"] or "{}"),
    }

def _save_updated_audit(updated: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    required_skills_json = json.dumps(updated.get("required_skills", []) or [])
    reports_json = json.dumps(updated.get("reports", []) or [])
    checklists_json = json.dumps(updated.get("checklists", {}) or {})

    exists = _fetch_one("select audit_id from audits where tenant_id = ? and audit_id = ?;", (tenant_id, updated.get("audit_id"),))
    if exists:
        _execute(
            """
            update audits set
              title = ?,
              scope = ?,
              audited_department = ?,
              required_skills_json = ?,
              assigned_auditor = ?,
              auditor_level = ?,
              status = ?,
              created_by = ?,
              created_at = ?,
              due_date = ?,
              reports_json = ?,
              report_submitted_at = ?,
              closed_at = ?,
              checklists_json = ?
            where audit_id = ? and tenant_id = ?;
            """,
            (
                updated.get("title", ""),
                updated.get("scope", ""),
                updated.get("audited_department", ""),
                required_skills_json,
                updated.get("assigned_auditor", ""),
                updated.get("auditor_level", ""),
                updated.get("status", ""),
                updated.get("created_by", ""),
                updated.get("created_at", _now_iso()),
                updated.get("due_date", ""),
                reports_json,
                updated.get("report_submitted_at", ""),
                updated.get("closed_at", ""),
                checklists_json,
                updated.get("audit_id", ""),
                tenant_id,
            ),
        )
        return

    _execute(
        """
        insert into audits
        (audit_id, tenant_id, title, scope, audited_department, required_skills_json,
         assigned_auditor, auditor_level, status, created_by, created_at, due_date,
         reports_json, report_submitted_at, closed_at, checklists_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            updated.get("audit_id", _new_audit_id()),
            tenant_id,
            updated.get("title", ""),
            updated.get("scope", ""),
            updated.get("audited_department", ""),
            required_skills_json,
            updated.get("assigned_auditor", ""),
            updated.get("auditor_level", ""),
            updated.get("status", "Assigned"),
            updated.get("created_by", ""),
            updated.get("created_at", _now_iso()),
            updated.get("due_date", ""),
            reports_json,
            updated.get("report_submitted_at", ""),
            updated.get("closed_at", ""),
            checklists_json,
        ),
    )

def create_and_assign_audit(
    created_by: str,
    target_dept: str,
    allow_fresher_fallback: bool,
    title: str = "",
    scope: str = "",
    due_date: str = "",
    required_skill_keys_override: Optional[Set[str]] = None,
    save_required_skills_as_default: bool = False,
    tenant_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    target_dept = _normalize_text(target_dept)
    if not target_dept:
        return None, "Department is required."

    add_department_to_catalog(target_dept, tenant_id=tenant_id)

    if required_skill_keys_override is not None:
        required_skills = set(str(k).strip().lower() for k in required_skill_keys_override if str(k).strip())
        for k in list(required_skills):
            ensure_skill_key_exists(k, fallback_label=k, tenant_id=tenant_id)
        if save_required_skills_as_default:
            set_dept_required_skills(target_dept, sorted(required_skills), tenant_id=tenant_id)
    else:
        required_skills = get_required_skills_for_dept(target_dept, tenant_id=tenant_id)

    if not required_skills and target_dept.lower() != "mr":
        return None, "No required skills defined for this department. Enter required skills (or save them as default)."

    people = load_people(tenant_id=tenant_id)
    state = load_state(tenant_id=tenant_id)

    experienced = eligible_people(people, state, target_dept, required_skills, level="experienced")
    chosen: Optional[Person] = None

    if experienced:
        chosen = sorted(experienced, key=lambda p: p.name.lower())[0]
    else:
        if allow_fresher_fallback:
            freshers = eligible_people(people, state, target_dept, required_skills, level="fresher")
            if freshers:
                chosen = sorted(freshers, key=lambda p: p.name.lower())[0]

    if chosen is None:
        return None, "No eligible auditor available (busy, department conflict, or missing mandatory skills)."

    audit_id = _new_audit_id()
    audit = {
        "audit_id": audit_id,
        "title": title.strip(),
        "scope": scope.strip(),
        "audited_department": target_dept,
        "required_skills": sorted(required_skills),
        "assigned_auditor": chosen.name,
        "auditor_level": chosen.level,
        "status": "Assigned",
        "created_by": created_by,
        "created_at": _now_iso(),
        "due_date": due_date.strip(),
        "reports": [],
        "report_submitted_at": "",
        "closed_at": "",
        "checklists": {},
        "checklist_extras": {},
    }

    _save_updated_audit(audit, tenant_id=tenant_id)

    lock_auditor(state, chosen.name, audit_id, target_dept, required_skills, chosen.level)
    save_state(state, tenant_id=tenant_id)

    return audit, f"Assigned {chosen.name} to audit '{target_dept}'."

def set_audit_status(audit_id: str, new_status: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    allowed = {"Assigned", "In Progress", "Report Submitted", "Closed"}
    if new_status not in allowed:
        return False, f"Invalid status: {new_status}"

    current = a.get("status") or "Assigned"

    if new_status == "Report Submitted":
        if current != "In Progress":
            return False, "Can set 'Report Submitted' only from 'In Progress'."
        if not a.get("reports"):
            return False, "Cannot submit without uploading at least one report."
        ok, msg = _validate_checklist_complete(a, tenant_id=tenant_id)
        if not ok:
            return False, msg

    if new_status == "Closed":
        if current != "Report Submitted":
            return False, "Can close audit only after 'Report Submitted'."
        if not a.get("reports"):
            return False, "Cannot complete audit without uploading report."

    if current == "Closed" and new_status != "Closed":
        return False, "Closed audit cannot be reopened."

    a["status"] = new_status
    if new_status == "Report Submitted" and not a.get("report_submitted_at"):
        a["report_submitted_at"] = _now_iso()
    if new_status == "Closed" and not a.get("closed_at"):
        a["closed_at"] = _now_iso()

    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Status updated."

def _validate_checklist_complete(audit: Dict[str, Any], tenant_id: str) -> Tuple[bool, str]:
    dept = _normalize_text(audit.get("audited_department", ""))
    if not dept:
        return False, "Audit department is missing."

    sections = get_sections_for_department(dept, tenant_id=tenant_id)
    if not sections:
        return False, f"Checklist is not configured for department '{dept}'. Ask Admin to create checklist sections."

    saved = (audit.get("checklists") or {}).get(dept, {})
    if not isinstance(saved, dict):
        saved = {}

    missing_sections: List[str] = []
    incomplete_examples: List[str] = []

    for sec in sections:
        expected_items = get_items_for_department_section(dept, sec, tenant_id=tenant_id)
        expected_items = [str(x).strip() for x in expected_items if str(x).strip()]

        extras = get_checklist_extras(audit, dept, sec)
        if extras:
            expected_items = expected_items + extras

        _seen = set()
        _deduped = []
        for it in expected_items:
            k = str(it).strip().lower()
            if k and k not in _seen:
                _seen.add(k)
                _deduped.append(str(it).strip())
        expected_items = _deduped

        if not expected_items:
            return False, f"Checklist section '{sec}' for department '{dept}' has no items. Ask Admin to configure it."

        rows = saved.get(sec)
        if not rows:
            missing_sections.append(sec)
            continue

        try:
            rows_sorted = sorted(rows, key=lambda r: int(str(r.get("sr_no", "0")).strip() or 0))
        except Exception:
            rows_sorted = list(rows)

        if len(rows_sorted) < len(expected_items):
            incomplete_examples.append(f"{sec} (missing rows)")
            continue

        for idx in range(len(expected_items)):
            r = rows_sorted[idx] if idx < len(expected_items) else {}
            obs = _normalize_text(r.get("observation", ""))
            evd = _normalize_text(r.get("evidence", ""))
            if not obs or not evd:
                sr = str(r.get("sr_no", idx + 1)).strip() or str(idx + 1)
                incomplete_examples.append(f"{sec} (SR {sr})")
                break

    if missing_sections:
        return False, "Checklist incomplete. No saved responses for sections: " + ", ".join(missing_sections)

    if incomplete_examples:
        sample = ", ".join(incomplete_examples[:5])
        more = "" if len(incomplete_examples) <= 5 else f" (+{len(incomplete_examples) - 5} more)"
        return False, f"Checklist incomplete. Fill Observation and Evidence for every row. Incomplete examples: {sample}{more}"

    return True, "Checklist complete."

def submit_report(audit_id: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name:
        return False, "You are not assigned to this audit."
    if a.get("status") != "In Progress":
        return False, "Report can be submitted only when the audit is 'In Progress'."
    if not a.get("reports"):
        return False, "Please upload at least one report file before submitting."

    ok_chk, msg_chk = validate_audit_checklists_complete(audit_id, tenant_id=tenant_id)
    if not ok_chk:
        return False, msg_chk

    ok, msg = _validate_checklist_complete(a, tenant_id=tenant_id)
    if not ok:
        return False, msg

    a["status"] = "Report Submitted"
    a["report_submitted_at"] = _now_iso()
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Report submitted."

def complete_audit(audit_id: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name:
        return False, "You are not assigned to this audit."
    if not a.get("reports"):
        return False, "Cannot complete audit without uploading report."
    if a.get("status") != "Report Submitted":
        return False, "Audit can be completed only after 'Report Submitted'."

    a["status"] = "Closed"
    a["closed_at"] = _now_iso()
    _save_updated_audit(a, tenant_id=tenant_id)

    state = load_state(tenant_id=tenant_id)
    unlock_auditor(state, auditor_name)
    state["audit_history"].append(
        {
            "audit_id": a.get("audit_id"),
            "auditor_name": auditor_name,
            "audited_department": a.get("audited_department"),
            "required_skills": a.get("required_skills", []),
            "completed_at": a.get("closed_at"),
            "status": "completed",
        }
    )
    save_state(state, tenant_id=tenant_id)

    return True, "Audit completed and auditor unlocked."


# ============================================================
# Final Generated Reports: register/list/get/delete (tenant-aware)
# ============================================================
def register_final_generated_report(
    *,
    created_by: str,
    pdf_rel_path: str,
    tenant_id: Optional[str] = None,
    # Newer/older callers may use either name:
    included_audit_ids: Optional[List[str]] = None,
    audit_ids: Optional[List[str]] = None,
    # App/admin summary fields:
    summary: str = "",
    admin_summaries_by_audit_id: Optional[Dict[str, str]] = None,
    # Access control. If None, defaults to "ALL_AUDITORS" behaviour via list_final_generated_reports_for_user().
    allowed_users: Optional[List[str]] = None,
    **_ignored_kwargs,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Register a final generated report (PDF already created by report_generator).

    Backwards/forwards compatible with multiple calling conventions:
      - report_generator.py may call with:
          included_audit_ids=[...], admin_summaries_by_audit_id={...}
      - other callers may call with:
          audit_ids=[...], summary="..."

    Visibility requirement (current project):
      - Any generated final report must be visible to *all auditors* (and admin).
      - Only admin can delete final reports.

    Notes:
      - We store the per-audit admin summaries (if provided) inside the 'summary' field as JSON,
        while preserving a plain summary string if you use that.
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    created_by = _normalize_text(created_by)
    if not created_by:
        return False, None, "created_by is required."

    # Accept either parameter name
    ids = audit_ids if audit_ids is not None else included_audit_ids
    audit_ids_clean = [str(x or "").strip() for x in (ids or []) if str(x or "").strip()]
    audit_ids_clean = list(dict.fromkeys(audit_ids_clean))
    if not audit_ids_clean:
        return False, None, "At least one audit must be selected."

    # Validate audits exist for this tenant
    rows = _fetch_all(
        "select audit_id from audits where tenant_id = ? and audit_id in ({})".format(",".join(["?"] * len(audit_ids_clean))),
        tuple([tenant_id] + audit_ids_clean),
    )
    found = {str(r["audit_id"]) for r in rows}
    missing = [a for a in audit_ids_clean if a not in found]
    if missing:
        return False, None, f"Invalid audit IDs: {missing}"

    # Validate PDF path is safe and exists
    try:
        pdf_rel_path = _safe_relpath_under_tenant(tenant_id, pdf_rel_path)
        abs_path = resolve_final_report_pdf_abs_path(tenant_id, pdf_rel_path)
    except Exception as e:
        return False, None, f"Invalid PDF path: {e}"

    if not os.path.exists(abs_path):
        return False, None, "PDF file not found on disk. Generate the PDF first, then register."

    # Store summary. If per-audit summaries are provided, store as JSON for later parsing.
    stored_summary = _normalize_text(summary)
    if admin_summaries_by_audit_id:
        payload = {
            "summary": stored_summary,
            "admin_summaries_by_audit_id": {str(k): str(v) for k, v in admin_summaries_by_audit_id.items()},
        }
        stored_summary = json.dumps(payload, ensure_ascii=False)

    # allowed_users is kept for compatibility, but auditors see all reports anyway.
    # If someone still wants to constrain, they can pass allowed_users and your app can enforce it.
    allowed_users = _normalize_users_list(allowed_users or ["ALL_AUDITORS"])

    report_id = _uuid()
    row = {
        "id": report_id,
        "tenant_id": tenant_id,
        "created_by": created_by,
        "created_at": _now_iso(),
        "summary": stored_summary,
        "audit_ids_json": json.dumps(audit_ids_clean),
        "allowed_users_json": json.dumps(allowed_users),
        "pdf_rel_path": pdf_rel_path,
        "is_deleted": 0,
        "deleted_at": None,
        "deleted_by": None,
    }

    _execute(
        """
        insert into generated_final_reports
        (id, tenant_id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path, is_deleted, deleted_at, deleted_by)
        values (?, ?, ?, ?, ?, ?, ?, ?, 0, null, null);
        """,
        (
            row["id"], row["tenant_id"], row["created_by"], row["created_at"], row["summary"],
            row["audit_ids_json"], row["allowed_users_json"], row["pdf_rel_path"],
        ),
    )

    return True, row, "Final report registered."

def list_final_generated_reports_for_user(
    username: str,
    role: str,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Visibility rules:
      - Admin: sees all non-deleted final reports.
      - Auditor: sees all non-deleted final reports (requirement: visible to all auditors).
      - Manager: also sees all non-deleted final reports.

    Only admin can delete (enforced in delete_final_generated_report()).
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    username = _normalize_text(username)
    role = str(role or "").strip().lower()

    rows = _fetch_all(
        """
        select id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path
        from generated_final_reports
        where tenant_id = ? and is_deleted = 0
        order by created_at desc;
        """,
        (tenant_id,),
    )

    out: List[Dict[str, Any]] = []
    for r in rows:
        allowed = []
        try:
            allowed = json.loads(r.get("allowed_users_json") or "[]")
        except Exception:
            allowed = []

        # Current requirement: show to all auditors and admin/manager
        if role in {"admin", "auditor", "manager"}:
            out.append(
                {
                    "id": r["id"],
                    "created_by": r["created_by"],
                    "created_at": r["created_at"],
                    "summary": r["summary"],
                    "audit_ids": json.loads(r.get("audit_ids_json") or "[]"),
                    "allowed_users": allowed,
                    "pdf_rel_path": r["pdf_rel_path"],
                }
            )
            continue

        # Fallback (if you ever add more roles later)
        allowed_norm = {str(x).strip().lower() for x in (allowed or []) if str(x).strip()}
        if username and username.lower() in allowed_norm:
            out.append(
                {
                    "id": r["id"],
                    "created_by": r["created_by"],
                    "created_at": r["created_at"],
                    "summary": r["summary"],
                    "audit_ids": json.loads(r.get("audit_ids_json") or "[]"),
                    "allowed_users": allowed,
                    "pdf_rel_path": r["pdf_rel_path"],
                }
            )

    return out

def get_final_generated_report(
    report_id: str,
    username: str,
    role: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    report_id = str(report_id or "").strip()
    if not report_id:
        return None

    r = _fetch_one(
        """
        select id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path, is_deleted
        from generated_final_reports
        where tenant_id = ? and id = ?
        limit 1;
        """,
        (tenant_id, report_id),
    )
    if not r or int(r.get("is_deleted") or 0) == 1:
        return None

    role = str(role or "").strip().lower()
    username = _normalize_text(username)

    allowed = []
    try:
        allowed = json.loads(r.get("allowed_users_json") or "[]")
    except Exception:
        allowed = []
    allowed_norm = {str(x).strip().lower() for x in (allowed or []) if str(x).strip()}

    if role not in {"admin", "auditor", "manager"} and (not username or username.lower() not in allowed_norm):
        return None

    return {
        "id": r["id"],
        "created_by": r["created_by"],
        "created_at": r["created_at"],
        "summary": r["summary"],
        "audit_ids": json.loads(r.get("audit_ids_json") or "[]"),
        "allowed_users": allowed,
        "pdf_rel_path": r["pdf_rel_path"],
    }


def delete_final_generated_report(
    report_id: str,
    requester_role: str,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Admin-only delete.
    - marks record deleted
    - attempts to delete PDF file from disk
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    requester_role = str(requester_role or "").strip().lower()

    if requester_role != "admin":
        return False, "Only admin can delete final reports."

    report_id = str(report_id or "").strip()
    if not report_id:
        return False, "report_id is required."

    r = _fetch_one(
        """
        select id, pdf_rel_path, is_deleted
        from generated_final_reports
        where tenant_id = ? and id = ?
        limit 1;
        """,
        (tenant_id, report_id),
    )
    if not r:
        return False, "Final report not found."
    if int(r.get("is_deleted") or 0) == 1:
        return False, "Final report already deleted."

    pdf_rel_path = str(r.get("pdf_rel_path") or "")
    abs_path = None
    try:
        abs_path = resolve_final_report_pdf_abs_path(tenant_id, pdf_rel_path)
    except Exception:
        abs_path = None

    _execute(
        """
        update generated_final_reports
        set is_deleted = 1, deleted_at = ?, deleted_by = ?
        where tenant_id = ? and id = ?;
        """,
        (_now_iso(), "admin", tenant_id, report_id),
    )

    # best-effort file deletion
    if abs_path and os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except Exception:
            pass

    return True, "Final report deleted."


# ============================================================
# Checklist responses (stored per audit in audits table JSON)
# ============================================================
def save_audit_section_table(
    audit_id: str,
    dept: str,
    section: str,
    rows: List[Dict[str, str]],
    auditor_name: Optional[str] = None,
    tenant_id: Optional[str] = None
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    if not audit_id or not dept or not section:
        return False, "audit_id, dept, and section are required."

    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    if auditor_name is not None:
        if a.get("assigned_auditor") != auditor_name:
            return False, "You are not assigned to this audit."
        if a.get("status") != "In Progress":
            return False, "Checklist can be edited only when the audit is 'In Progress'."

    a.setdefault("checklists", {})
    if dept not in a["checklists"]:
        a["checklists"][dept] = {}
    a["checklists"][dept][section] = rows

    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Checklist saved."

def load_audit_section_table(
    audit_id: str,
    dept: str,
    section: str,
    tenant_id: Optional[str] = None
) -> Optional[List[Dict[str, str]]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return None
    return a.get("checklists", {}).get(dept, {}).get(section)

def add_audit_section_checklist_item(
    audit_id: str,
    dept: str,
    section: str,
    checklist_text: str,
    auditor_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    section = _normalize_text(section)
    checklist_text = (checklist_text or "").strip()
    if not checklist_text:
        return False, "Checklist point is required."

    existing = load_audit_section_table(audit_id, dept, section, tenant_id=tenant_id) or []
    if existing:
        rows = list(existing)
    else:
        items = get_items_for_department_section(dept, section, tenant_id=tenant_id)
        rows = []
        for i, item in enumerate(items, start=1):
            rows.append(
                {
                    "sr_no": str(i),
                    "checklist": str(item).strip(),
                    "observation": "",
                    "evidence": "",
                }
            )

    next_sr = str(len(rows) + 1)
    rows.append(
        {
            "sr_no": next_sr,
            "checklist": checklist_text,
            "observation": "",
            "evidence": "",
        }
    )

    return save_audit_section_table(
        audit_id=audit_id,
        dept=dept,
        section=section,
        rows=rows,
        auditor_name=auditor_name,
        tenant_id=tenant_id,
    )

def validate_audit_checklists_complete(
    audit_id: str,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."

    checklists = a.get("checklists") or {}
    if not isinstance(checklists, dict) or not checklists:
        return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."

    any_rows = False
    for dept, sec_map in (checklists or {}).items():
        if not isinstance(sec_map, dict):
            continue
        for section, rows in sec_map.items():
            if not rows:
                continue
            any_rows = True
            for r in rows:
                obs = str((r or {}).get("observation", "")).strip()
                evd = str((r or {}).get("evidence", "")).strip()
                chk = str((r or {}).get("checklist", "")).strip()
                if not chk:
                    return False, "Checklist has an empty point. Please remove or fill it before submitting."
                if not obs or not evd:
                    return False, "Checklist incomplete. Please fill Observation and Evidence for all points before submitting."

    if not any_rows:
        return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."

    return True, "Checklist complete."


# ============================================================
# Admin: add/delete auditors (tenant-aware)
# ============================================================
def add_auditor(
    name: str,
    department: str,
    level: str,
    skills: Set[str],
    password: str = "auditor123",
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)

    name = _normalize_text(name)
    department = _normalize_text(department)
    level = str(level).strip().lower()

    if not name:
        return False, "Name is required."
    if not department:
        return False, "Department is required."
    if level not in {"experienced", "fresher"}:
        return False, "Invalid level. Use 'experienced' or 'fresher'."
    if not skills:
        return False, "At least one skill is required."

    add_department_to_catalog(department, tenant_id=tenant_id)

    cleaned_skills: Set[str] = set()
    for k in skills:
        kk = str(k).strip().lower()
        if not kk:
            continue
        kk = ensure_skill_key_exists(kk, fallback_label=kk, tenant_id=tenant_id)
        cleaned_skills.add(kk)

    if not cleaned_skills:
        return False, "At least one valid skill is required."

    existing_person = _fetch_one(
        "select name from people where tenant_id = ? and lower(name) = ? limit 1;",
        (tenant_id, name.lower()),
    )
    if existing_person:
        return False, "Auditor with this name already exists."

    _execute(
        """
        insert into people (id, tenant_id, name, department, level, is_active, created_at)
        values (?, ?, ?, ?, ?, 1, ?);
        """,
        (_uuid(), tenant_id, name, department, level, _now_iso()),
    )

    for kk in sorted(cleaned_skills):
        _execute(
            """
            insert or ignore into person_skills (id, tenant_id, person_name, skill_key)
            values (?, ?, ?, ?);
            """,
            (_uuid(), tenant_id, name, kk),
        )

    uname = _normalize_username(name)
    user_exists = _fetch_one(
        "select id from users where tenant_id = ? and lower(username) = ? limit 1;",
        (tenant_id, uname.lower()),
    )
    if user_exists:
        return True, f"Auditor added. Login already existed for username '{uname}'."

    pw = make_password_record(password)
    _execute(
        """
        insert into users
        (id, tenant_id, username, role, person_name, password_salt, password_iterations, password_hash, is_active, created_at)
        values (?, ?, ?, 'auditor', ?, ?, ?, ?, 1, ?);
        """,
        (_uuid(), tenant_id, uname, name, pw["salt"], int(pw["iterations"]), pw["hash"], _now_iso()),
    )

    return True, f"Auditor added successfully. Username: {uname} | Password: {password}"

def delete_auditor(name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    name = _normalize_text(name)
    if not name:
        return False, "Name is required."

    state = load_state(tenant_id=tenant_id)
    if is_busy(state, name):
        return False, "Cannot delete. Auditor is locked in an ongoing audit."

    person_exists = _fetch_one(
        "select name from people where tenant_id = ? and lower(name) = ? limit 1;",
        (tenant_id, name.lower()),
    )
    if not person_exists:
        return False, "Auditor not found."

    _execute("delete from person_skills where tenant_id = ? and lower(person_name) = ?;", (tenant_id, name.lower()))
    _execute("delete from people where tenant_id = ? and lower(name) = ?;", (tenant_id, name.lower()))

    _execute(
        "delete from users where tenant_id = ? and role = 'auditor' and lower(person_name) = ?;",
        (tenant_id, name.lower()),
    )

    return True, "Auditor deleted successfully."


# ============================================================
# UI helper: show Audit Title instead of Audit ID (tenant-aware)
# ============================================================
def _build_audit_display_title(a: Dict[str, Any]) -> str:
    title = _normalize_text(a.get("title", ""))
    if not title:
        title = _normalize_text(a.get("audit_title", ""))

    dept = _normalize_text(a.get("audited_department", ""))
    status = _normalize_text(a.get("status", ""))
    due = _normalize_text(a.get("due_date", ""))
    auditor = _normalize_text(a.get("assigned_auditor", ""))

    if title:
        label = title
    else:
        aid = str(a.get("audit_id", "") or "")
        prefix = aid[:8] if aid else "unknown"
        label = f"{dept or 'Audit'} | {prefix}"

    extras: List[str] = []
    if dept and (dept.lower() not in label.lower()):
        extras.append(dept)
    if status:
        extras.append(status)
    if due:
        extras.append(f"Due: {due}")
    if auditor:
        extras.append(f"Auditor: {auditor}")

    if extras:
        return f"{label}  ({' | '.join(extras)})"
    return label

def get_audit_dropdown_options(tenant_id: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    audits = list_audits(tenant_id=tenant_id)

    labels: List[str] = []
    label_to_id: Dict[str, str] = {}
    seen: Dict[str, int] = {}

    for a in audits:
        audit_id = str(a.get("audit_id", "") or "").strip()
        if not audit_id:
            continue

        base = _build_audit_display_title(a)
        key = base

        if key in seen:
            seen[key] += 1
            key = f"{base} [{seen[base]}]"
        else:
            seen[key] = 1

        labels.append(key)
        label_to_id[key] = audit_id

    labels.sort(key=lambda x: x.lower())
    return labels, label_to_id
