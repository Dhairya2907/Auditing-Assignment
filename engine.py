from __future__ import annotations

import os, re, json, uuid, hashlib, hmac, sqlite3, base64, zlib
def _d(s:str)->str: return zlib.decompress(base64.b64decode(s)).decode('utf-8')

try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Set, Optional, Tuple


class AttrDict(dict):
    def __getattr__(self, name):
        try: return self[name]
        except KeyError as e: raise AttributeError(name) from e
    def __setattr__(self, name, value): self[name] = value
    def __delattr__(self, name):
        try: del self[name]
        except KeyError as e: raise AttributeError(name) from e


def _parse_iso_date(val) -> Optional[date]:
    if val is None: return None
    if isinstance(val, datetime): return val.date()
    if isinstance(val, date): return val
    if isinstance(val, str):
        s = val.strip()
        if not s: return None
        try: return date.fromisoformat(s[:10])
        except Exception: return None
    return None


UPLOADS_DIR = "uploads"
DEFAULT_TENANT_CODE = os.getenv("DEFAULT_TENANT_CODE", "default")
DEFAULT_DEPARTMENTS = ["HR", "MR", "Purchase", "Sales and Marketing", "Production"]
DEFAULT_SKILLS = {
    "hr_competency_training_requirements": "Understanding of competency and training requirements",
    "hr_review_training_records_effectiveness": "Ability to review training records and effectiveness",
    "hr_personnel_regulatory_awareness": "Awareness of regulatory requirements related to personnel",
    "pur_supplier_selection_evaluation": "Understanding of supplier selection and evaluation criteria",
    "pur_incoming_inspection_linkage": "Ability to assess incoming inspection linkage with purchasing",
    "pur_supplier_agreements_quality_clauses": "Awareness of supplier agreements and quality clauses",
    "sm_labeling_claims_control": "Knowledge of labelling and claims control",
    "sm_customer_communication_feedback": "Skill in reviewing customer communication and feedback",
    "sm_complaint_intake_escalation": "Awareness of complaint intake and escalation",
}
DEFAULT_DEPT_REQUIRED_SKILLS = {
    "HR": ["hr_competency_training_requirements", "hr_review_training_records_effectiveness", "hr_personnel_regulatory_awareness"],
    "Purchase": ["pur_supplier_selection_evaluation", "pur_incoming_inspection_linkage", "pur_supplier_agreements_quality_clauses"],
    "Sales and Marketing": ["sm_labeling_claims_control", "sm_customer_communication_feedback", "sm_complaint_intake_escalation"],
    "MR": [],
}


@dataclass(frozen=True)
class Person:
    name: str
    department: str
    skills: Set[str]
    level: str


# ── Utilities ─────────────────────────────────────────────────────────────────
def _now_iso() -> str: return datetime.now().isoformat(timespec="seconds")
def _uuid() -> str: return str(uuid.uuid4())
def _normalize_username(name: str) -> str: return name.strip().lower().replace(" ", "")
def _normalize_text(s: str) -> str: return " ".join(str(s or "").strip().split())
def _new_audit_id() -> str: return str(uuid.uuid4())

def ensure_dirs() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    db_dir = os.path.dirname(SQLITE_DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

def _tenant_root_dir(tenant_id: str) -> str:
    return os.path.join(UPLOADS_DIR, "tenants", str(tenant_id))

def _tenant_generated_reports_dir(tenant_id: str) -> str:
    d = os.path.join(_tenant_root_dir(tenant_id), "generated_reports")
    os.makedirs(d, exist_ok=True)
    return d

# ── Password helpers ──────────────────────────────────────────────────────────
def _pbkdf2_hash(password: str, salt_hex: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations).hex()

def make_password_record(password: str) -> Dict[str, Any]:
    salt = os.urandom(16).hex()
    iterations = 150_000
    return {"salt": salt, "iterations": iterations, "hash": _pbkdf2_hash(password, salt, iterations)}

def verify_password(password: str, rec: Dict[str, Any]) -> bool:
    salt, it, expected = rec.get("salt", ""), int(rec.get("iterations", 150_000)), rec.get("hash", "")
    if not salt or not expected: return False
    return hmac.compare_digest(_pbkdf2_hash(password, salt, it), expected)

def _verify_password_columns(password: str, salt_hex: str, iterations: int, hash_hex: str) -> bool:
    if not salt_hex or not hash_hex: return False
    try: iterations = int(iterations)
    except Exception: return False
    return hmac.compare_digest(_pbkdf2_hash(password, salt_hex, iterations), hash_hex)

# ── Database config ───────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join("data", "app.db"))

def _pg_url_with_ssl(url: str) -> str:
    u = (url or "").strip()
    if not u or "sslmode=" in u: return u
    return u + ("&" if "?" in u else "?") + "sslmode=require"

def _ph() -> str: return "%s" if USE_POSTGRES else "?"
def _sql(q: str) -> str: return q.replace("?", "%s") if USE_POSTGRES else q
def _placeholders(n: int) -> str: return ",".join([_ph()] * int(n))

def _connect():
    if USE_POSTGRES:
        if psycopg2 is None:
            raise RuntimeError("Postgres requested but psycopg2 is not installed. Add psycopg2-binary to requirements.txt.")
        conn = psycopg2.connect(_pg_url_with_ssl(DATABASE_URL), connect_timeout=15)
        conn.autocommit = True
        return conn
    ensure_dirs()
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in ["PRAGMA journal_mode=WAL;", "PRAGMA synchronous=NORMAL;", "PRAGMA foreign_keys=ON;", "PRAGMA busy_timeout=30000;"]:
        conn.execute(pragma)
    return conn

def _fetch_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    q = _sql(sql)
    with _connect() as conn:
        if USE_POSTGRES:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(q, params)
                row = cur.fetchone()
                return dict(row) if row else None
        row = conn.execute(q, params).fetchone()
        return dict(row) if row else None

def _fetch_all(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    q = _sql(sql)
    with _connect() as conn:
        if USE_POSTGRES:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(q, params)
                return [dict(r) for r in cur.fetchall()]
        return [dict(r) for r in conn.execute(q, params).fetchall()]

def _execute(sql: str, params: Tuple[Any, ...] = ()) -> int:
    q = _sql(sql)
    with _connect() as conn:
        if USE_POSTGRES:
            with conn.cursor() as cur:
                cur.execute(q, params)
                return cur.rowcount
        return conn.execute(q, params).rowcount

def _executescript(script: str) -> None:
    if not script or not str(script).strip(): return
    if not USE_POSTGRES:
        with _connect() as conn: conn.executescript(script)
        return
    statements = [s.strip() for s in str(script).split(";") if s.strip()]
    with _connect() as conn:
        with conn.cursor() as cur:
            for st in statements: cur.execute(st)

def _table_columns(table: str) -> Set[str]:
    if USE_POSTGRES:
        rows = _fetch_all("select column_name as name from information_schema.columns where table_schema='public' and table_name = ?", (table,))
    else:
        rows = _fetch_all(f"PRAGMA table_info({table})", ())
    return {str(r.get("name")) for r in rows if r.get("name")}

def _ensure_column(table: str, col_name: str, col_def_sql: str) -> None:
    if col_name not in _table_columns(table):
        _execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def_sql}")

# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = _d("eNrFV82S2yAMvucpuMWZyc60505vne210xdgiJETGgxewJvk7Ssgdoj/Jj+73r1sLIEkPn2SYJEbYA6IYxsJRBREaUfgKKyzxIFiCv9nC0IEx8+jI5URJTMnsofTGsVxCc01h6j321UtJamVeKvBr1Gs7Ci9NPrllLnORg4Fq6UjGUe9EyVkS6UPy9VqsfqxWEyEW1swtwTbaNNo/N7hOI2W3aPlO8j3JAsaoUi2ZLwUarlelkyxLRj8xWounDYYtbdRYWBa0dZBkDFrD9pwapl0fbetWjgwzAmtLPpygOaH1+2Y3fXNCEtZ7sQ79Da3OH9/LBsBtZBjkrXArlsgg77QBsRWefyTRStioAADKoeWY5kXa4XuJGB6c2ZzxsFn/JxwoTgcOwkX/EhD0mm04g2E78TXNGU4VMy4Em5j+RBxPorcI3DOCWUCRgJoIr0ZVrsXUlqaM8ek3j6IbDBC/XlHVJJtQH4i9m0AcyXgDNsF+2sc72G1owbeamEQh2jkwSRcsk+HmT6RpQFIO+a+AGOPDUJzTfAeWjdDXYGuUPiRveOCUV8n4b1L+WYaRVUYR3DEgSM8XhxHUWHA7qAZRbMPhDk7WMxGktsouCObYU4/VTHdWf9EtSSmvqBSovdeT7rC6GZkw30oQhp+0vuBdcLJy/XJ5rq6fAWbyNap2umUOP2Hx+ivwusU4uqJH29wAyuigg7UYgjMMVfb8bG0Od0+skI7qIHyAOv5rAYqbdxY/FFLbb0phUtsBjdS247E9w7pMzRibgaeRWokDIuC+6hFPeyxD3co1CHYprYnzEEoqjEKBIM7NK7N6RNxmTpUkpjnblFTFWEh9w+LgVeDg5LiowKnw9CbI6jDpvtm/rrxuE48zNXO8t0+4Vgf32u+vbyQn0/8+f2vQjFJfoPy7zfg5G+sW5KVOD7FS2AZ+fPrdfW0swkebRv3tPDhUNME8RCZHu1hti6Dh5FSE3y0G0upD2g0vvKG11S8wGNJWjE3/ACOVOHjF55vsVDCqrQ7NqLzcWciakhU0+QvjB3J5BVt77F8zhebNH5JKlr/D90QWS8=")
_SCHEMA_PG = _d("eNrFWNuS2jAMfecr/AbM0C/oU7/EI2IBLo6d2k6BdvrvlW3I1aHJ7rJ92mA5knXOsaTsqrAIHpmHvUImD0wbz/AqnXfMowZNfzcrxqSgn1fPKitLsDd2xtuOltMWXhiByR5e17VSrNbyR41hj4ZyYAyrKa7g4JmXJToPZeV/te8LPECtwjuXzXa1/bpaPTlp7dDOOefD2kSxeECLusAm240UW2Y0xVdI0QpwBYiYRwiSz8UaNUy/OGFxZptokZpt1iBKqde7dQkajmjpCWohvbHr7Tb4qCgDo3kTIK6BcxdjBXdASIzCNmbp0YKXRjuK5ZHc5/edwJ3GbqTjUHj5E9ne0HFBj0nwNlG5iLSIWVQB2zT47xoYI6l3TqUWeB1wKsWVR155ejmQEn+3zv6hCoEVWF/iPA2/SxsfoPEJuOZC1Um2A1hndTZs7iyVcrwAD8ocX41cjMbJ4Ri+ZFKwR/UabJvYcwC+w9Ji28dpiSo9t/ijlpaOn5y8GuRWBjyv1CcsZHAbuFsIZACA8u+rdATJbDwrNBUt/pcL3gIxtin8OdTtoyskU2wLeKXCL8MhBLWEg0V3wkdL+OTCPLfSJMA79KWFBYTFTvc5yh+21XeovuNqoeLTm6MC0gNiNnxxbEi4xUf+QvS89KodR1xhqvZXDE6Se3YHBneaf6d8x7toPJFHHdSbJqLMjmTgmTsVD+bB1266R+xvH9A/RI1cRFLuAFisjPVTSSUrd/W+lH4cKB5BGZc3hDKhAtsZ5zP0liTSUVpaWCYxHlBNdXUgpY7QFqlpX7sbcRFv0JQUYuQTncLY20Tyz07eQe6T5pdn8ndYhKk8M3J7LDlN5DSo5wb2aI4vLevGu0fEXSfCnAJVnM4dtYxBnK2cI+rwKUKqPkgNit/vyKtJ+NCL7uoynm9CnFJM1jGlzIUipa+W/J5KHAgUxSvw+U+xlJyYbvkHUO6uvLgzUz8eljscMwQQ2XoUtFYJE3T25LDE850LeOq8JSyI7csX9i3gTnQr1AIsAy1YpUBrqY//rmLNay+WYNsq+yWg6ZnDjkXNoWknPRsdd8LyYTKf20Ma9Ia9pDEs7CmBt1QNwtMrR5fm5P0hKedrkNGky4uxZ9IckXPL/6PlGT8x33FNaHjZrH//WW/fNstXAvKFINMtRrjMF0Mkb6SEuPoGGXCnzOs7Q09m0+SnJO6bn7nKX8yQCo93esJGkC/7enxMvL3/B9IGdP0B/JHb1DdLymjXHn7XOewy6hNh8bHPfjI06H1d/QX2qvL5")

def _repair_audit_plan_schema() -> None:
    if USE_POSTGRES: return
    expected_plans_cols = {"plan_id", "tenant_id", "calendar_audit_id", "working_days", "created_by", "plan_json", "created_at", "updated_at"}
    expected_slots_cols = {"id", "tenant_id", "plan_id", "plan_date", "slot_start", "slot_end", "department", "auditor_name", "notes"}

    def _table_exists(name): return bool(_fetch_one("select name from sqlite_master where type='table' and name=? limit 1;", (name,)))

    if not _table_exists("audit_plans") and not _table_exists("audit_plan_slots"): return
    plans_cols = _table_columns("audit_plans") if _table_exists("audit_plans") else set()
    slots_cols = _table_columns("audit_plan_slots") if _table_exists("audit_plan_slots") else set()

    needs_rebuild = (plans_cols and not expected_plans_cols.issubset(plans_cols)) or (slots_cols and not expected_slots_cols.issubset(slots_cols))
    if not needs_rebuild and plans_cols:
        info = _fetch_all("PRAGMA table_info(audit_plans);", ())
        pk_cols = {str(r.get("name")) for r in info if int(r.get("pk") or 0) == 1}
        if "plan_id" not in pk_cols:
            try:
                idxs = _fetch_all("PRAGMA index_list(audit_plans);", ())
                unique_cols: Set[str] = set()
                for idx_name in [r["name"] for r in idxs if int(r.get("unique") or 0) == 1]:
                    unique_cols |= {str(c.get("name")) for c in _fetch_all(f"PRAGMA index_info({idx_name});", ()) if c.get("name")}
            except Exception:
                unique_cols = set()
            if "plan_id" not in unique_cols:
                needs_rebuild = True
    if not needs_rebuild: return

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    script = "PRAGMA foreign_keys=OFF;\nBEGIN;\n\n"
    if slots_cols: script += f"ALTER TABLE audit_plan_slots RENAME TO audit_plan_slots_bak_{ts};\n"
    if plans_cols: script += f"ALTER TABLE audit_plans RENAME TO audit_plans_bak_{ts};\n"
    script += """
    create table if not exists audit_plans (
      plan_id text primary key, tenant_id text not null, calendar_audit_id text not null,
      working_days integer not null, created_by text not null, plan_json text not null default ('{}'),
      created_at text not null default (datetime('now')), updated_at text,
      unique (tenant_id, calendar_audit_id),
      foreign key (tenant_id) references tenants(id) on delete cascade,
      foreign key (calendar_audit_id) references audit_calendar(id) on delete cascade
    );
    create table if not exists audit_plan_slots (
      id text primary key, tenant_id text not null, plan_id text not null,
      plan_date text not null, slot_start text not null, slot_end text not null,
      department text not null, auditor_name text, notes text,
      unique (tenant_id, plan_id, plan_date, slot_start),
      foreign key (tenant_id) references tenants(id) on delete cascade,
      foreign key (plan_id) references audit_plans(plan_id) on delete cascade
    );
    create index if not exists idx_audit_plans_tenant on audit_plans(tenant_id);
    create index if not exists idx_audit_plan_slots_tenant on audit_plan_slots(tenant_id);
    create index if not exists idx_audit_plan_slots_plan on audit_plan_slots(plan_id);
    COMMIT;
    PRAGMA foreign_keys=ON;
    """
    _executescript(script)

def init_db() -> None:
    _executescript(_SCHEMA_PG if USE_POSTGRES else _SCHEMA)
    migrate_db()

def migrate_db() -> None:
    if USE_POSTGRES: return
    _executescript("""
        create table if not exists audit_calendar (
          id text primary key, tenant_id text not null, title text not null, scope text not null,
          start_date text not null, end_date text not null, created_by text not null,
          created_at text not null default (datetime('now')),
          foreign key (tenant_id) references tenants(id) on delete cascade
        );
        create index if not exists idx_audit_calendar_tenant on audit_calendar(tenant_id);
        create table if not exists audit_plans (
          plan_id text primary key, tenant_id text not null, calendar_audit_id text not null,
          working_days integer not null, created_by text not null, plan_json text not null default ('{}'),
          created_at text not null default (datetime('now')), updated_at text,
          unique (tenant_id, calendar_audit_id),
          foreign key (tenant_id) references tenants(id) on delete cascade,
          foreign key (calendar_audit_id) references audit_calendar(id) on delete cascade
        );
        create index if not exists idx_audit_plans_tenant on audit_plans(tenant_id);
        create table if not exists audit_plan_slots (
          id text primary key, tenant_id text not null, plan_id text not null,
          plan_date text not null, slot_start text not null, slot_end text not null,
          department text not null, auditor_name text, notes text,
          unique (tenant_id, plan_id, plan_date, slot_start),
          foreign key (tenant_id) references tenants(id) on delete cascade,
          foreign key (plan_id) references audit_plans(plan_id) on delete cascade
        );
        create index if not exists idx_audit_plan_slots_plan on audit_plan_slots(plan_id);
    """)
    try: _repair_audit_plan_schema()
    except Exception: pass
    try: _ensure_column("audit_plan_slots", "audit_id", "text")
    except Exception: pass

# ── Tenant helpers ────────────────────────────────────────────────────────────
def _get_tenant_by_code(tenant_code: str) -> Optional[Dict[str, Any]]:
    tenant_code = _normalize_text(tenant_code).lower()
    if not tenant_code: return None
    return _fetch_one("select * from tenants where tenant_code=? limit 1;", (tenant_code,))

def ensure_tenant(tenant_code: str, tenant_name: str = "") -> str:
    init_db()
    tenant_code = _normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE
    row = _get_tenant_by_code(tenant_code)
    if row: return str(row["id"])
    tenant_id = _uuid()
    _execute("insert into tenants (id, tenant_code, name) values (?, ?, ?);", (tenant_id, tenant_code, _normalize_text(tenant_name) or tenant_code.upper()))
    return tenant_id

def _ensure_state_row(tenant_id: str) -> None:
    if not _fetch_one("select tenant_id from audit_state where tenant_id = ?;", (tenant_id,)):
        _execute("insert into audit_state (tenant_id, busy_by_name_json, audit_history_json) values (?, ?, ?);", (tenant_id, json.dumps({}), json.dumps([])))

def _seed_checklists_if_empty(tenant_id: str) -> None:
    if _fetch_one("select id from checklists_catalog where tenant_id = ? limit 1;", (tenant_id,)): return
    seed = {
        "HR": {
            "Resource Planning": ["Has top management determined the need for resources and documented it?","Was the Resource Plan prepared as per the decided time period?","Were process owners involved in preparing the Resource Plan?","Is there evidence of consultation with Top Management and MR?","Is the Resource Plan reviewed during Management Review Meetings (MRM) and documented?"],
            "Pre-Boarding & Onboarding": ["Are pre-boarding details completed by the process owner for selected candidates?","Is the Employee Boarding Checklist used and completed?","Are education, experience, and training records collected and maintained?","Is the Employee Master List updated after joining?"],
            "Job Roles, Responsibilities & Communication": ["Are job roles, authorities, and responsibilities documented in Job Roles, Tasks, Competency Profile?","Has top management communicated job roles and responsibilities?","Is acknowledgement of JD communication recorded?"],
            "Competency & Skill Management": ["Are employee skills identified within 7 days of joining?","Is the Skill Matrix available and updated?","Is the Skill Matrix reviewed as per the decided time period?","Are improvements in skills documented and updated?"],
            "Exit Management": ["Are exit formalities maintained for employees leaving the organization?","Is employee list updated post-exit?"],
            "Training Planning": ["Has top management planned training for all employees and documented them?","Is a Training List maintained and used to select training topics?","Is the Training planning documented as per the time period?","Are planned trainings communicated to employees?"],
            "Conduct of Trainings": ["Are trainings conducted as per the approved Training Plan?","Are email or documented communications available as evidence?"],
            "Evaluation of Trainings": ["Is training effectiveness evaluated upon completion?","Is evaluation documented appropriately?","Are appropriate evaluation methods selected?"],
        },
        "MR": {
            "General Requirements": ["Does top management conduct management reviews at planned intervals?","Is MRM plan documented","Is the management review procedure defined and implemented?","Are management review records maintained","Is MRM notice sent acknowledged by respective personnel and is it documented?","Is the MRM attendance documented?"],
            "Management Review Inputs": ["Results of internal and external audits","Customer feedback (including complaints)","Process performance and product conformity","Status of preventive and corrective actions","Follow-up actions from previous management reviews","Changes that could affect the QMS (regulatory, organizational, product-related)","Recommendations for improvement","New or revised regulatory requirements applicable to medical devices","Resource needs (human, infrastructure, work environment)"],
            "Conduct of Management Review": ["Is the management review chaired or attended by top management?","Are relevant process owners involved as required?","Are discussions aligned with the planned agenda?"],
            "Management Review Outputs": ["Improvement of the effectiveness of the QMS","Improvement of product-related processes","Improvement of medical device safety and performance","Resource requirements","Actions addressing identified risks","Responsibilities and timelines assigned for actions"],
            "Follow-up & Records": ["Is the effectiveness of previous actions reviewed in subsequent MRMs?","Are management review minutes legible, dated, and approved?"],
        },
        "Production": {
            "BMR": ["Is a Batch Manufacturing Record (BMR) available for each batch/lot produced?","Is the BMR version controlled and approved before use?","Are material issue details recorded, including item code, quantity, and traceability to GRN/issue records?","Are critical process parameters and in-process checks recorded at each required step?","Are equipment/line clearance and cleaning status recorded before batch start?","Are yields, reconciliation, and any discrepancies documented and reviewed?","Are deviations, nonconformities, and rework (if any) documented with appropriate approvals?","Are operator and verifier signatures and dates present for all applicable steps?","Is the final review of the BMR performed by an authorized person before batch release or transfer to QA?","Are any attachments (printouts, labels, log sheets) referenced and traceable within the BMR?"],
        },
        "Purchase": {
            "Supplier Selection": ["Is supplier selection initiated when a new material, component, or service is required?","Does the Purchase Department identify potential suppliers?","Are supplier identification sources documented","Are suppliers evaluated based on defined selection criteria?","Are suppliers categorized on risk based approach?"],
            "Supplier Evaluation & Approval": ["Is Supplier Assessment completed for potential suppliers","Is the completed assessment reviewed","Are suppliers evaluated and scored as per defined criteria?","Are approved suppliers included in Approved Supplier List","For critical suppliers, is Supplier Quality Agreement executed before approval?"],
            "Control of Outsourced Processes": ["Are outsourced processes assigned only to approved suppliers?","Is verification of certificates and reports from outsourced activities carried out?"],
            "Purchase Order Control": ["Is supplier verification against the Approved Supplier List performed before PO issuance?","Is Supplier Selection & Evaluation initiated if the supplier is not approved","Are POs reviewed and approved by authorized personnel?","Are PO records maintained?"],
            "Verification of Purchased Product": ["Is Incoming Inspection conducted as per approved procedure or specifications?","Are inspection results documented?","Are inspection outcomes (acceptance/rejection/deviation/concession) linked to the supplier?","Are non-conforming items recorded","Are inspection results used for supplier performance monitoring"],
            "Supplier Performance Evaluation": ["Is supplier performance evaluated based on defined parameters?","Are suppliers classified according to defined rating scale?","Are suppliers evaluated as per defined time period?","Are supplier audits conducted when required?","Is SCAR issued to the suppliers when required?","Are supplier ratings reviewed in Management Review Meetings?"],
            "Supplier Re-evaluation": ["Is re-evaluation initiated based on performance monitoring results?","Are re-evaluation outcomes documented?"],
        },
    }
    for dept, sections in seed.items():
        for section, items in sections.items():
            for i, item in enumerate(items, start=1):
                _execute("insert into checklists_catalog (id, tenant_id, department, section, item_order, item_text) values (?, ?, ?, ?, ?, ?);", (_uuid(), tenant_id, dept, section, i, item))

def ensure_seed_files(tenant_code: str = "", tenant_name: str = "") -> str:
    init_db(); ensure_dirs()
    tenant_code = _normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE
    tenant_id = ensure_tenant(tenant_code, tenant_name)
    _tenant_generated_reports_dir(tenant_id)
    for d in DEFAULT_DEPARTMENTS: add_department_to_catalog(d, tenant_id=tenant_id)
    for k, v in DEFAULT_SKILLS.items(): ensure_skill_key_exists(k, fallback_label=v, tenant_id=tenant_id)
    for dept, keys in DEFAULT_DEPT_REQUIRED_SKILLS.items(): set_dept_required_skills(dept, keys, tenant_id=tenant_id)
    _seed_checklists_if_empty(tenant_id)
    _ensure_state_row(tenant_id)
    if not _fetch_one("select id from users where tenant_id = ? limit 1;", (tenant_id,)):
        admin_pw = make_password_record("admin123")
        _execute("insert into users (id, tenant_id, username, role, person_name, password_salt, password_iterations, password_hash, is_active, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", (_uuid(), tenant_id, "admin", "admin", None, admin_pw["salt"], int(admin_pw["iterations"]), admin_pw["hash"], True, _now_iso()))
        sample_people = [
            {"name": "Priya", "department": "HR", "skills": ["hr_competency_training_requirements", "hr_review_training_records_effectiveness", "hr_personnel_regulatory_awareness"], "level": "experienced"},
            {"name": "Amit", "department": "Purchase", "skills": ["pur_supplier_selection_evaluation", "pur_incoming_inspection_linkage", "pur_supplier_agreements_quality_clauses"], "level": "experienced"},
            {"name": "Ravi", "department": "Sales and Marketing", "skills": ["sm_labeling_claims_control", "sm_customer_communication_feedback", "sm_complaint_intake_escalation"], "level": "experienced"},
        ]
        for p in sample_people:
            add_auditor(name=p["name"], department=p["department"], level=p["level"], skills=set(p["skills"]), password="auditor123", tenant_id=tenant_id)
    return tenant_id

def get_tenant_id(tenant_code: str = "") -> str: return ensure_seed_files(tenant_code=tenant_code)
def get_tenant_code_from_id(tenant_id: str) -> str:
    row = _fetch_one("select tenant_code from tenants where id = ?;", (tenant_id,))
    return str(row["tenant_code"]) if row else DEFAULT_TENANT_CODE

# ── Departments & Skills ──────────────────────────────────────────────────────
def load_departments_catalog(tenant_id: Optional[str] = None) -> List[str]:
    init_db()
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return [str(r["name"]) for r in _fetch_all("select name from departments where tenant_id = ? order by lower(name);", (tenant_id,))]

def add_department_to_catalog(dept: str, tenant_id: Optional[str] = None) -> None:
    init_db()
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    if not dept: return
    if USE_POSTGRES:
        _execute("insert into departments (id, tenant_id, name, created_at) values (?, ?, ?, ?) on conflict (tenant_id, name) do nothing;", (_uuid(), tenant_id, dept, _now_iso()))
    else:
        _execute("insert or ignore into departments (id, tenant_id, name, created_at) values (?, ?, ?, ?);", (_uuid(), tenant_id, dept, _now_iso()))

def load_skills_catalog(tenant_id: Optional[str] = None) -> Dict[str, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return {str(r["skill_key"]).strip().lower(): _normalize_text(r["skill_label"]) for r in _fetch_all("select skill_key, skill_label from skills_catalog where tenant_id = ?;", (tenant_id,))}

def ensure_skill_key_exists(skill_key: str, fallback_label: str = "", tenant_id: Optional[str] = None) -> str:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    kk = str(skill_key).strip().lower()
    if not kk: raise ValueError("Skill key cannot be empty.")
    if _fetch_one("select skill_key from skills_catalog where tenant_id = ? and skill_key = ?;", (tenant_id, kk)): return kk
    _execute("insert into skills_catalog (id, tenant_id, skill_key, skill_label, created_at) values (?, ?, ?, ?, ?);", (_uuid(), tenant_id, kk, _normalize_text(fallback_label) or kk, _now_iso()))
    return kk

def ensure_skill_in_catalog(label: str, tenant_id: Optional[str] = None) -> str:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    label = _normalize_text(label)
    if not label: raise ValueError("Skill label cannot be empty.")
    for r in _fetch_all("select skill_key, skill_label from skills_catalog where tenant_id = ?;", (tenant_id,)):
        if str(r["skill_label"]).strip().lower() == label.lower():
            return str(r["skill_key"]).strip().lower()
    new_key = f"custom_{uuid.uuid4().hex[:10]}"
    ensure_skill_key_exists(new_key, fallback_label=label, tenant_id=tenant_id)
    return new_key

def load_dept_required_skills(tenant_id: Optional[str] = None) -> Dict[str, List[str]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all("select department_name, skill_key from dept_required_skills where tenant_id = ? order by lower(department_name), lower(skill_key);", (tenant_id,))
    out: Dict[str, List[str]] = {}
    for r in rows:
        out.setdefault(_normalize_text(r["department_name"]), []).append(str(r["skill_key"]).strip().lower())
    for d in out:
        seen: Set[str] = set()
        out[d] = [k for k in out[d] if not (k in seen or seen.add(k))]  # type: ignore
    return out

def set_dept_required_skills(dept: str, skill_keys: List[str], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept = _normalize_text(dept)
    if not dept: raise ValueError("Department cannot be empty.")
    add_department_to_catalog(dept, tenant_id=tenant_id)
    seen: Set[str] = set()
    cleaned = []
    for k in (skill_keys or []):
        kk = ensure_skill_key_exists(str(k).strip().lower(), fallback_label=str(k).strip().lower(), tenant_id=tenant_id)
        if kk and kk not in seen:
            seen.add(kk); cleaned.append(kk)
    _execute("delete from dept_required_skills where tenant_id = ? and department_name = ?;", (tenant_id, dept))
    for kk in cleaned:
        if USE_POSTGRES:
            _execute("insert into dept_required_skills (id, tenant_id, department_name, skill_key) values (?, ?, ?, ?) on conflict (tenant_id, department_name, skill_key) do nothing;", (_uuid(), tenant_id, dept, kk))
        else:
            _execute("insert or ignore into dept_required_skills (id, tenant_id, department_name, skill_key) values (?, ?, ?, ?);", (_uuid(), tenant_id, dept, kk))

def get_required_skills_for_dept(dept: str, tenant_id: Optional[str] = None) -> Set[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return {str(r["skill_key"]).strip().lower() for r in _fetch_all("select skill_key from dept_required_skills where tenant_id = ? and department_name = ?;", (tenant_id, _normalize_text(dept)))}

# ── Checklist catalog ─────────────────────────────────────────────────────────
def get_checklist_catalog(tenant_id: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    out: Dict[str, Dict[str, List[str]]] = {}
    for r in _fetch_all("select department, section, item_order, item_text from checklists_catalog where tenant_id = ? order by lower(department), lower(section), item_order;", (tenant_id,)):
        out.setdefault(_normalize_text(r["department"]), {}).setdefault(_normalize_text(r["section"]), []).append(str(r["item_text"]))
    return out

def get_sections_for_department(dept: str, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return [str(r["section"]) for r in _fetch_all("select section from checklists_catalog where tenant_id = ? and department = ? group by section order by lower(section);", (tenant_id, _normalize_text(dept)))]

def get_items_for_department_section(dept: str, section: str, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return [str(r["item_text"]) for r in _fetch_all("select item_text from checklists_catalog where tenant_id = ? and department = ? and section = ? order by item_order;", (tenant_id, _normalize_text(dept), _normalize_text(section)))]

def upsert_section_items(dept: str, section: str, items: List[str], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    if not dept or not section: return
    _execute("delete from checklists_catalog where tenant_id = ? and department = ? and section = ?;", (tenant_id, dept, section))
    for idx, txt in enumerate([str(x).strip() for x in (items or []) if str(x).strip()], start=1):
        _execute("insert into checklists_catalog (id, tenant_id, department, section, item_order, item_text) values (?, ?, ?, ?, ?, ?);", (_uuid(), tenant_id, dept, section, idx, txt))

def delete_section(dept: str, section: str, tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    if not dept or not section: return
    _execute("delete from checklists_catalog where tenant_id = ? and department = ? and section = ?;", (tenant_id, dept, section))

def get_checklist_extras(audit: Dict[str, Any], dept: str, section: str) -> List[str]:
    dept, section = _normalize_text(dept), _normalize_text(section)
    try: extras = (((audit.get("checklist_extras") or {}).get(dept) or {}).get(section) or [])
    except Exception: extras = []
    return [str(x).strip() for x in (extras if isinstance(extras, list) else []) if str(x).strip()]

def get_effective_checklist_items(audit_id: str, dept: str, section: str, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return []
    catalog_items = [str(x).strip() for x in get_items_for_department_section(dept, section, tenant_id=tenant_id) if str(x).strip()]
    seen: Set[str] = set()
    out = []
    for it in catalog_items + get_checklist_extras(a, dept, section):
        k = it.strip().lower()
        if k and k not in seen:
            seen.add(k); out.append(it.strip())
    return out

def add_checklist_extra_item(audit_id: str, dept: str, section: str, item_text: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    item_text = str(item_text or "").strip()
    if not item_text: return False, "Checklist item cannot be empty."
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if a.get("status") != "In Progress": return False, "Checklist can be edited only when the audit is 'In Progress'."
    if a.get("assigned_auditor") != auditor_name: return False, "You are not assigned to this audit."
    dept, section = _normalize_text(dept), _normalize_text(section)
    a.setdefault("checklist_extras", {}).setdefault(dept, {}).setdefault(section, [])
    current = a["checklist_extras"][dept][section]
    if not isinstance(current, list): current = []; a["checklist_extras"][dept][section] = current
    if item_text.lower() in {str(x).strip().lower() for x in current}: return False, "This checklist item already exists."
    current.append(item_text)
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Added checklist item."

def delete_checklist_extra_item(audit_id: str, dept: str, section: str, item_text: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    item_text = str(item_text or "").strip()
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name: return False, "You are not assigned to this audit."
    if a.get("status") != "In Progress": return False, "You can edit extra checklist items only when the audit is 'In Progress'."
    dept, section = _normalize_text(dept), _normalize_text(section)
    sec_list = (((a.get("checklist_extras") or {}).get(dept) or {}).get(section) or [])
    if not isinstance(sec_list, list) or not sec_list: return False, "No extra checklist items to delete."
    new_list = [x for x in sec_list if str(x).strip().lower() != item_text.lower()]
    if len(new_list) == len(sec_list): return False, "Item not found."
    a.setdefault("checklist_extras", {}).setdefault(dept, {})[section] = new_list
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Deleted checklist item."

# ── File helpers ──────────────────────────────────────────────────────────────
def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", ((name or "").strip().replace("\\", "/").split("/")[-1]))
    return name[:180] or "report"

def _safe_relpath_under_tenant(tenant_id: str, rel_path: str) -> str:
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel_path: raise ValueError("rel_path is required.")
    tenant_root = os.path.abspath(_tenant_root_dir(tenant_id))
    abs_path = os.path.abspath(os.path.join(tenant_root, rel_path))
    if not abs_path.startswith(tenant_root + os.sep) and abs_path != tenant_root:
        raise ValueError("Invalid path (outside tenant root).")
    return rel_path

def resolve_final_report_pdf_abs_path(tenant_id: str, pdf_rel_path: str) -> str:
    return os.path.abspath(os.path.join(os.path.abspath(_tenant_root_dir(tenant_id)), _safe_relpath_under_tenant(tenant_id, pdf_rel_path)))

def _normalize_users_list(users: List[str]) -> List[str]:
    seen: Set[str] = set()
    out = []
    for u in (users or []):
        uu = _normalize_text(u)
        if uu and uu.lower() not in seen:
            seen.add(uu.lower()); out.append(uu)
    return out

def _audit_ids_to_auditors(audit_ids: List[str], tenant_id: str) -> List[str]:
    if not audit_ids: return []
    rows = _fetch_all("select audit_id, assigned_auditor from audits where tenant_id = ? and audit_id in ({})".format(_placeholders(len(audit_ids))), tuple([tenant_id] + audit_ids))
    seen: Set[str] = set()
    auditors = []
    for r in rows:
        uname = _normalize_username(_normalize_text(r.get("assigned_auditor", "")))
        if uname and uname.lower() not in seen:
            seen.add(uname.lower()); auditors.append(uname)
    return auditors

def save_report_file(audit_id: str, uploaded_by: str, original_filename: str, file_bytes: bytes, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    audit_id = str(audit_id or "").strip()
    if not audit_id: return False, "audit_id is required."
    if not file_bytes: return False, "File is empty."
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    safe_name = _safe_filename(original_filename)
    report_dir = os.path.join(UPLOADS_DIR, "tenants", str(tenant_id), "audits", audit_id, "reports")
    os.makedirs(report_dir, exist_ok=True)
    base, ext = os.path.splitext(safe_name)
    saved_path = os.path.join(report_dir, f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.bin'}")
    try:
        with open(saved_path, "wb") as f: f.write(file_bytes)
    except Exception as e:
        return False, f"Failed to save file: {e}"
    reports = a.get("reports", []) if isinstance(a.get("reports"), list) else []
    reports.append({"file_name": safe_name, "saved_path": saved_path, "uploaded_by": _normalize_text(uploaded_by) or "unknown", "uploaded_at": _now_iso()})
    a["reports"] = reports
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Report uploaded successfully."

# ── People ────────────────────────────────────────────────────────────────────
def load_people(tenant_id: Optional[str] = None) -> List[Person]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    people_rows = _fetch_all("select name, department, level from people where tenant_id = ? and is_active = ? order by lower(name);", (tenant_id, True))
    skill_map: Dict[str, Set[str]] = {}
    for r in _fetch_all("select person_name, skill_key from person_skills where tenant_id = ?;", (tenant_id,)):
        skill_map.setdefault(_normalize_text(r["person_name"]), set()).add(str(r["skill_key"]).strip().lower())
    out = []
    for r in people_rows:
        nm = _normalize_text(r["name"])
        level = str(r["level"]).strip().lower()
        if level not in {"experienced", "fresher"}: level = "experienced"
        out.append(Person(name=nm, department=_normalize_text(r["department"]), skills=skill_map.get(nm, set()), level=level))
    return out

def list_people_records(tenant_id: Optional[str] = None) -> List[AttrDict]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all("select name, department, level, is_active, created_at from people where tenant_id = ? order by lower(name);", (tenant_id,))
    smap: Dict[str, List[str]] = {}
    for r in _fetch_all("select person_name, skill_key from person_skills where tenant_id = ?;", (tenant_id,)):
        smap.setdefault(_normalize_text(r["person_name"]), []).append(str(r["skill_key"]).strip().lower())
    out = []
    for r in rows:
        nm = _normalize_text(r["name"])
        out.append(AttrDict({"name": nm, "department": _normalize_text(r["department"]), "skills": sorted(set(smap.get(nm, []))), "level": str(r["level"]).strip().lower(), "is_active": bool(r["is_active"]) if isinstance(r["is_active"], bool) else bool(int(r["is_active"])), "created_at": r["created_at"]}))
    return out

# ── Users & Auth ──────────────────────────────────────────────────────────────
def load_users(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rows = _fetch_all("select username, role, person_name, password_salt, password_iterations, password_hash, created_at, is_active from users where tenant_id = ? order by lower(username);", (tenant_id,))
    return {"users": [{"username": r["username"], "role": r["role"], "person_name": r["person_name"], "password": {"salt": r["password_salt"], "iterations": r["password_iterations"], "hash": r["password_hash"]}, "created_at": r["created_at"], "is_active": bool(r["is_active"]) if isinstance(r["is_active"], bool) else bool(int(r["is_active"]))} for r in rows]}

def find_user(username: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    row = _fetch_one("select id, username, role, person_name, password_salt, password_iterations, password_hash, is_active from users where tenant_id = ? and lower(username) = ? limit 1;", (tenant_id, _normalize_text(username).lower()))
    if not row: return None
    return {"id": str(row["id"]), "tenant_id": tenant_id, "username": row["username"], "role": row["role"], "person_name": row["person_name"], "password_salt": row["password_salt"], "password_iterations": row["password_iterations"], "password_hash": row["password_hash"], "is_active": bool(int(row["is_active"]))}

def authenticate(username: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    return authenticate_tenant(DEFAULT_TENANT_CODE, username, password)

def authenticate_tenant(tenant_code: str, username: str, password: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    tenant_id = ensure_seed_files(_normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE)
    u = find_user(username, tenant_id=tenant_id)
    if not u: return False, None, "Invalid username or password."
    if not u.get("is_active", True): return False, None, "User is disabled."
    if not _verify_password_columns(password, u.get("password_salt"), u.get("password_iterations"), u.get("password_hash")):
        return False, None, "Invalid username or password."
    return True, {"id": u["id"], "tenant_id": tenant_id, "tenant_code": (_normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE), "username": u["username"], "role": u["role"], "person_name": u["person_name"]}, "Login successful."

def change_password(username: str, old_password: str, new_password: str, *, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    username = _normalize_text(username).lower()
    if not username: return False, "Username is required."
    if not old_password: return False, "Current password is required."
    if not new_password or len(new_password) < 6: return False, "New password must be at least 6 characters."
    u = find_user(username, tenant_id=tenant_id)
    if not u: return False, "User not found."
    if not u.get("is_active", True): return False, "User is disabled."
    if not _verify_password_columns(old_password, u.get("password_salt"), u.get("password_iterations"), u.get("password_hash")):
        return False, "Current password is incorrect."
    pw = make_password_record(new_password)
    _execute("update users set password_salt = ?, password_iterations = ?, password_hash = ? where tenant_id = ? and lower(username) = ?;", (pw["salt"], int(pw["iterations"]), pw["hash"], tenant_id, username))
    return True, "Password updated successfully."

def admin_reset_password(target_username: str, new_password: str, *, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    target_username = _normalize_text(target_username).lower()
    if not target_username: return False, "Target username is required."
    if not new_password or len(new_password) < 6: return False, "New password must be at least 6 characters."
    if not find_user(target_username, tenant_id=tenant_id): return False, "User not found."
    pw = make_password_record(new_password)
    _execute("update users set password_salt = ?, password_iterations = ?, password_hash = ? where tenant_id = ? and lower(username) = ?;", (pw["salt"], int(pw["iterations"]), pw["hash"], tenant_id, target_username))
    return True, f"Password reset successfully for '{target_username}'."

# ── State ─────────────────────────────────────────────────────────────────────
def load_state(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    _ensure_state_row(tenant_id)
    row = _fetch_one("select busy_by_name_json, audit_history_json from audit_state where tenant_id = ?;", (tenant_id,))
    return {"busy_by_name": json.loads(row["busy_by_name_json"] or "{}") if row else {}, "audit_history": json.loads(row["audit_history_json"] or "[]") if row else []}

def save_state(state: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    _ensure_state_row(tenant_id)
    _execute("update audit_state set busy_by_name_json = ?, audit_history_json = ? where tenant_id = ?;", (json.dumps(state.get("busy_by_name", {}) or {}), json.dumps(state.get("audit_history", []) or []), tenant_id))

def is_busy(state: Dict[str, Any], person_name: str) -> bool:
    return person_name in state.get("busy_by_name", {})

def has_all_required_skills(person: Person, required_skills: Set[str]) -> bool:
    return required_skills.issubset(person.skills)

def eligible_people(people: List[Person], state: Dict[str, Any], target_dept: str, required_skills: Set[str], level: str) -> List[Person]:
    return [p for p in people if p.level == level and p.department.strip().lower() != target_dept.strip().lower() and not is_busy(state, p.name) and has_all_required_skills(p, required_skills)]

def lock_auditor(state: Dict[str, Any], auditor_name: str, audit_id: str, target_dept: str, required_skills: Set[str], level: str) -> None:
    state["busy_by_name"][auditor_name] = {"audit_id": audit_id, "audited_department": target_dept, "required_skills": sorted(required_skills), "level": level, "started_at": _now_iso(), "status": "ongoing"}

def unlock_auditor(state: Dict[str, Any], auditor_name: str) -> None:
    state.get("busy_by_name", {}).pop(auditor_name, None)

# ── Audits ────────────────────────────────────────────────────────────────────
def _row_to_audit(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"audit_id": r["audit_id"], "title": r["title"] or "", "scope": r["scope"] or "", "audited_department": r["audited_department"], "required_skills": json.loads(r["required_skills_json"] or "[]"), "assigned_auditor": r["assigned_auditor"], "auditor_level": r["auditor_level"], "status": r["status"], "created_by": r["created_by"], "created_at": r["created_at"], "due_date": r["due_date"] or "", "reports": json.loads(r["reports_json"] or "[]"), "report_submitted_at": r["report_submitted_at"] or "", "closed_at": r["closed_at"] or "", "checklists": json.loads(r["checklists_json"] or "{}")}

def load_audits(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    return {"audits": [_row_to_audit(r) for r in _fetch_all("select * from audits where tenant_id = ? order by created_at desc;", (tenant_id,))]}

def save_audits(data: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    for a in data.get("audits", []): _save_updated_audit(a, tenant_id=tenant_id)

def list_audits(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return load_audits(tenant_id=tenant_id).get("audits", [])

def get_audit(audit_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    r = _fetch_one("select * from audits where tenant_id = ? and audit_id = ? limit 1;", (tenant_id, audit_id))
    return _row_to_audit(r) if r else None

def _save_updated_audit(updated: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    rsk_json = json.dumps(updated.get("required_skills", []) or [])
    rep_json = json.dumps(updated.get("reports", []) or [])
    chk_json = json.dumps(updated.get("checklists", {}) or {})
    aid = updated.get("audit_id", "")
    exists = _fetch_one("select audit_id from audits where tenant_id = ? and audit_id = ?;", (tenant_id, aid))
    if exists:
        _execute("update audits set title=?,scope=?,audited_department=?,required_skills_json=?,assigned_auditor=?,auditor_level=?,status=?,created_by=?,created_at=?,due_date=?,reports_json=?,report_submitted_at=?,closed_at=?,checklists_json=? where audit_id=? and tenant_id=?;",
            (updated.get("title",""), updated.get("scope",""), updated.get("audited_department",""), rsk_json, updated.get("assigned_auditor",""), updated.get("auditor_level",""), updated.get("status",""), updated.get("created_by",""), updated.get("created_at",_now_iso()), updated.get("due_date",""), rep_json, updated.get("report_submitted_at",""), updated.get("closed_at",""), chk_json, aid, tenant_id))
    else:
        _execute("insert into audits (audit_id,tenant_id,title,scope,audited_department,required_skills_json,assigned_auditor,auditor_level,status,created_by,created_at,due_date,reports_json,report_submitted_at,closed_at,checklists_json) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);",
            (aid or _new_audit_id(), tenant_id, updated.get("title",""), updated.get("scope",""), updated.get("audited_department",""), rsk_json, updated.get("assigned_auditor",""), updated.get("auditor_level",""), updated.get("status","Assigned"), updated.get("created_by",""), updated.get("created_at",_now_iso()), updated.get("due_date",""), rep_json, updated.get("report_submitted_at",""), updated.get("closed_at",""), chk_json))

def save_updated_audit(updated: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    _save_updated_audit(updated, tenant_id=tenant_id)

def create_audit(created_by: str, target_dept: str, title: str = "", scope: str = "", due_date: str = "", audit_date: str = "", required_skill_keys_override: Optional[Set[str]] = None, save_required_skills_as_default: bool = False, tenant_id: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    target_dept = _normalize_text(target_dept)
    if not target_dept: return None, "Department is required."
    add_department_to_catalog(target_dept, tenant_id=tenant_id)
    if required_skill_keys_override is not None:
        required_skills = {str(k).strip().lower() for k in required_skill_keys_override if str(k).strip()}
        for k in list(required_skills): ensure_skill_key_exists(k, fallback_label=k, tenant_id=tenant_id)
        if save_required_skills_as_default: set_dept_required_skills(target_dept, sorted(required_skills), tenant_id=tenant_id)
    else:
        required_skills = get_required_skills_for_dept(target_dept, tenant_id=tenant_id)
    if not required_skills and target_dept.lower() != "mr":
        return None, "No required skills defined for this department. Enter required skills (or save them as default)."
    audit_id = _new_audit_id()
    audit = {"audit_id": audit_id, "title": (title or "").strip(), "scope": (scope or "").strip(), "audited_department": target_dept, "required_skills": sorted(required_skills), "assigned_auditor": "", "auditor_level": "", "status": "Created", "created_by": _normalize_text(created_by) or "admin", "created_at": _now_iso(), "due_date": (due_date or "").strip(), "reports": [], "report_submitted_at": "", "closed_at": "", "checklists": {}, "checklist_extras": {}}
    _save_updated_audit(audit, tenant_id=tenant_id)
    return audit, f"Audit created: {audit_id}"

def create_and_assign_audit(created_by: str, target_dept: str, allow_fresher_fallback: bool, title: str = "", scope: str = "", due_date: str = "", required_skill_keys_override: Optional[Set[str]] = None, save_required_skills_as_default: bool = False, tenant_id: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    target_dept = _normalize_text(target_dept)
    if not target_dept: return None, "Department is required."
    add_department_to_catalog(target_dept, tenant_id=tenant_id)
    if required_skill_keys_override is not None:
        required_skills = {str(k).strip().lower() for k in required_skill_keys_override if str(k).strip()}
        for k in list(required_skills): ensure_skill_key_exists(k, fallback_label=k, tenant_id=tenant_id)
        if save_required_skills_as_default: set_dept_required_skills(target_dept, sorted(required_skills), tenant_id=tenant_id)
    else:
        required_skills = get_required_skills_for_dept(target_dept, tenant_id=tenant_id)
    if not required_skills and target_dept.lower() != "mr":
        return None, "No required skills defined for this department. Enter required skills (or save them as default)."
    people = load_people(tenant_id=tenant_id)
    state = load_state(tenant_id=tenant_id)
    experienced = eligible_people(people, state, target_dept, required_skills, "experienced")
    chosen = sorted(experienced, key=lambda p: p.name.lower())[0] if experienced else None
    if chosen is None and allow_fresher_fallback:
        freshers = eligible_people(people, state, target_dept, required_skills, "fresher")
        chosen = sorted(freshers, key=lambda p: p.name.lower())[0] if freshers else None
    if chosen is None: return None, "No eligible auditor available (busy, department conflict, or missing mandatory skills)."
    audit_id = _new_audit_id()
    audit = {"audit_id": audit_id, "title": title.strip(), "scope": scope.strip(), "audited_department": target_dept, "required_skills": sorted(required_skills), "assigned_auditor": chosen.name, "auditor_level": chosen.level, "status": "Assigned", "created_by": created_by, "created_at": _now_iso(), "due_date": due_date.strip(), "reports": [], "report_submitted_at": "", "closed_at": "", "checklists": {}, "checklist_extras": {}}
    _save_updated_audit(audit, tenant_id=tenant_id)
    lock_auditor(state, chosen.name, audit_id, target_dept, required_skills, chosen.level)
    save_state(state, tenant_id=tenant_id)
    return audit, f"Assigned {chosen.name} to audit '{target_dept}'."

def set_audit_status(audit_id: str, new_status: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if new_status not in {"Created", "Assigned", "In Progress", "Report Submitted", "Closed"}:
        return False, f"Invalid status: {new_status}"
    current = a.get("status") or "Assigned"
    if new_status == "In Progress" and current not in {"Created", "Assigned", "In Progress"}:
        return False, "Can set 'In Progress' only from 'Created' or 'Assigned'."
    if new_status == "Report Submitted":
        if current != "In Progress": return False, "Can set 'Report Submitted' only from 'In Progress'."
        if not a.get("reports"): return False, "Cannot submit without uploading at least one report."
        ok, msg = _validate_checklist_complete(a, tenant_id=tenant_id)
        if not ok: return False, msg
    if new_status == "Closed":
        if current != "Report Submitted": return False, "Can close audit only after 'Report Submitted'."
        if not a.get("reports"): return False, "Cannot complete audit without uploading report."
    if current == "Closed" and new_status != "Closed": return False, "Closed audit cannot be reopened."
    a["status"] = new_status
    if new_status == "Report Submitted" and not a.get("report_submitted_at"): a["report_submitted_at"] = _now_iso()
    if new_status == "Closed" and not a.get("closed_at"): a["closed_at"] = _now_iso()
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Status updated."

def _validate_checklist_complete(audit: Dict[str, Any], tenant_id: str) -> Tuple[bool, str]:
    dept = _normalize_text(audit.get("audited_department", ""))
    if not dept: return False, "Audit department is missing."
    sections = get_sections_for_department(dept, tenant_id=tenant_id)
    if not sections: return False, f"Checklist is not configured for department '{dept}'. Ask Admin to create checklist sections."
    saved = (audit.get("checklists") or {}).get(dept, {})
    if not isinstance(saved, dict): saved = {}
    missing_sections, incomplete_examples = [], []
    for sec in sections:
        expected_items = list(dict.fromkeys(str(x).strip() for x in (get_items_for_department_section(dept, sec, tenant_id=tenant_id) + get_checklist_extras(audit, dept, sec)) if str(x).strip()))
        if not expected_items: return False, f"Checklist section '{sec}' for department '{dept}' has no items."
        rows = saved.get(sec)
        if not rows: missing_sections.append(sec); continue
        try: rows_sorted = sorted(rows, key=lambda r: int(str(r.get("sr_no", "0")).strip() or 0))
        except Exception: rows_sorted = list(rows)
        if len(rows_sorted) < len(expected_items): incomplete_examples.append(f"{sec} (missing rows)"); continue
        for idx in range(len(expected_items)):
            r = rows_sorted[idx] if idx < len(rows_sorted) else {}
            if not _normalize_text(r.get("observation", "")) or not _normalize_text(r.get("evidence", "")):
                incomplete_examples.append(f"{sec} (SR {str(r.get('sr_no', idx + 1)).strip() or str(idx + 1)})"); break
    if missing_sections: return False, "Checklist incomplete. No saved responses for sections: " + ", ".join(missing_sections)
    if incomplete_examples:
        sample = ", ".join(incomplete_examples[:5])
        return False, f"Checklist incomplete. Fill Observation and Evidence for every row. Incomplete examples: {sample}{'  (+' + str(len(incomplete_examples) - 5) + ' more)' if len(incomplete_examples) > 5 else ''}"
    return True, "Checklist complete."

def submit_report(audit_id: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name: return False, "You are not assigned to this audit."
    if a.get("status") != "In Progress": return False, "Report can be submitted only when the audit is 'In Progress'."
    if not a.get("reports"): return False, "Please upload at least one report file before submitting."
    ok, msg = validate_audit_checklists_complete(audit_id, tenant_id=tenant_id)
    if not ok: return False, msg
    ok, msg = _validate_checklist_complete(a, tenant_id=tenant_id)
    if not ok: return False, msg
    a["status"] = "Report Submitted"; a["report_submitted_at"] = _now_iso()
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Report submitted."

def complete_audit(audit_id: str, auditor_name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name: return False, "You are not assigned to this audit."
    if not a.get("reports"): return False, "Cannot complete audit without uploading report."
    if a.get("status") != "Report Submitted": return False, "Audit can be completed only after 'Report Submitted'."
    a["status"] = "Closed"; a["closed_at"] = _now_iso()
    _save_updated_audit(a, tenant_id=tenant_id)
    state = load_state(tenant_id=tenant_id)
    unlock_auditor(state, auditor_name)
    state["audit_history"].append({"audit_id": a.get("audit_id"), "auditor_name": auditor_name, "audited_department": a.get("audited_department"), "required_skills": a.get("required_skills", []), "completed_at": a.get("closed_at"), "status": "completed"})
    save_state(state, tenant_id=tenant_id)
    return True, "Audit completed and auditor unlocked."

# ── Final reports ─────────────────────────────────────────────────────────────
def register_final_generated_report(*, created_by: str, pdf_rel_path: str, tenant_id: Optional[str] = None, included_audit_ids: Optional[List[str]] = None, audit_ids: Optional[List[str]] = None, summary: str = "", admin_summaries_by_audit_id: Optional[Dict[str, str]] = None, allowed_users: Optional[List[str]] = None, **_ignored_kwargs) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    created_by = _normalize_text(created_by)
    if not created_by: return False, None, "created_by is required."
    ids = audit_ids if audit_ids is not None else included_audit_ids
    audit_ids_clean = list(dict.fromkeys(str(x or "").strip() for x in (ids or []) if str(x or "").strip()))
    if not audit_ids_clean: return False, None, "At least one audit must be selected."
    found = {str(r["audit_id"]) for r in _fetch_all("select audit_id from audits where tenant_id = ? and audit_id in ({})".format(_placeholders(len(audit_ids_clean))), tuple([tenant_id] + audit_ids_clean))}
    missing = [a for a in audit_ids_clean if a not in found]
    if missing: return False, None, f"Invalid audit IDs: {missing}"
    try:
        pdf_rel_path = _safe_relpath_under_tenant(tenant_id, pdf_rel_path)
        abs_path = resolve_final_report_pdf_abs_path(tenant_id, pdf_rel_path)
    except Exception as e:
        return False, None, f"Invalid PDF path: {e}"
    if not os.path.exists(abs_path): return False, None, "PDF file not found on disk."
    stored_summary = _normalize_text(summary)
    if admin_summaries_by_audit_id:
        stored_summary = json.dumps({"summary": stored_summary, "admin_summaries_by_audit_id": {str(k): str(v) for k, v in admin_summaries_by_audit_id.items()}}, ensure_ascii=False)
    allowed_users = _normalize_users_list(allowed_users or ["ALL_AUDITORS"])
    report_id = _uuid()
    row = {"id": report_id, "tenant_id": tenant_id, "created_by": created_by, "created_at": _now_iso(), "summary": stored_summary, "audit_ids_json": json.dumps(audit_ids_clean), "allowed_users_json": json.dumps(allowed_users), "pdf_rel_path": pdf_rel_path}
    _execute("insert into generated_final_reports (id, tenant_id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path, is_deleted, deleted_at, deleted_by) values (?, ?, ?, ?, ?, ?, ?, ?, 0, null, null);", (row["id"], row["tenant_id"], row["created_by"], row["created_at"], row["summary"], row["audit_ids_json"], row["allowed_users_json"], row["pdf_rel_path"]))
    return True, row, "Final report registered."

def _parse_report_row(r: Dict) -> Dict:
    return {"id": r["id"], "created_by": r["created_by"], "created_at": r["created_at"], "summary": r["summary"], "audit_ids": json.loads(r.get("audit_ids_json") or "[]"), "allowed_users": json.loads(r.get("allowed_users_json") or "[]"), "pdf_rel_path": r["pdf_rel_path"]}

def list_final_generated_reports_for_user(username: str, role: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    username = _normalize_text(username)
    role = str(role or "").strip().lower()
    rows = _fetch_all("select id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path from generated_final_reports where tenant_id = ? and is_deleted = ? order by created_at desc;", (tenant_id, False))
    out = []
    for r in rows:
        if role in {"admin", "auditor", "manager"}:
            out.append(_parse_report_row(r)); continue
        allowed_norm = {str(x).strip().lower() for x in json.loads(r.get("allowed_users_json") or "[]") if str(x).strip()}
        if username and username.lower() in allowed_norm:
            out.append(_parse_report_row(r))
    return out

def get_final_generated_report(report_id: str, username: str, role: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    r = _fetch_one("select id, created_by, created_at, summary, audit_ids_json, allowed_users_json, pdf_rel_path, is_deleted from generated_final_reports where tenant_id = ? and id = ? limit 1;", (tenant_id, str(report_id or "").strip()))
    if not r or int(r.get("is_deleted") or 0) == 1: return None
    role = str(role or "").strip().lower()
    username = _normalize_text(username)
    allowed_norm = {str(x).strip().lower() for x in json.loads(r.get("allowed_users_json") or "[]") if str(x).strip()}
    if role not in {"admin", "auditor", "manager"} and (not username or username.lower() not in allowed_norm): return None
    return _parse_report_row(r)

def delete_final_generated_report(report_id: str, requester_role: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    if str(requester_role or "").strip().lower() != "admin": return False, "Only admin can delete final reports."
    report_id = str(report_id or "").strip()
    if not report_id: return False, "report_id is required."
    r = _fetch_one("select id, pdf_rel_path, is_deleted from generated_final_reports where tenant_id = ? and id = ? limit 1;", (tenant_id, report_id))
    if not r: return False, "Final report not found."
    if int(r.get("is_deleted") or 0) == 1: return False, "Final report already deleted."
    try: abs_path = resolve_final_report_pdf_abs_path(tenant_id, str(r.get("pdf_rel_path") or ""))
    except Exception: abs_path = None
    _execute("update generated_final_reports set is_deleted = 1, deleted_at = ?, deleted_by = ? where tenant_id = ? and id = ?;", (_now_iso(), "admin", tenant_id, report_id))
    if abs_path and os.path.exists(abs_path):
        try: os.remove(abs_path)
        except Exception: pass
    return True, "Final report deleted."

# ── Checklist audit helpers ───────────────────────────────────────────────────
def save_audit_section_table(audit_id: str, dept: str, section: str, rows: List[Dict[str, str]], auditor_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    if not audit_id or not dept or not section: return False, "audit_id, dept, and section are required."
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    if auditor_name is not None:
        if a.get("assigned_auditor") != auditor_name: return False, "You are not assigned to this audit."
        if a.get("status") != "In Progress": return False, "Checklist can be edited only when the audit is 'In Progress'."
    a.setdefault("checklists", {}).setdefault(dept, {})[section] = rows
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, "Checklist saved."

def load_audit_section_table(audit_id: str, dept: str, section: str, tenant_id: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return None
    return a.get("checklists", {}).get(_normalize_text(dept), {}).get(_normalize_text(section))

def _checklist_row_complete(row: Dict[str, Any]) -> bool:
    return bool(str(row.get("observation", "") or "").strip()) and bool(str(row.get("evidence", "") or "").strip())

def get_checklist_rows_for_audit_section(audit_id: str, dept: str, section: str, *, tenant_id: Optional[str] = None) -> List[Dict[str, str]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    saved = load_audit_section_table(audit_id, dept, section, tenant_id=tenant_id)
    if saved and isinstance(saved, list):
        return [{"sr_no": str(r.get("sr_no", "")).strip(), "checklist": str(r.get("checklist", "")).strip(), "observation": str(r.get("observation", "")).strip(), "evidence": str(r.get("evidence", "")).strip()} for r in saved]
    items = get_items_for_department_section(_normalize_text(dept), _normalize_text(section), tenant_id=tenant_id) or []
    return [{"sr_no": str(i), "checklist": str(item).strip(), "observation": "", "evidence": ""} for i, item in enumerate(items, start=1)]

def get_checklist_progress(audit_id: str, dept: str, section: str, *, tenant_id: Optional[str] = None) -> Dict[str, int]:
    rows = get_checklist_rows_for_audit_section(audit_id, dept, section, tenant_id=tenant_id)
    total = len(rows)
    completed_prefix = next((i for i, r in enumerate(rows) if not _checklist_row_complete(r)), total)
    return {"total": total, "unlocked": min(total, completed_prefix + 1) if total > 0 else 0, "completed_prefix": completed_prefix, "completed_any": sum(1 for r in rows if _checklist_row_complete(r))}

def save_single_checklist_response(audit_id: str, dept: str, section: str, sr_no: str, observation: str, evidence: str, *, auditor_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    sr_no_s = str(sr_no or "").strip()
    if not sr_no_s: return False, "sr_no is required."
    rows = get_checklist_rows_for_audit_section(audit_id, _normalize_text(dept), _normalize_text(section), tenant_id=tenant_id)
    idx = next((i for i, r in enumerate(rows) if str(r.get("sr_no", "")).strip() == sr_no_s), None)
    if idx is None:
        try:
            n = int(sr_no_s)
            if n <= 0: raise ValueError
            while len(rows) < n: rows.append({"sr_no": str(len(rows) + 1), "checklist": "", "observation": "", "evidence": ""})
            idx = n - 1
        except Exception:
            return False, "Checklist row not found."
    rows[idx]["observation"] = str(observation or "").strip()
    rows[idx]["evidence"] = str(evidence or "").strip()
    return save_audit_section_table(audit_id=audit_id, dept=dept, section=section, rows=rows, auditor_name=auditor_name, tenant_id=tenant_id)

def add_audit_section_checklist_item(audit_id: str, dept: str, section: str, checklist_text: str, auditor_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    checklist_text = (checklist_text or "").strip()
    if not checklist_text: return False, "Checklist point is required."
    existing = load_audit_section_table(audit_id, dept, section, tenant_id=tenant_id) or []
    rows = list(existing) if existing else [{"sr_no": str(i), "checklist": str(item).strip(), "observation": "", "evidence": ""} for i, item in enumerate(get_items_for_department_section(dept, section, tenant_id=tenant_id), start=1)]
    rows.append({"sr_no": str(len(rows) + 1), "checklist": checklist_text, "observation": "", "evidence": ""})
    return save_audit_section_table(audit_id=audit_id, dept=dept, section=section, rows=rows, auditor_name=auditor_name, tenant_id=tenant_id)

def validate_audit_checklists_complete(audit_id: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a: return False, "Audit not found."
    checklists = a.get("checklists") or {}
    if not isinstance(checklists, dict) or not checklists: return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."
    any_rows = False
    for dept, sec_map in checklists.items():
        if not isinstance(sec_map, dict): continue
        for section, rows in sec_map.items():
            if not rows: continue
            any_rows = True
            for r in rows:
                chk = str((r or {}).get("checklist", "")).strip()
                obs = str((r or {}).get("observation", "")).strip()
                evd = str((r or {}).get("evidence", "")).strip()
                if not chk: return False, "Checklist has an empty point. Please remove or fill it before submitting."
                if not obs or not evd: return False, "Checklist incomplete. Please fill Observation and Evidence for all points before submitting."
    if not any_rows: return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."
    return True, "Checklist complete."

# ── Auditor CRUD ──────────────────────────────────────────────────────────────
def add_auditor(name: str, department: str, level: str, skills: Set[str], password: str = "auditor123", tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    name, department, level = _normalize_text(name), _normalize_text(department), str(level).strip().lower()
    if not name: return False, "Name is required."
    if not department: return False, "Department is required."
    if level not in {"experienced", "fresher"}: return False, "Invalid level. Use 'experienced' or 'fresher'."
    if not skills: return False, "At least one skill is required."
    add_department_to_catalog(department, tenant_id=tenant_id)
    cleaned_skills = {ensure_skill_key_exists(str(k).strip().lower(), fallback_label=str(k).strip().lower(), tenant_id=tenant_id) for k in skills if str(k).strip()}
    if not cleaned_skills: return False, "At least one valid skill is required."
    if _fetch_one("select name from people where tenant_id = ? and lower(name) = ? limit 1;", (tenant_id, name.lower())): return False, "Auditor with this name already exists."
    _execute("insert into people (id, tenant_id, name, department, level, is_active, created_at) values (?, ?, ?, ?, ?, ?, ?);", (_uuid(), tenant_id, name, department, level, True, _now_iso()))
    for kk in sorted(cleaned_skills):
        if USE_POSTGRES:
            _execute("insert into person_skills (id, tenant_id, person_name, skill_key) values (?, ?, ?, ?) on conflict (tenant_id, person_name, skill_key) do nothing;", (_uuid(), tenant_id, name, kk))
        else:
            _execute("insert or ignore into person_skills (id, tenant_id, person_name, skill_key) values (?, ?, ?, ?);", (_uuid(), tenant_id, name, kk))
    uname = _normalize_username(name)
    if _fetch_one("select id from users where tenant_id = ? and lower(username) = ? limit 1;", (tenant_id, uname.lower())):
        return True, f"Auditor added. Login already existed for username '{uname}'."
    pw = make_password_record(password)
    _execute("insert into users (id, tenant_id, username, role, person_name, password_salt, password_iterations, password_hash, is_active, created_at) values (?, ?, ?, 'auditor', ?, ?, ?, ?, ?, ?);", (_uuid(), tenant_id, uname, name, pw["salt"], int(pw["iterations"]), pw["hash"], True, _now_iso()))
    return True, f"Auditor added successfully. Username: {uname} | Password: {password}"

def delete_auditor(name: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    name = _normalize_text(name)
    if not name: return False, "Name is required."
    if is_busy(load_state(tenant_id=tenant_id), name): return False, "Cannot delete. Auditor is locked in an ongoing audit."
    if not _fetch_one("select name from people where tenant_id = ? and lower(name) = ? limit 1;", (tenant_id, name.lower())): return False, "Auditor not found."
    _execute("delete from person_skills where tenant_id = ? and lower(person_name) = ?;", (tenant_id, name.lower()))
    _execute("delete from people where tenant_id = ? and lower(name) = ?;", (tenant_id, name.lower()))
    _execute("delete from users where tenant_id = ? and role = 'auditor' and lower(person_name) = ?;", (tenant_id, name.lower()))
    return True, "Auditor deleted successfully."

# ── Audit dropdown ────────────────────────────────────────────────────────────
def _build_audit_display_title(a: Dict[str, Any]) -> str:
    title = _normalize_text(a.get("title", "")) or _normalize_text(a.get("audit_title", ""))
    dept = _normalize_text(a.get("audited_department", ""))
    label = title or f"{dept or 'Audit'} | {str(a.get('audit_id', '') or '')[:8] or 'unknown'}"
    extras = []
    if dept and dept.lower() not in label.lower(): extras.append(dept)
    for k in ["status", "due_date", "assigned_auditor"]:
        v = _normalize_text(a.get(k, ""))
        if v: extras.append(f"Due: {v}" if k == "due_date" else f"Auditor: {v}" if k == "assigned_auditor" else v)
    return f"{label}  ({' | '.join(extras)})" if extras else label

def get_audit_dropdown_options(tenant_id: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    labels, label_to_id, seen = [], {}, {}
    for a in list_audits(tenant_id=tenant_id):
        audit_id = str(a.get("audit_id", "") or "").strip()
        if not audit_id: continue
        base = _build_audit_display_title(a)
        key = base
        if key in seen:
            seen[key] += 1; key = f"{base} [{seen[base]}]"
        else:
            seen[key] = 1
        labels.append(key); label_to_id[key] = audit_id
    labels.sort(key=str.lower)
    return labels, label_to_id

# ── Audit plan ────────────────────────────────────────────────────────────────
AUDIT_PLAN_SLOTS = [("09:30","10:30"),("10:30","11:30"),("11:30","12:30"),("12:30","13:30"),("13:30","14:30"),("14:30","15:30"),("15:30","16:30")]

def list_audit_calendar(tenant_id: str) -> List[Dict[str, Any]]:
    init_db()
    return [dict(r) for r in _fetch_all("select id, title, scope, start_date, end_date, created_by, created_at from audit_calendar where tenant_id = ? order by start_date asc;", (tenant_id,))]

def create_audit_calendar(tenant_id: str, title: str, scope: str, start_date: str, end_date: str, created_by: str) -> Tuple[Optional[Dict[str, Any]], str]:
    init_db()
    title, scope = _normalize_text(title), _normalize_text(scope)
    if not title: return None, "Audit title is required."
    if not scope: return None, "Scope is required."
    if not start_date or not end_date: return None, "Start Date and End Date are required."
    try:
        sd, ed = datetime.fromisoformat(start_date).date(), datetime.fromisoformat(end_date).date()
    except Exception:
        return None, "Invalid date format."
    if ed < sd: return None, "End Date cannot be before Start Date."
    audit_id = str(uuid.uuid4())
    _execute("insert into audit_calendar (id, tenant_id, title, scope, start_date, end_date, created_by) values (?, ?, ?, ?, ?, ?, ?);", (audit_id, tenant_id, title, scope, sd.isoformat(), ed.isoformat(), created_by or ""))
    row = _fetch_one("select id, title, scope, start_date, end_date, created_by, created_at from audit_calendar where tenant_id=? and id=?;", (tenant_id, audit_id))
    return (dict(row) if row else None), "Audit created."

def get_audit_calendar(tenant_id: str, audit_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    row = _fetch_one("select id, title, scope, start_date, end_date, created_by, created_at from audit_calendar where tenant_id=? and id=? limit 1;", (tenant_id, audit_id))
    return dict(row) if row else None

def _is_working_day(d: date) -> bool: return d.weekday() < 5

def _next_working_days(start: date, count: int) -> List[date]:
    days, cur = [], start
    while len(days) < int(count):
        if _is_working_day(cur): days.append(cur)
        cur += timedelta(days=1)
    return days

def list_departments_simple(tenant_id: str) -> List[str]:
    init_db()
    return [r["name"] for r in _fetch_all("select name from departments where tenant_id=? order by name asc;", (tenant_id,))]

def list_eligible_auditors(tenant_id: str, audited_department: str) -> List[str]:
    init_db()
    dept_n = _normalize_text(audited_department).lower()
    required = set(get_required_skills_for_dept(audited_department, tenant_id=tenant_id) or set())
    names = []
    for p in load_people(tenant_id=tenant_id):
        if dept_n and _normalize_text(getattr(p, "department", "")).lower() == dept_n: continue
        if required and not required.issubset(set(getattr(p, "skills", set()) or set())): continue
        names.append(getattr(p, "name", ""))
    return sorted(n for n in names if n)

def _plan_slot_audit_title(calendar_audit: Optional[Dict[str, Any]], department: str, plan_date: str, slot_start: str, slot_end: str) -> str:
    base = _normalize_text((calendar_audit or {}).get("title", ""))
    dept = _normalize_text(department)
    d, s = _normalize_text(plan_date), f"{slot_start}-{slot_end}" if slot_start and slot_end else ""
    if base and dept: return f"{base} | {dept} | {d} {s}".strip()
    return (f"{dept} | {d} {s}" if dept else f"Audit | {d} {s}").strip()

def _sync_plan_slots_to_audits(tenant_id: str, plan_id: str) -> Tuple[int, int]:
    init_db()
    plan = _fetch_one("select calendar_audit_id from audit_plans where tenant_id=? and plan_id=? limit 1;", (tenant_id, plan_id))
    cal = get_audit_calendar(tenant_id, str(plan.get("calendar_audit_id")) if plan else "") if plan else None
    cal_scope = _normalize_text((cal or {}).get("scope", ""))
    slots = _fetch_all("select id, plan_date, slot_start, slot_end, department, auditor_name, notes, audit_id from audit_plan_slots where tenant_id=? and plan_id=? order by plan_date asc, slot_start asc;", (tenant_id, plan_id))
    created = updated = 0
    for s in slots:
        dept = _normalize_text(s.get("department") or "")
        auditor_name = _normalize_text(s.get("auditor_name") or "")
        if not dept or not auditor_name: continue
        required = sorted(get_required_skills_for_dept(dept, tenant_id=tenant_id) or set())
        slot_audit_id = str(s.get("audit_id") or "").strip()
        existing_audit = get_audit(slot_audit_id, tenant_id=tenant_id) if slot_audit_id else None
        title = _plan_slot_audit_title(cal, dept, str(s.get("plan_date") or ""), str(s.get("slot_start") or ""), str(s.get("slot_end") or ""))
        notes = _normalize_text(s.get("notes") or "")
        if existing_audit is None:
            new_id = _new_audit_id()
            _save_updated_audit({"audit_id": new_id, "title": title, "scope": cal_scope, "audited_department": dept, "required_skills": required, "assigned_auditor": auditor_name, "auditor_level": "", "status": "Assigned", "created_by": "admin", "created_at": _now_iso(), "due_date": str(s.get("plan_date") or ""), "reports": [], "report_submitted_at": "", "closed_at": "", "checklists": {}, "checklist_extras": {}, "plan_slot_notes": notes}, tenant_id=tenant_id)
            try: _execute("update audit_plan_slots set audit_id=? where tenant_id=? and id=?;", (new_id, tenant_id, s["id"]))
            except Exception: pass
            created += 1
        else:
            status = _normalize_text(existing_audit.get("status", "")) or "Assigned"
            if status in {"Created", "Assigned"}:
                existing_audit.update({"title": title or existing_audit.get("title", ""), "scope": cal_scope or existing_audit.get("scope", ""), "audited_department": dept, "required_skills": required, "assigned_auditor": auditor_name, "due_date": str(s.get("plan_date") or existing_audit.get("due_date", ""))})
                if notes: existing_audit["plan_slot_notes"] = notes
                if status == "Created": existing_audit["status"] = "Assigned"
                _save_updated_audit(existing_audit, tenant_id=tenant_id)
                updated += 1
    return created, updated

def get_audit_plan_by_calendar_audit(tenant_id: str, calendar_audit_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    row = _fetch_one("select plan_id, calendar_audit_id, working_days, created_by, created_at, updated_at from audit_plans where tenant_id=? and calendar_audit_id=? limit 1;", (tenant_id, calendar_audit_id))
    if not row: return None
    plan = dict(row)
    plan["slots"] = [dict(s) for s in _fetch_all("select id, plan_date, slot_start, slot_end, department, auditor_name, notes from audit_plan_slots where tenant_id=? and plan_id=? order by plan_date asc, slot_start asc;", (tenant_id, plan["plan_id"]))]
    return plan

def create_or_reset_audit_plan(tenant_id: str, calendar_audit_id: str, working_days: int, created_by: str) -> Tuple[Optional[Dict[str, Any]], str]:
    init_db()
    if not working_days or int(working_days) <= 0: return None, "Working days must be greater than 0."
    audit = get_audit_calendar(tenant_id, calendar_audit_id)
    if not audit: return None, "Selected audit not found."
    sd = _parse_iso_date(audit.get("start_date"))
    if not sd: return None, "Audit Start Date is invalid."
    working_days = int(working_days)
    existing = _fetch_one("select plan_id from audit_plans where tenant_id=? and calendar_audit_id=? limit 1;", (tenant_id, calendar_audit_id))
    if existing:
        plan_id = existing["plan_id"]
        _execute("update audit_plans set working_days=?, updated_at=? where tenant_id=? and plan_id=?;", (working_days, _now_iso(), tenant_id, plan_id))
        if "plan_json" in _table_columns("audit_plans"):
            try: _execute("update audit_plans set plan_json='{}' where tenant_id=? and plan_id=? and (plan_json is null or plan_json='');", (tenant_id, plan_id))
            except Exception: pass
        _execute("delete from audit_plan_slots where tenant_id=? and plan_id=?;", (tenant_id, plan_id))
    else:
        plan_id = str(uuid.uuid4())
        cols = _table_columns("audit_plans")
        if "plan_json" in cols:
            _execute("insert into audit_plans (plan_id, tenant_id, calendar_audit_id, working_days, created_by, plan_json) values (?, ?, ?, ?, ?, ?);", (plan_id, tenant_id, calendar_audit_id, working_days, created_by or "", "{}"))
        else:
            _execute("insert into audit_plans (plan_id, tenant_id, calendar_audit_id, working_days, created_by) values (?, ?, ?, ?, ?);", (plan_id, tenant_id, calendar_audit_id, working_days, created_by or ""))
    for d in _next_working_days(sd, working_days):
        for s0, s1 in AUDIT_PLAN_SLOTS:
            _execute("insert into audit_plan_slots (id, tenant_id, plan_id, plan_date, slot_start, slot_end, department, auditor_name, notes) values (?, ?, ?, ?, ?, ?, ?, ?, ?);", (str(uuid.uuid4()), tenant_id, plan_id, d.isoformat(), s0, s1, "", None, None))
    return get_audit_plan_by_calendar_audit(tenant_id, calendar_audit_id), "Audit plan created."

def update_audit_plan_slots(tenant_id: str, plan_id: str, slots: List[Dict[str, Any]]) -> Tuple[bool, str]:
    init_db()
    if not _fetch_one("select plan_id from audit_plans where tenant_id=? and plan_id=? limit 1;", (tenant_id, plan_id)):
        return False, "Audit plan not found."
    for s in slots:
        plan_date = s.get("plan_date") or s.get("Date") or ""
        slot_start = s.get("slot_start") or s.get("Slot Start") or ""
        slot_end = s.get("slot_end") or s.get("Slot End") or ""
        if not plan_date or not slot_start or not slot_end: continue
        department = _normalize_text(s.get("department") or s.get("Department") or "")
        auditor_name = _normalize_text(s.get("auditor_name") or s.get("Auditor") or "")
        notes = s.get("notes") or s.get("Notes") or None
        _execute("update audit_plan_slots set department=?, auditor_name=?, notes=? where tenant_id=? and plan_id=? and plan_date=? and slot_start=? and slot_end=?;", (department, auditor_name if auditor_name else None, notes, tenant_id, plan_id, plan_date, slot_start, slot_end))
    _execute("update audit_plans set updated_at=? where tenant_id=? and plan_id=?;", (_now_iso(), tenant_id, plan_id))
    try: created_cnt, updated_cnt = _sync_plan_slots_to_audits(tenant_id, plan_id)
    except Exception: created_cnt = updated_cnt = 0
    msg = f"Audit plan saved. Audits synced: {created_cnt} created, {updated_cnt} updated." if (created_cnt or updated_cnt) else "Audit plan saved."
    return True, msg

def auto_assign_auditors(tenant_id: str, plan_id: str) -> Tuple[bool, str]:
    init_db()
    slots = _fetch_all("select id, plan_date, slot_start, slot_end, department, auditor_name from audit_plan_slots where tenant_id=? and plan_id=? order by plan_date asc, slot_start asc;", (tenant_id, plan_id))
    assigned_by_date: Dict[str, Set[str]] = {}
    changed = 0
    for s in slots:
        dep = _normalize_text(s["department"])
        if not dep or s["auditor_name"]: continue
        assigned = assigned_by_date.setdefault(s["plan_date"], set())
        eligible = list_eligible_auditors(tenant_id, dep)
        pick = next((n for n in eligible if n not in assigned), eligible[0] if eligible else None)
        if pick:
            _execute("update audit_plan_slots set auditor_name=? where tenant_id=? and id=?;", (pick, tenant_id, s["id"]))
            assigned.add(pick); changed += 1
    if changed: _execute("update audit_plans set updated_at=? where tenant_id=? and plan_id=?;", (_now_iso(), tenant_id, plan_id))
    try: _sync_plan_slots_to_audits(tenant_id, plan_id)
    except Exception: pass
    return True, f"Auto-assigned {changed} slot(s)."
