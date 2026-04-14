from __future__ import annotations

import os, re, json, uuid, hashlib, hmac, sqlite3, base64, zlib, calendar, threading
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
DEFAULT_DEPARTMENTS = ["HR", "MR", "Purchase", "Sales and Marketing", "Production","Quality Assurance", "Maintenance", "Top Management"]
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

# ── Connection pooling ────────────────────────────────────────────────────────
# SQLite: one persistent connection per thread (avoids open/close per query)
_sqlite_local = threading.local()

def _get_sqlite_conn():
    conn = getattr(_sqlite_local, "conn", None)
    if conn is not None:
        return conn
    ensure_dirs()
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in [
        "PRAGMA journal_mode=WAL;",
        "PRAGMA synchronous=NORMAL;",
        "PRAGMA foreign_keys=ON;",
        "PRAGMA busy_timeout=30000;",
        "PRAGMA cache_size=-8000;",   # 8 MB page cache
        "PRAGMA temp_store=MEMORY;",
    ]:
        conn.execute(pragma)
    _sqlite_local.conn = conn
    return conn

# Postgres: simple thread-local connection (psycopg2 pool optional)
_pg_local = threading.local()

def _get_pg_conn():
    conn = getattr(_pg_local, "conn", None)
    if conn is not None:
        try:
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            pass
    if psycopg2 is None:
        raise RuntimeError("Postgres requested but psycopg2 is not installed. Add psycopg2-binary to requirements.txt.")
    conn = psycopg2.connect(_pg_url_with_ssl(DATABASE_URL), connect_timeout=15)
    conn.autocommit = True
    _pg_local.conn = conn
    return conn

def _connect():
    if USE_POSTGRES:
        return _get_pg_conn()
    return _get_sqlite_conn()

def _fetch_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    q = _sql(sql)
    conn = _connect()
    if USE_POSTGRES:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(q, params)
            row = cur.fetchone()
            return dict(row) if row else None
    row = conn.execute(q, params).fetchone()
    return dict(row) if row else None

def _fetch_all(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    q = _sql(sql)
    conn = _connect()
    if USE_POSTGRES:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(q, params)
            return [dict(r) for r in cur.fetchall()]
    return [dict(r) for r in conn.execute(q, params).fetchall()]

def _execute(sql: str, params: Tuple[Any, ...] = ()) -> int:
    q = _sql(sql)
    conn = _connect()
    if USE_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(q, params)
            return cur.rowcount
    cur = conn.execute(q, params)
    conn.commit()
    return cur.rowcount

def _executescript(script: str) -> None:
    if not script or not str(script).strip(): return
    if not USE_POSTGRES:
        _get_sqlite_conn().executescript(script)
        return
    statements = [s.strip() for s in str(script).split(";") if s.strip()]
    conn = _connect()
    with conn.cursor() as cur:
        for st in statements: cur.execute(st)

_table_columns_cache: Dict[str, Set[str]] = {}

def _table_columns(table: str) -> Set[str]:
    if table in _table_columns_cache:
        return _table_columns_cache[table]
    if USE_POSTGRES:
        rows = _fetch_all("select column_name as name from information_schema.columns where table_schema='public' and table_name = ?", (table,))
    else:
        rows = _fetch_all(f"PRAGMA table_info({table})", ())
    cols = {str(r.get("name")) for r in rows if r.get("name")}
    _table_columns_cache[table] = cols
    return cols

def _invalidate_table_columns_cache(table: str) -> None:
    _table_columns_cache.pop(table, None)

def _ensure_column(table: str, col_name: str, col_def_sql: str) -> None:
    if col_name not in _table_columns(table):
        _execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def_sql}")
        _invalidate_table_columns_cache(table)

# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = _d("eNrFV82S2yAMvucpuMWZyc60505vne210xdgiJETGgxewJvk7Ssgdoj/Jj+73r1sLIEkPn2SYJEbYA6IYxsJRBREaUfgKKyzxIFiCv9nC0IEx8+jI5URJTMnsofTGsVxCc01h6j321UtJamVeKvBr1Gs7Ci9NPrllLnORg4Fq6UjGUe9EyVkS6UPy9VqsfqxWEyEW1swtwTbaNNo/N7hOI2W3aPlO8j3JAsaoUi2ZLwUarlelkyxLRj8xWounDYYtbdRYWBa0dZBkDFrD9pwapl0fbetWjgwzAmtLPpygOaH1+2Y3fXNCEtZ7sQ79Da3OH9/LBsBtZBjkrXArlsgg77QBsRWefyTRStioAADKoeWY5kXa4XuJGB6c2ZzxsFn/JxwoTgcOwkX/EhD0mm04g2E78TXNGU4VMy4Em5j+RBxPorcI3DOCWUCRgJoIr0ZVrsXUlqaM8ek3j6IbDBC/XlHVJJtQH4i9m0AcyXgDNsF+2sc72G1owbeamEQh2jkwSRcsk+HmT6RpQFIO+a+AGOPDUJzTfAeWjdDXYGuUPiRveOCUV8n4b1L+WYaRVUYR3DEgSM8XhxHUWHA7qAZRbMPhDk7WMxGktsouCObYU4/VTHdWf9EtSSmvqBSovdeT7rC6GZkw30oQhp+0vuBdcLJy/XJ5rq6fAWbyNap2umUOP2Hx+ivwusU4uqJH29wAyuigg7UYgjMMVfb8bG0Od0+skI7qIHyAOv5rAYqbdxY/FFLbb0phUtsBjdS247E9w7pMzRibgaeRWokDIuC+6hFPeyxD3co1CHYprYnzEEoqjEKBIM7NK7N6RNxmTpUkpjnblFTFWEh9w+LgVeDg5LiowKnw9CbI6jDpvtm/rrxuE48zNXO8t0+4Vgf32u+vbyQn0/8+f2vQjFJfoPy7zfg5G+sW5KVOD7FS2AZ+fPrdfW0swkebRv3tPDhUNME8RCZHu1hti6Dh5FSE3y0G0upD2g0vvKG11S8wGNJWjE3/ACOVOHjF55vsVDCqrQ7NqLzcWciakhU0+QvjB3J5BVt77F8zhebNH5JKlr/D90QWS8=")
_SCHEMA_PG = """
-- Core tables
create table if not exists tenants (
  id text primary key,
  tenant_code text not null unique,
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists users (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  username text not null,
  role text not null check (role in ('admin','manager','auditor')),
  person_name text,
  password_salt text not null,
  password_iterations integer not null,
  password_hash text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tenant_id, username)
);
create index if not exists idx_users_tenant on users(tenant_id);

create table if not exists departments (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create index if not exists idx_departments_tenant on departments(tenant_id);

create table if not exists skills_catalog (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  skill_key text not null,
  skill_label text not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, skill_key)
);
create index if not exists idx_skills_tenant on skills_catalog(tenant_id);

create table if not exists dept_required_skills (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  department_name text not null,
  skill_key text not null,
  unique (tenant_id, department_name, skill_key)
);
create index if not exists idx_deptreq_tenant on dept_required_skills(tenant_id);

create table if not exists people (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  name text not null,
  department text not null,
  level text not null check (level in ('experienced','fresher')),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create index if not exists idx_people_tenant on people(tenant_id);

create table if not exists person_skills (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  person_name text not null,
  skill_key text not null,
  unique (tenant_id, person_name, skill_key)
);
create index if not exists idx_personskills_tenant on person_skills(tenant_id);

create table if not exists audits (
  audit_id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  title text,
  scope text,
  audited_department text not null,
  required_skills_json text not null default '[]',
  assigned_auditor text not null,
  auditor_level text not null default '',
  status text not null,
  created_by text not null,
  created_at timestamptz not null default now(),
  due_date text,
  reports_json text not null default '[]',
  report_submitted_at timestamptz,
  closed_at timestamptz,
  checklists_json text not null default '{}',
  checklist_extras_json text not null default '{}',
  pre_audit_answers_json text not null default '{}',
  plan_slot_notes text
);
create index if not exists idx_audits_tenant on audits(tenant_id);

create table if not exists audit_state (
  tenant_id text primary key references tenants(id) on delete cascade,
  busy_by_name_json text not null default '{}',
  audit_history_json text not null default '[]'
);

create table if not exists checklists_catalog (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  department text not null,
  section text not null,
  item_order integer not null,
  item_text text not null,
  item_level text not null default 'main',
  parent_order integer,
  unique (tenant_id, department, section, item_order)
);
create index if not exists idx_chk_tenant on checklists_catalog(tenant_id);

create table if not exists generated_final_reports (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  created_by text not null,
  created_at timestamptz not null default now(),
  summary text not null,
  audit_ids_json text not null,
  allowed_users_json text not null,
  pdf_rel_path text not null,
  is_deleted boolean not null default false,
  deleted_at timestamptz,
  deleted_by text
);
create index if not exists idx_finalreports_tenant on generated_final_reports(tenant_id);
create index if not exists idx_finalreports_createdat on generated_final_reports(created_at);

-- Audit calendar & planning tables
create table if not exists audit_calendar (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  title text not null,
  scope text not null,
  start_date text not null,
  end_date text not null,
  created_by text not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_calendar_tenant on audit_calendar(tenant_id);

create table if not exists audit_plans (
  plan_id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  calendar_audit_id text not null references audit_calendar(id) on delete cascade,
  working_days integer not null,
  created_by text not null,
  plan_json text not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (tenant_id, calendar_audit_id)
);
create index if not exists idx_audit_plans_tenant on audit_plans(tenant_id);

create table if not exists audit_plan_slots (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  plan_id text not null references audit_plans(plan_id) on delete cascade,
  plan_date text not null,
  slot_start text not null,
  slot_end text not null,
  department text not null,
  auditor_name text,
  notes text,
  audit_id text,
  unique (tenant_id, plan_id, plan_date, slot_start)
);
create index if not exists idx_audit_plan_slots_tenant on audit_plan_slots(tenant_id);
create index if not exists idx_audit_plan_slots_plan on audit_plan_slots(plan_id);
"""

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

_db_initialized = False
_db_init_lock = threading.Lock()

def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        if USE_POSTGRES:
            stmts = [s.strip() for s in _SCHEMA_PG.split(";") if s.strip() and not s.strip().startswith("--")]
            for st in stmts:
                try: _execute(st + ";")
                except Exception: pass
        else:
            _executescript(_SCHEMA)
        migrate_db()
        _db_initialized = True

def migrate_db() -> None:
    if USE_POSTGRES:
        # Ensure extra columns exist on Postgres too (idempotent)
        for tbl, col, defn in [
            ("audits", "auditor_level",          "text not null default ''"),
            ("audits", "checklists_json",         "text not null default '{}'"),
            ("audits", "checklist_extras_json",   "text not null default '{}'"),
            ("audits", "pre_audit_answers_json",  "text not null default '{}'"),
            ("audits", "plan_slot_notes",         "text"),
            ("checklists_catalog", "item_level",  "text not null default 'main'"),
            ("checklists_catalog", "parent_order","integer"),
            ("audit_plan_slots",   "audit_id",    "text"),
        ]:
            try: _ensure_column(tbl, col, defn)
            except Exception: pass
        return
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
    # audit_plan_slots extra column
    try: _ensure_column("audit_plan_slots", "audit_id", "text")
    except Exception: pass
    # audits extra columns
    try: _ensure_column("audits", "auditor_level",        "text not null default ''")
    except Exception: pass
    try: _ensure_column("audits", "checklists_json",       "text not null default '{}'")
    except Exception: pass
    try: _ensure_column("audits", "checklist_extras_json", "text not null default '{}'")
    except Exception: pass
    try: _ensure_column("audits", "pre_audit_answers_json", "text not null default '{}'")
    except Exception: pass
    try: _ensure_column("audits", "plan_slot_notes",       "text")
    except Exception: pass
    # checklist hierarchy support
    try: _ensure_column("checklists_catalog", "item_level",   "text not null default 'main'")
    except Exception: pass
    try: _ensure_column("checklists_catalog", "parent_order", "integer")
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


def ensure_seed_files(tenant_code: str = "", tenant_name: str = "") -> str:
    init_db(); ensure_dirs()
    tenant_code = _normalize_text(tenant_code).lower() or DEFAULT_TENANT_CODE
    tenant_id = ensure_tenant(tenant_code, tenant_name)
    _tenant_generated_reports_dir(tenant_id)
    for d in DEFAULT_DEPARTMENTS: add_department_to_catalog(d, tenant_id=tenant_id)
    for k, v in DEFAULT_SKILLS.items(): ensure_skill_key_exists(k, fallback_label=v, tenant_id=tenant_id)
    for dept, keys in DEFAULT_DEPT_REQUIRED_SKILLS.items(): set_dept_required_skills(dept, keys, tenant_id=tenant_id)
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

# ═══════════════════════════════════════════════════════════════════════════════
# ISO 13485:2016 CLAUSE-DRIVEN DYNAMIC QUESTION GENERATION
# Questions are generated based on 4 pre-audit answers (Yes/No)
# and reference specific ISO 13485 clauses.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Pre-audit classification questions ────────────────────────────────────────
PRE_AUDIT_QUESTIONS = [
    {"id": "is_implantable", "text": "Is the product an implantable medical device?",
     "clause_ref": "3.6, 7.5.9.2, 8.2.6"},
    {"id": "is_sterile", "text": "Is the product a sterile medical device?",
     "clause_ref": "3.20, 7.5.2, 7.5.5, 7.5.6, 7.5.7"},
    {"id": "requires_installation", "text": "Does the product require installation?",
     "clause_ref": "7.5.3"},
    {"id": "requires_servicing", "text": "Does the product require servicing?",
     "clause_ref": "7.5.4"},
]

# ── Production question bank ────────────────────────────────────────────────
_ISO_CLAUSE_QUESTIONS: List[Dict[str, Any]] = [
    {"clause": "7.5.1(a)", "condition": "always", "section": "Production Control",
     "main": "Are documented procedures and methods for the control of production available and followed?",
     "subs": ["Is there a documented production procedure or work instruction for this product?",
              "Is the current revision of the procedure available at the point of use?",
              "Are operators following the documented procedure as observed during the audit?"]},
    {"clause": "7.5.1(b)", "condition": "always", "section": "Production Control",
     "main": "Is the infrastructure qualified for the production of this medical device?",
     "subs": ["Is there evidence of equipment qualification such as IQ, OQ, or PQ for critical production equipment?",
              "Are qualification records current and approved?"]},
    {"clause": "7.5.1(c)", "condition": "always", "section": "Production Control",
     "main": "Is monitoring and measurement of process parameters and product characteristics implemented?",
     "subs": ["Are in-process monitoring parameters defined and recorded?",
              "Are acceptance criteria documented for each monitoring point?",
              "Are out-of-specification results investigated and documented?"]},
    {"clause": "7.5.1(d)", "condition": "always", "section": "Production Control",
     "main": "Are monitoring and measuring equipment available and used as required?",
     "subs": ["Is the measuring equipment identified and within its calibration validity period?",
              "Is the calibration status clearly visible on the equipment label or tag?"]},
    {"clause": "7.5.1(e)", "condition": "always", "section": "Production Control",
     "main": "Are defined operations for labelling and packaging implemented?",
     "subs": ["Is the labelling verified against the approved label artwork before application?",
              "Is there a label reconciliation for issued, used, and destroyed labels?",
              "Does the label include all mandatory regulatory information such as UDI, symbols, and expiry?"]},
    {"clause": "7.5.1(f)", "condition": "always", "section": "Production Control",
     "main": "Are product release, delivery, and post-delivery activities implemented as defined?",
     "subs": ["Is there documented evidence that all release criteria were met before product dispatch?",
              "Is the identity of the person authorizing release recorded?"]},
    {"clause": "7.5.1", "condition": "always", "section": "Production Control",
     "main": "Is a record established and maintained for each batch that provides traceability and identifies the amount manufactured and approved for distribution?",
     "subs": ["Does the batch record include the batch or lot number and manufacturing dates?",
              "Is the quantity manufactured versus quantity approved for distribution recorded and reconciled?",
              "Is the batch record verified and approved by authorized personnel?"]},
    {"clause": "4.2.4", "condition": "always", "section": "Document Control",
     "main": "Are documents required by the quality management system controlled per clause 4.2.4?",
     "subs": ["Are production documents reviewed and approved for adequacy prior to issue?",
              "Is the current revision status of documents identified and available at points of use?",
              "Are obsolete documents prevented from unintended use?",
              "Is there a master list or equivalent document control system showing current document revisions?"]},
    {"clause": "4.2.5", "condition": "always", "section": "Record Control",
     "main": "Are records maintained to provide evidence of conformity to requirements per clause 4.2.5?",
     "subs": ["Are production records legible, readily identifiable, and retrievable?",
              "Is the retention time for production records defined and compliant with regulatory requirements?",
              "Are records stored securely to prevent damage, deterioration, or loss?",
              "Are methods defined for protecting confidential health information in records?"]},
    {"clause": "7.5.9.2", "condition": "is_implantable", "section": "Implantable Device Traceability",
     "main": "Are traceability records maintained for components, materials, and conditions of the work environment used for this implantable device?",
     "subs": ["Do traceability records include records of components and materials used in this batch?",
              "Are conditions of the work environment recorded if they could affect the device meeting its safety and performance requirements?",
              "Are suppliers of distribution services or distributors required to maintain records for traceability?",
              "Are records of the name and address of the shipping package consignee maintained?"]},
    {"clause": "8.2.6", "condition": "is_implantable", "section": "Implantable Device Inspection",
     "main": "Is the identity of personnel performing any inspection or testing of this implantable device recorded?",
     "subs": ["Does the inspection record identify the specific person who performed the test?",
              "Is there documented evidence that all acceptance criteria were met at each inspection stage?",
              "Is the test equipment used for measurement activities identified in the records?"]},
    {"clause": "7.5.2", "condition": "is_sterile", "section": "Sterile Product Cleanliness",
     "main": "Are requirements for cleanliness of product documented as required before sterilization?",
     "subs": ["Is there a documented cleaning procedure for the product prior to sterilization?",
              "Are cleaning validation records available and current?",
              "Are process agents removed from the product during manufacture as documented?"]},
    {"clause": "7.5.5", "condition": "is_sterile", "section": "Sterilization Records",
     "main": "Are records of sterilization process parameters maintained for each sterilization batch?",
     "subs": ["Are sterilization records traceable to each production batch of medical devices?",
              "Do sterilization records include all defined critical process parameters such as temperature, time, and pressure?",
              "Are sterilization cycle records reviewed and approved by authorized personnel?"]},
    {"clause": "7.5.6", "condition": "is_sterile", "section": "Process Validation (Sterile)",
     "main": "Are processes for production validated where the resulting output cannot be verified by subsequent monitoring or measurement?",
     "subs": ["Is there a documented validation protocol with defined criteria for review and approval?",
              "Is equipment qualification and qualification of personnel documented?",
              "Are specific methods, procedures, and acceptance criteria documented?",
              "Are revalidation criteria defined and followed?",
              "Are records of validation results and conclusions maintained?"]},
    {"clause": "7.5.7", "condition": "is_sterile", "section": "Sterilization Validation",
     "main": "Are processes for sterilization and sterile barrier systems validated prior to implementation?",
     "subs": ["Is there a documented procedure for validation of sterilization processes?",
              "Is the sterilization validation report approved and current?",
              "Has revalidation been performed following any product or process changes?",
              "Are results and conclusions of validation maintained as records?"]},
    {"clause": "7.5.3", "condition": "requires_installation", "section": "Installation Activities",
     "main": "Are requirements for medical device installation and acceptance criteria for verification of installation documented?",
     "subs": ["If installation is performed by an external party, are documented requirements provided to them?",
              "Are records of medical device installation and verification of installation maintained?",
              "Do installation records confirm that all acceptance criteria were met?"]},
    {"clause": "7.5.4", "condition": "requires_servicing", "section": "Servicing Activities",
     "main": "Are servicing procedures, reference materials, and reference measurements documented as necessary?",
     "subs": ["Are records of servicing activities analysed to determine if the information should be handled as a complaint?",
              "Are servicing records used as input to the improvement process where appropriate?",
              "Are records of servicing activities carried out by the organization or its supplier maintained?"]},
    {"clause": "7.5.6", "condition": "always", "section": "Process Validation",
     "main": "Are production processes validated where the resulting output cannot be verified by subsequent monitoring or measurement?",
     "subs": ["Are validation procedures documented with defined criteria for review and approval of the processes?",
              "Is there documented evidence of equipment qualification and personnel qualification?",
              "Are specific methods, procedures, and acceptance criteria used for validation?",
              "Are revalidation criteria defined, including when revalidation is triggered?"]},
    {"clause": "7.5.8", "condition": "always", "section": "Product Identification",
     "main": "Is the product identified by suitable means throughout product realization?",
     "subs": ["Is product status with respect to monitoring and measurement requirements identified throughout production, storage, installation, and servicing?",
              "Is there a system to assign unique device identification if required by regulatory requirements?",
              "Are procedures documented to ensure returned medical devices are identified and distinguished from conforming product?"]},
    {"clause": "7.5.9.1", "condition": "always", "section": "Traceability",
     "main": "Are procedures for traceability documented defining the extent of traceability in accordance with applicable regulatory requirements?",
     "subs": ["Are traceability records maintained as required?",
              "Can the product be traced from raw material receipt through production to distribution?"]},
    {"clause": "7.5.10", "condition": "always", "section": "Customer Property",
     "main": "Is customer property identified, verified, protected, and safeguarded while under the organization's control?",
     "subs": ["If any customer property is lost, damaged, or found unsuitable for use, is it reported to the customer and are records maintained?"]},
    {"clause": "7.5.11", "condition": "always", "section": "Product Preservation",
     "main": "Are procedures for preserving the conformity of product during processing, storage, handling, and distribution documented?",
     "subs": ["Is suitable packaging and shipping container design defined?",
              "Are requirements for special conditions documented if packaging alone cannot provide preservation?",
              "Are special conditions controlled and recorded if required?"]},
    {"clause": "7.6", "condition": "always", "section": "Monitoring & Measuring Equipment",
     "main": "Is monitoring and measuring equipment calibrated or verified at specified intervals or prior to use against measurement standards traceable to international or national standards?",
     "subs": ["Are calibration or verification results recorded?",
              "Is the equipment adjusted or re-adjusted as necessary with adjustments recorded?",
              "Is the equipment identified to determine its calibration status?",
              "Is the equipment safeguarded from adjustments that would invalidate the measurement result?",
              "Is the equipment protected from damage and deterioration during handling, maintenance, and storage?",
              "Is the validity of previous measuring results assessed and recorded when equipment is found not conforming to requirements?"]},
    {"clause": "8.2.6", "condition": "always", "section": "Product Monitoring & Measurement",
     "main": "Are the characteristics of the product monitored and measured to verify that product requirements have been met?",
     "subs": ["Is this carried out at applicable stages of the product realization process in accordance with planned and documented arrangements?",
              "Is evidence of conformity to acceptance criteria maintained with the identity of the person authorizing release recorded?",
              "Does product release proceed only after planned and documented arrangements have been satisfactorily completed?"]},
    {"clause": "8.3.1", "condition": "always", "section": "Nonconforming Product Control",
     "main": "Is product that does not conform to product requirements identified and controlled to prevent its unintended use or delivery?",
     "subs": ["Is there a documented procedure defining controls, responsibilities, and authorities for identification, documentation, segregation, evaluation, and disposition of nonconforming product?",
              "Is the evaluation of nonconformity including determination of the need for investigation documented?",
              "Are records of the nature of nonconformities, subsequent actions taken, evaluations, investigations, and rationale for decisions maintained?"]},
    {"clause": "8.3.2", "condition": "always", "section": "Nonconforming Product Control",
     "main": "Are nonconforming products detected before delivery dealt with by taking action to eliminate the detected nonconformity, preclude its original intended use, or authorize its use under concession?",
     "subs": ["Is nonconforming product accepted by concession only when justification is provided, approval is obtained, and applicable regulatory requirements are met?",
              "Are records of acceptance by concession and the identity of the person authorizing the concession maintained?"]},
    {"clause": "8.3.3", "condition": "always", "section": "Nonconforming Product Control",
     "main": "When nonconforming product is detected after delivery or use has started, is action taken appropriate to the effects of the nonconformity?",
     "subs": ["Are procedures for issuing advisory notices documented in accordance with applicable regulatory requirements?",
              "Are records of actions relating to the issuance of advisory notices maintained?"]},
]

_DEPARTMENT_DIRECT_CHECKLISTS: Dict[str, List[Dict[str, Any]]] = {
    "purchase": [
        {"clause": "7.4.1", "section": "Supplier Selection and Evaluation",
         "main": "Is the supplier selection criteria defined using a documented risk-based approach?",
         "subs": ["Are suppliers classified based on product or process risk?",
                  "Does the selection criteria consider impact on device quality, patient safety, and regulatory compliance?",
                  "Is the rationale for supplier approval documented before the supplier is added to the approved supplier list?"]},
        {"clause": "7.4.1", "section": "Supplier Selection and Evaluation",
         "main": "Is the supplier rating method defined and implemented using a risk-based approach?",
         "subs": ["Are rating parameters such as quality, delivery, responsiveness, and certification status weighted according to supplier risk?",
                  "Are critical suppliers reviewed more rigorously or more frequently than low-risk suppliers?",
                  "Are supplier rating results used to determine approval status, intensified control, or disqualification?"]},
        {"clause": "7.4.1", "section": "Supplier Selection and Evaluation",
         "main": "Are supplier control methods defined according to supplier risk and purchased product criticality?",
         "subs": ["Are controls such as audits, incoming inspection, certificate review, or first article verification selected based on risk?",
                  "Are changes to supplier controls triggered by poor performance, complaints, or nonconformities?",
                  "Are outsourced processes controlled at a level proportionate to their effect on product conformity?"]},
        {"clause": "7.4.1", "section": "Supplier Agreements and Controls",
         "main": "Are supplier quality agreements established where required?",
         "subs": ["Do supplier quality agreements clearly define quality responsibilities, change notification, and record retention requirements?",
                  "Are agreements in place for critical suppliers or outsourced processes affecting conformity of the medical device?",
                  "Are agreements reviewed and approved by authorized personnel before use?"]},
        {"clause": "4.2.4", "section": "Document Control",
         "main": "Are supplier qualification, rating, and control procedures documented and controlled?",
         "subs": ["Are current revisions of supplier evaluation procedures available to the purchasing and quality teams?",
                  "Are obsolete supplier forms or approval criteria prevented from unintended use?"]},
        {"clause": "4.2.5", "section": "Record Control",
         "main": "Are supplier evaluation, approval, and monitoring records maintained and retrievable?",
         "subs": ["Are records retained for the required retention period?",
                  "Can the organization retrieve supplier approval history, audit reports, and rating trends when needed?"]},
        {"clause": "7.4.2", "section": "Purchasing Information and Orders",
         "main": "Is there a documented purchasing procedure defining how purchasing information is prepared, reviewed, and communicated to suppliers?",
         "subs": ["Does the procedure define required information such as specifications, drawings, acceptance criteria, and quality requirements?",
                  "Are applicable regulatory or quality management requirements communicated to suppliers where necessary?"]},
        {"clause": "7.4.2", "section": "Purchasing Information and Orders",
         "main": "Are purchase orders reviewed and approved for adequacy before release to the supplier?",
         "subs": ["Does the review verify that the purchase order matches approved specifications and supplier status?",
                  "Are only authorized personnel allowed to approve or release purchase orders?",
                  "Are changes to purchase orders reviewed and approved in the same controlled manner?"]},
        {"clause": "7.5.1", "section": "Link to Production and Process Controls",
         "main": "Does purchasing information support downstream production and service provision requirements under clause 7.5?",
         "subs": ["Do purchased materials or outsourced services include requirements necessary for production control, validation, or preservation?",
                  "Where special handling, cleanliness, or traceability is required, is it defined in the purchasing documentation?"]},
        {"clause": "7.4.3", "section": "Incoming Inspection and Verification",
         "main": "Are incoming inspection plans and verification methods defined according to the type and risk of purchased product?",
         "subs": ["Do incoming inspection plans define sample size, inspection or test method, and acceptance criteria?",
                  "Are verification methods appropriate for raw materials, components, labels, packaging, and outsourced services as applicable?",
                  "Are critical purchased products subject to enhanced verification where risk justifies it?"]},
        {"clause": "7.4.3", "section": "Incoming Inspection and Verification",
         "main": "Are incoming inspection results documented and linked to disposition decisions?",
         "subs": ["Are acceptance, rejection, deviation, or concession decisions documented for incoming materials?",
                  "When incoming product fails requirements, is it controlled as nonconforming product under clause 8.3?"]},
        {"clause": "8.2.5", "section": "Monitoring of Purchasing Process",
         "main": "Is supplier performance monitored and analysed as part of process monitoring?",
         "subs": ["Are trends such as on-time delivery, incoming rejection rate, and response to issues reviewed periodically?",
                  "Are poor supplier performance trends escalated for action or management review when necessary?"]},
        {"clause": "8.3", "section": "Nonconforming Purchased Product",
         "main": "When purchased product does not meet requirements, is it identified and controlled to prevent unintended use?",
         "subs": ["Are supplier-related nonconformities documented and investigated?",
                  "Are supplier corrective actions requested when needed and is follow-up documented?"]},
        {"clause": "8.4 / 8.5", "section": "Data Analysis and Improvement",
         "main": "Are supplier performance data analysed and used to drive improvement?",
         "subs": ["Does the organization use supplier rating, incoming inspection data, complaints, or NCR data to identify purchasing risks?",
                  "Are actions arising from supplier performance analysis tracked to closure and checked for effectiveness?"]},
    ],
    "hr": [
        {"clause": "6.2.2", "section": "Competence Framework",
         "main": "Are necessary competence, skills, education, and experience defined for personnel performing work affecting product quality?",
         "subs": ["Are role descriptions available and do they define responsibilities and competence requirements?",
                  "Are roles and responsibilities communicated to relevant personnel?",
                  "Are competence requirements linked to actual process responsibilities and risk to product quality?"]},
        {"clause": "6.2.2", "section": "Competence Framework",
         "main": "Does the organization have a defined method to identify skill and competency gaps?",
         "subs": ["Are tools such as skill matrices, competency assessments, observation, audit findings, or performance reviews used to identify gaps?",
                  "Are gaps identified during onboarding, role change, or periodic review?",
                  "Are gaps documented and reviewed by responsible functions?"]},
        {"clause": "6.2.2", "section": "Training and Gap Closure",
         "main": "Does the organization have defined methods to fill identified competency gaps?",
         "subs": ["Are training, coaching, qualification, supervised practice, or reassignment used as appropriate to close gaps?",
                  "Are action plans documented with responsible person and target completion date?",
                  "Is effectiveness of the gap-closing action evaluated after completion?"]},
        {"clause": "6.2.2", "section": "Risk-Based Competence Planning",
         "main": "Is a risk-based approach used when planning competency development or assigning personnel to activities?",
         "subs": ["Are personnel performing high-risk or special process activities subject to stricter competence requirements?",
                  "When competence gaps could affect product conformity or regulatory compliance, are interim controls defined?",
                  "Is the level of training or qualification proportional to the impact of the role on process output?"]},
        {"clause": "7.5.1 / 7.5.6", "section": "Link to Production and Service Provision",
         "main": "Are competence requirements linked to activities under clause 7.5 where personnel performance can affect process output?",
         "subs": ["For production, inspection, validation, servicing, or installation roles, is competency evidence available before independent work is allowed?",
                  "Are only qualified personnel allowed to perform activities where output cannot be fully verified later?"]},
        {"clause": "4.2.4", "section": "Document Control",
         "main": "Are HR and training procedures, job descriptions, and competency criteria documented and controlled?",
         "subs": ["Are current revisions available at point of use to managers and HR personnel?",
                  "Are obsolete job descriptions, training forms, or competency criteria prevented from unintended use?"]},
        {"clause": "4.2.5", "section": "Record Control",
         "main": "Are records of education, training, skills, experience, and competency maintained and retrievable?",
         "subs": ["Are training records complete with date, trainer, topic, and participant evidence?",
                  "Are competency or qualification records retained for the required retention period?"]},
        {"clause": "8.2.5", "section": "Process Monitoring",
         "main": "Is the effectiveness of the competence and training process monitored?",
         "subs": ["Are metrics such as training completion, overdue training, assessment results, or requalification status reviewed periodically?",
                  "Are delays or failures in competency development escalated when they can affect process performance?"]},
        {"clause": "8.2.6", "section": "Link to Product Quality",
         "main": "Where human performance affects product conformity, is there evidence that competent personnel performed the relevant work or inspection?",
         "subs": ["Can the organization identify who performed the work and whether the person was qualified at that time?",
                  "Where required, are personnel identities captured in inspection, release, or batch records?"]},
        {"clause": "8.4", "section": "Data Analysis",
         "main": "Are data from audits, deviations, complaints, CAPAs, and performance reviews used to identify competence-related trends?",
         "subs": ["Are recurring human error trends analysed to determine whether additional training or qualification controls are needed?",
                  "Are competence-related issues reviewed in management review or process review meetings?"]},
        {"clause": "8.5", "section": "Improvement",
         "main": "When competence-related issues are identified, are corrective actions implemented and checked for effectiveness?",
         "subs": ["Are root causes analysed before deciding retraining or other actions?",
                  "Is recurrence checked after corrective action closure to confirm effectiveness?"]},

    ],
    "quality assurance": [
        {"clause": "4.2.4 / 4.2.5", "section": "Document and Record Control",
         "main": "Is there a documented procedure for control of documents and records?",
         "subs": ["Are documents and records identifiable, legible and retrievable?",
                  "Are documents and records reviewed and approved as per the documented procedure?",
                  "Are document changes recorded with necessary revision history, approvals?",
                  "Are obsolete documents retained till the lifetime of the medical devices or as per regulatory requirements, whichever is higher?",
                  "Are records pertaining to design, manufacturing, testing retained till the lifetime of the medical device or as per regulatory requirements, whichever is higher?"]},
        {"clause": "4.1", "section": "QMS Processes",
         "main": "Are all processes and their interactions identified and documented?",
         "subs": ["Are process risks identified and monitoring methods set based on a risk-based approach?"]},
        {"clause": "4.2.2", "section": "Quality Manual",
         "main": "Is a Quality Manual documented?",
         "subs": ["Is the scope, the exclusions and non-applicable clauses documented in the Quality Manual with justifications?"]},
        {"clause": "4.2.3", "section": "Medical Device Files",
         "main": "Are medical device files documented?",
         "subs": ["Is an adequate justification provided for their absence."]},
        {"clause": "8.2.4", "section": "Internal Audit",
         "main": "Are internal audits planned?",
         "subs": ["Are internal audits conducted as per plan and records maintained?",
                  "Are internal auditors competent and independent of the function they audit?",
                  "Are corrective actions taken without undue delay for the non-conformities identified?",
                  "Are corrective actions verified for their effectiveness?"]},
    ],
}

_DEPARTMENT_GENERATOR_CONFIG: Dict[str, Dict[str, Any]] = {
    "production": {
        "mode": "pre_audit",
        "title": "Pre-Audit Product Classification",
        "description": "Answer the following 4 questions to generate your ISO 13485 production checklist. The checklist will be customized based on the product type.",
        "button_label": "🚀 Generate Audit Checklist",
    },
    "purchase": {
        "mode": "direct",
        "title": "Purchase Checklist Generator",
        "description": "Generate a clause-focused ISO 13485 purchase checklist covering supplier selection, supplier controls, purchase orders, incoming inspection, and linked document and record controls.",
        "button_label": "🚀 Generate Purchase Checklist",
        "focus_lines": [
            "Primary focus: clauses 7.4.1, 7.4.2 and 7.4.3",
            "Linked clauses: 4.2.4, 4.2.5, 7.5 and section 8",
            "Includes supplier rating, supplier selection, supplier controls, supplier quality agreements, purchasing procedure, PO review, and incoming inspection methods",
        ],
    },
    "hr": {
        "mode": "direct",
        "title": "HR Checklist Generator",
        "description": "Generate a clause-focused ISO 13485 HR checklist covering competence, skills, gap identification, gap closure, risk-based competency planning, and links to process output.",
        "button_label": "🚀 Generate HR Checklist",
        "focus_lines": [
            "Primary focus: clause 6.2.2",
            "Linked clauses: 4.2.4, 4.2.5, 7.5 and section 8",
            "Includes identification of skills and competencies, role definition, gap identification, gap closure, and risk-based approach",
        ],
    },
    "quality assurance": {
        "mode": "direct",
        "title": "Quality Assurance Checklist Generator",
        "description": "Generate a clause-focused ISO 13485 quality assurance checklist covering document and record control, QMS processes, quality manual, medical device files, and internal audits.",
        "button_label": "🚀 Generate Quality Assurance Checklist",
        "focus_lines": [
            "Primary focus: clauses 4.1, 4.2.2, 4.2.3, 4.2.4, 4.2.5 and 8.2.4",
            "Uses Yes/No observation and CAPA follow-up when answer is No",
            "Includes document control, record retention, process interaction, quality manual, medical device files, and internal audit flow",
        ],
    },
    "top management": {
        "mode": "direct",
        "title": "Top Management Checklist Generator",
        "description": "Generate a clause-focused ISO 13485 top management checklist covering quality policy, quality objectives, responsibilities, management review, and management representative responsibilities.",
        "button_label": "🚀 Generate Top Management Checklist",
        "focus_lines": [
            "Primary focus: clauses 5.3, 5.4.1, 5.5.1, 5.5.2 and 5.6",
            "Includes conditional follow-up questions on communication, monitoring, and management review records",
            "Uses CAPA follow-up logic when observation is No",
        ],
    },
}


_TOP_MANAGEMENT_CHECKLIST: List[Dict[str, Any]] = [
    {"clause": "5.3", "section": "Quality Policy", "main": "Is the organization’s quality policy appropriate to its purpose and provides a framework to set quality objectives?",
     "subs": ["Is the quality policy effectively communicated within the organization?"]},
    {"clause": "5.4.1", "section": "Quality Objectives", "main": "Are measurable quality objectives set at different levels in the organization?",
     "subs": ["Are the quality objectives monitored regularly?"]},
    {"clause": "5.5.1", "section": "Responsibilities and Authorities", "main": "Are job responsibilities set and communicated to everyone in the organization?",
     "subs": []},
    {"clause": "5.6", "section": "Management Review", "main": "Are Management Review Meetings (MRM) planned and held periodically?",
     "subs": ["Do the management review discuss issues as mentioned in the ISO13485 and are records maintained?"]},
    {"clause": "5.6", "section": "Management Review", "main": "Is there a documented procedure for conducting management reviews?",
     "subs": []},
    {"clause": "5.5.2", "section": "Management Representative", "main": "Has a Management Representative been appointed and allotted responsibilities?",
     "subs": []},
]

def generate_top_management_checklist() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    return_order = _append_hierarchical_items(items, _TOP_MANAGEMENT_CHECKLIST, start_order=0)
    return items

def save_top_management_checklist(audit_id: str, *, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    dept = _normalize_text(a.get("audited_department", ""))
    if dept.lower() != "top management":
        return False, "This checklist generator is only for Top Management."
    generated_items = generate_top_management_checklist()
    sections_map: Dict[str, List[Dict[str, Any]]] = {}
    for item in generated_items:
        sec = item.get("section", "General")
        sections_map.setdefault(sec, []).append(item)
    checklists: Dict[str, Dict[str, List]] = a.get("checklists", {}) if isinstance(a.get("checklists"), dict) else {}
    checklists[dept] = {}
    for sec, sec_items in sections_map.items():
        rows = []
        for item in sec_items:
            rows.append({
                "sr_no": str(item["item_order"]),
                "checklist": f"[{item['clause_ref']}] {item['item_text']}",
                "observation": "",
                "evidence": "",
                "clause_no": item["clause_ref"],
                "item_level": item["item_level"],
                "parent_order": item["parent_order"],
            })
        checklists[dept][sec] = rows
    a["checklists"] = checklists
    a["pre_audit_answers"] = {"generated_for": "top_management"}
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, f"Checklist generated with {len(generated_items)} questions across {len(sections_map)} sections."

def _department_key(dept: str) -> str:
    return _normalize_text(dept).lower()

def get_department_generator_config(dept: str) -> Dict[str, Any]:
    dep_key = _department_key(dept)
    return dict(_DEPARTMENT_GENERATOR_CONFIG.get(dep_key, {
        "mode": "none",
        "title": "Checklist Generator",
        "description": "No dynamic generator is configured for this department.",
        "button_label": "Generate Checklist",
        "focus_lines": [],
    }))

def get_pre_audit_questions() -> List[Dict[str, Any]]:
    return list(PRE_AUDIT_QUESTIONS)

def _append_hierarchical_items(target: List[Dict[str, Any]], rows: List[Dict[str, Any]], start_order: int = 0) -> int:
    order = int(start_order)
    for q_def in rows:
        clause = q_def.get("clause", "")
        section = q_def.get("section", "General")
        main_text = q_def.get("main", "")
        subs = q_def.get("subs", []) or []
        order += 1
        parent_order = order
        target.append({
            "item_order": order,
            "item_text": main_text,
            "item_level": "main",
            "parent_order": None,
            "clause_ref": clause,
            "section": section,
        })
        for sub_text in subs:
            order += 1
            target.append({
                "item_order": order,
                "item_text": sub_text,
                "item_level": "sub",
                "parent_order": parent_order,
                "clause_ref": clause,
                "section": section,
            })
    return order

def generate_checklist_from_pre_audit(pre_audit_answers: Dict[str, bool]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    order = 0
    for q_def in _ISO_CLAUSE_QUESTIONS:
        cond = q_def.get("condition", "always")
        if cond == "always":
            include = True
        elif cond in pre_audit_answers:
            include = bool(pre_audit_answers.get(cond, False))
        else:
            include = False
        if not include:
            continue
        order = _append_hierarchical_items(items, [q_def], order)
    return items

def generate_department_checklist(dept: str, answers: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    dep_key = _department_key(dept)
    answers = answers or {}
    if dep_key == "production":
        return generate_checklist_from_pre_audit(answers)
    direct_rows = _DEPARTMENT_DIRECT_CHECKLISTS.get(dep_key, [])
    items: List[Dict[str, Any]] = []
    _append_hierarchical_items(items, direct_rows, 0)
    return items

def _save_generated_items_to_audit(a: Dict[str, Any], dept: str, answers_payload: Dict[str, Any], generated_items: List[Dict[str, Any]], *, tenant_id: str) -> Tuple[bool, str]:
    dept = _normalize_text(dept)
    if not generated_items:
        return False, f"No checklist blueprint configured for department '{dept}'."
    sections_map: Dict[str, List[Dict[str, Any]]] = {}
    for item in generated_items:
        sec = item.get("section", "General")
        sections_map.setdefault(sec, []).append(item)
    checklists: Dict[str, Dict[str, List]] = a.get("checklists", {}) or {}
    checklists[dept] = {}
    for sec, sec_items in sections_map.items():
        rows = []
        for item in sec_items:
            rows.append({
                "sr_no": str(item["item_order"]),
                "checklist": f"[{item['clause_ref']}] {item['item_text']}",
                "observation": "",
                "evidence": "",
                "clause_no": item["clause_ref"],
                "item_level": item["item_level"],
                "parent_order": item["parent_order"],
            })
        checklists[dept][sec] = rows
    a["pre_audit_answers"] = answers_payload
    a["checklists"] = checklists
    _save_updated_audit(a, tenant_id=tenant_id)
    return True, f"Checklist generated with {len(generated_items)} questions across {len(sections_map)} sections."

def save_generated_department_checklist(audit_id: str, answers: Optional[Dict[str, bool]] = None, *, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    dept = _normalize_text(a.get("audited_department", ""))
    dep_key = _department_key(dept)
    answers = answers or {}
    if dep_key == "production":
        return save_pre_audit_answers(audit_id, answers, tenant_id=tenant_id)
    generated_items = generate_department_checklist(dept, answers)
    answers_payload = {"generator_department": dep_key, "generated_at": _now_iso()}
    return _save_generated_items_to_audit(a, dept, answers_payload, generated_items, tenant_id=tenant_id)

def save_pre_audit_answers(
    audit_id: str,
    answers: Dict[str, bool],
    *,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    dept = _normalize_text(a.get("audited_department", ""))
    generated_items = generate_checklist_from_pre_audit(answers or {})
    return _save_generated_items_to_audit(a, dept, answers or {}, generated_items, tenant_id=tenant_id)

def get_pre_audit_answers(audit_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, bool]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return None
    return a.get("pre_audit_answers")

def get_generated_sections(audit_id: str, dept: str, *, tenant_id: Optional[str] = None) -> List[str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return []
    dept_n = _normalize_text(dept)
    saved = (a.get("checklists") or {}).get(dept_n, {})
    return list(saved.keys()) if isinstance(saved, dict) else []
# ── Keep CHECKLIST_CATALOG minimal for backward compat ────────────────────────


PURCHASE_SAMPLE_SIZE_QUESTION = "Do incoming inspection plans define sample size, inspection or test method, and acceptance criteria?"
PURCHASE_CROSS_Q1 = "Is the sample size statistically justified?"
PURCHASE_CROSS_Q2 = "Has this deviation been identified internally and any correction or CAPA planned?"
CHECKLIST_CATALOG: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
    "Production": {},
    "Purchase": {},
    "HR": {},
}

def _catalog_key(s: str) -> str:
    """Normalize department/section name for catalog lookup."""
    return " ".join(str(s or "").strip().split())

def get_sections_for_department(dept: str, tenant_id: Optional[str] = None, audit_id: Optional[str] = None) -> List[str]:
    """Return sections for a department.

    For audit runtime, use only the generated checklist saved inside the audit record.
    For admin checklist-library editing, keep DB access available when audit_id is not provided.
    """
    if audit_id:
        try:
            tid = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
            return get_generated_sections(audit_id, dept, tenant_id=tid)
        except Exception:
            return []

    key = _catalog_key(dept)
    for cat_dept, sections in CHECKLIST_CATALOG.items():
        if _catalog_key(cat_dept) == key and sections:
            return list(sections.keys())
    try:
        tid = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
        return [str(r["section"]) for r in _fetch_all(
            "select section from checklists_catalog where tenant_id = ? and department = ? group by section order by lower(section);",
            (tid, _normalize_text(dept)))]
    except Exception:
        return []

def get_items_for_department_section(dept: str, section: str, tenant_id: Optional[str] = None) -> List[str]:
    """Return flat list of item texts — reads from hardcoded catalog first, DB as fallback."""
    items = get_hierarchical_items_for_section(dept, section, tenant_id=tenant_id)
    return [i["item_text"] for i in items]

def get_hierarchical_items_for_section(dept: str, section: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return items with hierarchy — reads from hardcoded catalog first, DB as fallback."""
    dept_key    = _catalog_key(dept)
    section_key = _catalog_key(section)
    # Check hardcoded catalog
    for cat_dept, sections in CHECKLIST_CATALOG.items():
        if _catalog_key(cat_dept) == dept_key:
            for cat_sec, items in sections.items():
                if _catalog_key(cat_sec) == section_key:
                    return [dict(i) for i in items]
    # Fallback: DB (for admin-added custom sections)
    try:
        tid = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
        rows = _fetch_all(
            "select item_order, item_text, item_level, parent_order from checklists_catalog "
            "where tenant_id = ? and department = ? and section = ? order by item_order;",
            (tid, _normalize_text(dept), _normalize_text(section))
        )
        return [{"item_order": int(r["item_order"] or 0), "item_text": str(r["item_text"] or "").strip(),
                 "item_level": str(r["item_level"] or "main").strip(),
                 "parent_order": int(r["parent_order"]) if r["parent_order"] is not None else None}
                for r in rows]
    except Exception:
        return []

def upsert_section_items_hierarchical(dept: str, section: str, items: List[Dict[str, Any]], tenant_id: Optional[str] = None) -> None:
    """Save hierarchical items to DB (used only for admin-added custom sections)."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    if not dept or not section: return
    _execute("delete from checklists_catalog where tenant_id = ? and department = ? and section = ?;", (tenant_id, dept, section))
    for idx, item in enumerate([i for i in (items or []) if str(i.get("item_text","")).strip()], start=1):
        txt   = str(item.get("item_text","")).strip()
        level = str(item.get("item_level","main")).strip() or "main"
        parent = item.get("parent_order")
        _execute(
            "insert into checklists_catalog (id, tenant_id, department, section, item_order, item_text, item_level, parent_order) values (?, ?, ?, ?, ?, ?, ?, ?);",
            (_uuid(), tenant_id, dept, section, idx, txt, level, parent)
        )



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

    generated_rows = (((a.get("checklists") or {}).get(dept) or {}).get(section) or [])
    generated_items = [str(r.get("checklist", "")).strip() for r in generated_rows if str(r.get("checklist", "")).strip()]

    seen: Set[str] = set()
    out = []
    for it in generated_items + get_checklist_extras(a, dept, section):
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
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

def change_username(username: str, new_username: str, current_password: str, *, tenant_id: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    username = _normalize_text(username).lower()
    new_username_clean = _normalize_username(new_username)
    if not username:
        return False, None, "Current username is required."
    if not new_username_clean:
        return False, None, "New username is required."
    if len(new_username_clean) < 3:
        return False, None, "New username must be at least 3 characters."
    if username == new_username_clean.lower():
        return False, None, "Please enter a different username."
    if not current_password:
        return False, None, "Current password is required."
    u = find_user(username, tenant_id=tenant_id)
    if not u:
        return False, None, "User not found."
    if not u.get("is_active", True):
        return False, None, "User is disabled."
    if not _verify_password_columns(current_password, u.get("password_salt"), u.get("password_iterations"), u.get("password_hash")):
        return False, None, "Current password is incorrect."
    if find_user(new_username_clean, tenant_id=tenant_id):
        return False, None, "That username already exists."
    _execute("update users set username = ? where tenant_id = ? and lower(username) = ?;", (new_username_clean, tenant_id, username))
    return True, new_username_clean, f"Username updated successfully to '{new_username_clean}'."

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
    return {
        "audit_id":            r["audit_id"],
        "title":               r["title"] or "",
        "scope":               r["scope"] or "",
        "audited_department":  r["audited_department"],
        "required_skills":     json.loads(r["required_skills_json"] or "[]"),
        "assigned_auditor":    r["assigned_auditor"],
        "auditor_level":       r.get("auditor_level") or "",
        "status":              r["status"],
        "created_by":          r["created_by"],
        "created_at":          str(r["created_at"] or ""),
        "due_date":            r["due_date"] or "",
        "reports":             json.loads(r["reports_json"] or "[]"),
        "report_submitted_at": str(r["report_submitted_at"] or ""),
        "closed_at":           str(r["closed_at"] or ""),
        "checklists":          json.loads(r.get("checklists_json") or "{}"),
        "checklist_extras":    json.loads(r.get("checklist_extras_json") or "{}"),
        "pre_audit_answers":   json.loads(r.get("pre_audit_answers_json") or "{}"),
        "plan_slot_notes":     r.get("plan_slot_notes") or "",
    }

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
    rsk_json  = json.dumps(updated.get("required_skills", []) or [])
    rep_json  = json.dumps(updated.get("reports", []) or [])
    chk_json  = json.dumps(updated.get("checklists", {}) or {})
    ext_json  = json.dumps(updated.get("checklist_extras", {}) or {})
    pre_json  = json.dumps(updated.get("pre_audit_answers", {}) or {})
    notes     = updated.get("plan_slot_notes") or None
    aid       = updated.get("audit_id", "")
    exists    = _fetch_one("select audit_id from audits where tenant_id = ? and audit_id = ?;", (tenant_id, aid))
    if exists:
        _execute(
            "update audits set title=?,scope=?,audited_department=?,required_skills_json=?,"
            "assigned_auditor=?,auditor_level=?,status=?,created_by=?,created_at=?,due_date=?,"
            "reports_json=?,report_submitted_at=?,closed_at=?,checklists_json=?,"
            "checklist_extras_json=?,pre_audit_answers_json=?,plan_slot_notes=? where audit_id=? and tenant_id=?;",
            (updated.get("title",""), updated.get("scope",""), updated.get("audited_department",""),
             rsk_json, updated.get("assigned_auditor",""), updated.get("auditor_level",""),
             updated.get("status",""), updated.get("created_by",""), updated.get("created_at",_now_iso()),
             updated.get("due_date",""), rep_json, updated.get("report_submitted_at","") or None,
             updated.get("closed_at","") or None, chk_json, ext_json, pre_json, notes, aid, tenant_id))
    else:
        _execute(
            "insert into audits (audit_id,tenant_id,title,scope,audited_department,required_skills_json,"
            "assigned_auditor,auditor_level,status,created_by,created_at,due_date,reports_json,"
            "report_submitted_at,closed_at,checklists_json,checklist_extras_json,pre_audit_answers_json,plan_slot_notes) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);",
            (aid or _new_audit_id(), tenant_id, updated.get("title",""), updated.get("scope",""),
             updated.get("audited_department",""), rsk_json, updated.get("assigned_auditor",""),
             updated.get("auditor_level",""), updated.get("status","Assigned"), updated.get("created_by",""),
             updated.get("created_at",_now_iso()), updated.get("due_date",""), rep_json,
             updated.get("report_submitted_at","") or None, updated.get("closed_at","") or None,
             chk_json, ext_json, pre_json, notes))


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

def _is_purchase_department_name(dept: str) -> bool:
    return _normalize_text(dept).lower() == "purchase"

def _is_top_management_department_name(dept: str) -> bool:
    return _normalize_text(dept).lower() == "top management"

def _is_quality_assurance_department_name(dept: str) -> bool:
    return _normalize_text(dept).lower() == "quality assurance"

def _is_maintenance_department_name(dept: str) -> bool:
    return _normalize_text(dept).lower() == "maintenance"

def _is_purchase_cross_question_text(text: str) -> bool:
    t = " ".join(str(text or "").split()).lower()
    return "do incoming inspection plans define sample size, inspection or test method, and acceptance criteria?" in t

def _effective_rows_for_validation(rows: List[Dict[str, Any]], dept: str) -> List[Dict[str, Any]]:
    dept_n = _normalize_text(dept)
    if not _is_top_management_department_name(dept_n):
        return [dict(r or {}) for r in (rows or []) if _normalize_text((r or {}).get("checklist", ""))]

    out: List[Dict[str, Any]] = []
    by_sr: Dict[str, Dict[str, Any]] = {}
    for idx, r in enumerate(rows or [], start=1):
        rr = dict(r or {})
        sr = str(rr.get("sr_no", idx)).strip() or str(idx)
        rr["sr_no"] = sr
        by_sr[sr] = rr

    for idx, r in enumerate(rows or [], start=1):
        rr = dict(r or {})
        chk = _normalize_text(rr.get("checklist", ""))
        if not chk:
            continue
        lvl = str(rr.get("item_level", "main") or "main").strip().lower()
        if lvl == "main":
            out.append(rr)
            continue
        parent_sr = str(_norm_parent(rr.get("parent_order")) or "")
        parent = by_sr.get(parent_sr)
        parent_obs = _normalize_text((parent or {}).get("observation", ""))
        if parent_obs == "yes":
            out.append(rr)
    return out

def _row_complete_for_validation(row: Dict[str, Any], dept: str) -> bool:
    obs = _normalize_text((row or {}).get("observation", ""))
    evd = _normalize_text((row or {}).get("evidence", ""))
    if not obs or not evd:
        return False
    branch = (row or {}).get("branch_answers") or {}
    if not isinstance(branch, dict):
        branch = {}

    if (_is_purchase_department_name(dept) or _is_top_management_department_name(dept) or _is_quality_assurance_department_name(dept) or _is_maintenance_department_name(dept)) and obs.lower() == "no":
        if not _normalize_text(branch.get("deviation_identified_capa_planned", "")):
            return False

    if _is_purchase_department_name(dept) and obs.lower() == "yes" and _is_purchase_cross_question_text((row or {}).get("checklist", "")):
        stat = _normalize_text(branch.get("sample_size_statistically_justified", ""))
        if not stat:
            return False
        if stat.lower() == "no" and not _normalize_text(branch.get("deviation_identified_capa_planned", "")):
            return False

    return True

def _validate_checklist_complete(audit: Dict[str, Any], tenant_id: str) -> Tuple[bool, str]:
    """Validate only the generated checklist rows that are actually active/visible for this audit path."""
    dept = _normalize_text(audit.get("audited_department", ""))
    if not dept:
        return False, "Audit department is missing."

    all_checklists = audit.get("checklists") or {}
    if not isinstance(all_checklists, dict):
        return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."

    saved = all_checklists.get(dept, {})
    if not isinstance(saved, dict) or not saved:
        return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."

    missing_sections: List[str] = []
    incomplete_examples: List[str] = []
    any_rows = False

    for sec, rows in saved.items():
        sec_name = _normalize_text(sec)
        if not sec_name:
            continue
        if not isinstance(rows, list) or not rows:
            missing_sections.append(sec_name or str(sec))
            continue

        rows_to_check = _effective_rows_for_validation(rows, dept)
        if not rows_to_check:
            missing_sections.append(sec_name or str(sec))
            continue

        any_rows = True
        for idx, r in enumerate(rows_to_check, start=1):
            rr = r or {}
            sr = str(rr.get("sr_no", idx)).strip() or str(idx)
            if not _row_complete_for_validation(rr, dept):
                incomplete_examples.append(f"{sec_name} (SR {sr})")
                break

    if not any_rows:
        return False, "Checklist is not filled yet. Please fill Observation and Evidence before submitting."
    if missing_sections:
        return False, "Checklist incomplete. No saved responses for sections: " + ", ".join(missing_sections)
    if incomplete_examples:
        sample = ", ".join(incomplete_examples[:5])
        more = f"  (+{len(incomplete_examples) - 5} more)" if len(incomplete_examples) > 5 else ""
        return False, f"Checklist incomplete. Fill Observation, Evidence, and required follow-up answers for every visible question. Incomplete examples: {sample}{more}"
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

def _norm_parent(val) -> Optional[int]:
    """Normalize parent_order to int or None — handles str, int, float, None."""
    if val is None: return None
    try:
        v = int(float(str(val)))
        return v if v > 0 else None
    except Exception:
        return None

def get_checklist_rows_for_audit_section(audit_id: str, dept: str, section: str, *, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    saved = load_audit_section_table(audit_id, dept, section, tenant_id=tenant_id)
        
    if saved and isinstance(saved, list):
        out: List[Dict[str, Any]] = []
        missing_hierarchy = False
        for idx, r in enumerate(saved, start=1):
            # sr_no must never be empty — fall back to enumerate index
            rr = dict(r or {})
            sr = str(rr.get("sr_no", "")).strip() or str(idx)
            item_level = rr.get("item_level")
            parent_order = rr.get("parent_order")
            if item_level is None and parent_order is None:
                missing_hierarchy = True
            row_out = dict(rr)
            row_out.update({
                "sr_no":        sr,
                "checklist":    str(rr.get("checklist", "")).strip(),
                "observation":  str(rr.get("observation", "") or "").strip(),
                "evidence":     str(rr.get("evidence", "") or "").strip(),
                "clause_no":    str(rr.get("clause_no", "") or "").strip(),
                "item_level":   str(rr.get("item_level", "main") or "main").strip() or "main",
                "parent_order": _norm_parent(rr.get("parent_order")),
            })
            out.append(row_out)
    
        # If the saved table is older (no hierarchy fields), rebuild it from the latest
        # hierarchical catalog for this dept/section; keep existing observations/evidence.
        if missing_hierarchy:
            hier_items = get_hierarchical_items_for_section(_normalize_text(dept), _normalize_text(section), tenant_id=tenant_id)
            if hier_items:
                # Map old answers by checklist text (best-effort)
                ans_map = {}
                for r in out:
                    key = " ".join(str(r.get("checklist", "")).split()).lower()
                    if key:
                        ans_map[key] = {"observation": r.get("observation", ""), "evidence": r.get("evidence", ""), "clause_no": r.get("clause_no", "")}
    
                rebuilt: List[Dict[str, Any]] = []
                for it in hier_items:
                    txt = str(it.get("item_text", "")).strip()
                    key = " ".join(txt.split()).lower()
                    prev = ans_map.get(key, {})
                    rebuilt.append({
                        "sr_no":        str(it.get("item_order")),
                        "checklist":    txt,
                        "observation":  str(prev.get("observation", "") or "").strip(),
                        "evidence":     str(prev.get("evidence", "") or "").strip(),
                        "clause_no":    str(prev.get("clause_no", "") or "").strip(),
                        "item_level":   str(it.get("item_level", "main") or "main").strip() or "main",
                        "parent_order": _norm_parent(it.get("parent_order")),
                    })
                return rebuilt
    
        return out
    hier_items = get_hierarchical_items_for_section(_normalize_text(dept), _normalize_text(section), tenant_id=tenant_id)
    if hier_items:
        return [{
            "sr_no":        str(item["item_order"]),
            "checklist":    str(item["item_text"] or "").strip(),
            "observation":  "",
            "evidence":     "",
            "item_level":   str(item["item_level"] or "main").strip() or "main",
            "parent_order": _norm_parent(item["parent_order"]),
        } for item in hier_items]
    # flat fallback (legacy sections with no hierarchy)
    items = get_items_for_department_section(_normalize_text(dept), _normalize_text(section), tenant_id=tenant_id) or []
    return [{
        "sr_no": str(i), "checklist": str(item).strip(),
        "observation": "", "evidence": "",
        "item_level": "main", "parent_order": None,
    } for i, item in enumerate(items, start=1)]

def get_checklist_progress(audit_id: str, dept: str, section: str, *, tenant_id: Optional[str] = None) -> Dict[str, int]:
    rows = get_checklist_rows_for_audit_section(audit_id, dept, section, tenant_id=tenant_id)
    main_rows = [r for r in rows if str(r.get("item_level","main")).strip() == "main"]
    total_main = len(main_rows)

    def _row_complete(r: Dict[str, Any]) -> bool:
        """A row is complete when both observation and evidence are non-empty."""
        return (bool(str(r.get("observation","") or "").strip())
                and bool(str(r.get("evidence","") or "").strip()))

    if total_main == 0:
        # flat (no hierarchy) — use sequential unlocking
        total = len(rows)
        completed_prefix = next((i for i, r in enumerate(rows) if not _row_complete(r)), total)
        return {
            "total":            total,
            "unlocked":         min(total, completed_prefix + 1) if total > 0 else 0,
            "completed_prefix": completed_prefix,
            "completed_any":    sum(1 for r in rows if _row_complete(r)),
            "total_rows":       total,
        }

    def _subtree_complete(main_row: Dict[str, Any]) -> bool:
        """True only when main question AND every sub AND every subsub are answered."""
        if not _row_complete(main_row): return False
        main_sr = _norm_parent(main_row.get("sr_no"))
        if main_sr is None: return False
        for sub in rows:
            if str(sub.get("item_level","")).strip() != "sub": continue
            if _norm_parent(sub.get("parent_order")) != main_sr: continue
            if not _row_complete(sub): return False
            sub_sr = _norm_parent(sub.get("sr_no"))
            if sub_sr is None: continue
            for ss in rows:
                if str(ss.get("item_level","")).strip() != "subsub": continue
                if _norm_parent(ss.get("parent_order")) != sub_sr: continue
                if not _row_complete(ss): return False
        return True

    # completed_prefix = consecutive fully-done mains from index 0
    completed_prefix = 0
    for mr in main_rows:
        if _subtree_complete(mr):
            completed_prefix += 1
        else:
            break

    # unlocked = all completed mains + the next one (so next Q is always visible)
    unlocked_main = min(total_main, completed_prefix + 1)
    completed_any = sum(1 for mr in main_rows if _subtree_complete(mr))

    return {
        "total":            total_main,
        "unlocked":         unlocked_main,
        "completed_prefix": completed_prefix,
        "completed_any":    completed_any,
        "total_rows":       len(rows),
    }

def save_single_checklist_response(audit_id: str, dept: str, section: str, sr_no: str, observation: str, evidence: str, *, clause_no: str = "", auditor_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    sr_no_s = str(sr_no or "").strip()
    if not sr_no_s: return False, "sr_no is required."
    dept_n, section_n = _normalize_text(dept), _normalize_text(section)
    rows = get_checklist_rows_for_audit_section(audit_id, dept_n, section_n, tenant_id=tenant_id)
    idx = next((i for i, r in enumerate(rows) if str(r.get("sr_no","")).strip() == sr_no_s), None)
    if idx is None:
        return False, f"Checklist row '{sr_no_s}' not found. Please reload the checklist."
    # Update only observation/evidence — all hierarchy fields (item_level, parent_order,
    # checklist text, sr_no) are preserved exactly as loaded from DB/catalog.
    rows[idx]["observation"]  = str(observation or "").strip()
    rows[idx]["evidence"]     = str(evidence or "").strip()
    rows[idx]["clause_no"]    = str(clause_no or "").strip()
    # Normalize hierarchy fields before writing back (guards against stale None types)
    rows[idx]["item_level"]   = str(rows[idx].get("item_level","main") or "main").strip() or "main"
    rows[idx]["parent_order"] = _norm_parent(rows[idx].get("parent_order"))
    rows[idx]["sr_no"]        = str(rows[idx].get("sr_no","")).strip() or sr_no_s
    if "branch_answers" in rows[idx] and not isinstance(rows[idx].get("branch_answers"), dict):
        rows[idx]["branch_answers"] = {}
    return save_audit_section_table(
        audit_id=audit_id, dept=dept_n, section=section_n,
        rows=rows, auditor_name=auditor_name, tenant_id=tenant_id
    )

def add_audit_section_checklist_item(audit_id: str, dept: str, section: str, checklist_text: str, auditor_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept, section = _normalize_text(dept), _normalize_text(section)
    checklist_text = (checklist_text or "").strip()
    if not checklist_text: return False, "Checklist point is required."
    existing = load_audit_section_table(audit_id, dept, section, tenant_id=tenant_id) or []
    rows = list(existing) if existing else [{"sr_no": str(i), "checklist": str(item).strip(), "observation": "", "evidence": ""} for i, item in enumerate(get_items_for_department_section(dept, section, tenant_id=tenant_id), start=1)]
    rows.append({"sr_no": str(len(rows) + 1), "checklist": checklist_text, "observation": "", "evidence": ""})
    return save_audit_section_table(audit_id=audit_id, dept=dept, section=section, rows=rows, auditor_name=auditor_name, tenant_id=tenant_id)



def save_checklist_row_branch_answers(
    audit_id: str,
    dept: str,
    section: str,
    sr_no: str,
    branch_answers: Dict[str, Any],
    *,
    auditor_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    sr_no_s = str(sr_no or "").strip()
    if not sr_no_s:
        return False, "sr_no is required."
    dept_n, section_n = _normalize_text(dept), _normalize_text(section)
    rows = get_checklist_rows_for_audit_section(audit_id, dept_n, section_n, tenant_id=tenant_id)
    idx = next((i for i, r in enumerate(rows) if str(r.get("sr_no","")).strip() == sr_no_s), None)
    if idx is None:
        return False, f"Checklist row '{sr_no_s}' not found. Please reload the checklist."
    rows[idx]["branch_answers"] = dict(branch_answers or {})
    return save_audit_section_table(
        audit_id=audit_id, dept=dept_n, section=section_n,
        rows=rows, auditor_name=auditor_name, tenant_id=tenant_id
    )
def validate_audit_checklists_complete(audit_id: str, tenant_id: Optional[str] = None) -> Tuple[bool, str]:
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return False, "Audit not found."
    return _validate_checklist_complete(a, tenant_id=tenant_id)

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

def list_all_plan_dates(tenant_id: str) -> List[Dict[str, Any]]:
    """Return all distinct plan_dates from audit_plan_slots for this tenant,
    joined with the calendar audit title so the calendar can highlight them."""
    init_db()
    rows = _fetch_all(
        "select distinct aps.plan_date, ac.title, ac.id as calendar_audit_id "
        "from audit_plan_slots aps "
        "join audit_plans ap on ap.plan_id = aps.plan_id and ap.tenant_id = aps.tenant_id "
        "join audit_calendar ac on ac.id = ap.calendar_audit_id and ac.tenant_id = aps.tenant_id "
        "where aps.tenant_id = ? "
        "order by aps.plan_date asc;",
        (tenant_id,))
    return [dict(r) for r in rows]

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


def create_recurring_audit_calendar(
    tenant_id: str,
    title: str,
    scope: str,
    year: int,
    start_month: int,
    frequency: str,
    created_by: str,
    start_day: int = 1,
    duration_days: int = 1,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    init_db()
    title = _normalize_text(title)
    scope = _normalize_text(scope)
    if not title:
        return False, [], "Audit title is required."
    if not scope:
        return False, [], "Scope is required."
    try:
        year = int(year); start_month = int(start_month); start_day = int(start_day); duration_days = int(duration_days)
    except Exception:
        return False, [], "Invalid year, month, day, or duration."
    if year < 2000 or year > 2100:
        return False, [], "Year is out of supported range."
    if start_month < 1 or start_month > 12:
        return False, [], "Start month must be between 1 and 12."
    if start_day < 1 or start_day > 28:
        return False, [], "Start day must be between 1 and 28."
    if duration_days <= 0:
        return False, [], "Duration must be at least 1 day."

    step_map = {"Monthly": 1, "Bi-monthly": 2, "Quarterly": 3, "Half-yearly": 6, "One-time": 12}
    step = step_map.get(str(frequency or "").strip(), 1)
    months = list(range(start_month, 13, step))
    if str(frequency or "").strip() == "One-time":
        months = months[:1]

    created_rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for month in months:
        try:
            sd = date(year, month, min(start_day, calendar.monthrange(year, month)[1]))
            ed = sd + timedelta(days=duration_days - 1)
            occ_title = f"{title} | {calendar.month_name[month]} {year}"
            row, msg = create_audit_calendar(
                tenant_id=tenant_id,
                title=occ_title,
                scope=scope,
                start_date=sd.isoformat(),
                end_date=ed.isoformat(),
                created_by=created_by,
            )
            if row:
                created_rows.append(row)
            else:
                errors.append(msg)
        except Exception as e:
            errors.append(str(e))

    if created_rows:
        msg = f"Created {len(created_rows)} audit(s)."
        if errors:
            msg += " Some occurrences failed."
        return True, created_rows, msg
    return False, [], errors[0] if errors else "Failed to create recurring audits."

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

def create_or_reset_audit_plan(
    tenant_id: str,
    calendar_audit_id: str,
    working_days: int,
    created_by: str,
    start_date_override: Optional[str] = None,
    custom_slots: Optional[List[tuple]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Create or reset an audit plan.

    Args:
        start_date_override: ISO date string (YYYY-MM-DD). If given, overrides the
                             calendar audit's start_date so the admin can pick any
                             date as the first audit day.
        custom_slots:        List of (slot_start, slot_end) tuples e.g.
                             [("09:00","10:00"), ("10:00","11:00")].
                             Falls back to AUDIT_PLAN_SLOTS if None.
    """
    init_db()
    if not working_days or int(working_days) <= 0:
        return None, "Duration (days) must be greater than 0."
    audit = get_audit_calendar(tenant_id, calendar_audit_id)
    if not audit:
        return None, "Selected audit not found."
    # Use override date if supplied, else fall back to audit's own start_date
    raw_date = start_date_override if start_date_override else audit.get("start_date")
    sd = _parse_iso_date(raw_date)
    if not sd:
        return None, "Audit start date is invalid. Please set a valid date."
    working_days = int(working_days)
    slots_to_use = custom_slots if custom_slots else AUDIT_PLAN_SLOTS

    existing = _fetch_one(
        "select plan_id from audit_plans where tenant_id=? and calendar_audit_id=? limit 1;",
        (tenant_id, calendar_audit_id))
    if existing:
        plan_id = existing["plan_id"]
        _execute(
            "update audit_plans set working_days=?, updated_at=? where tenant_id=? and plan_id=?;",
            (working_days, _now_iso(), tenant_id, plan_id))
        if "plan_json" in _table_columns("audit_plans"):
            try:
                _execute(
                    "update audit_plans set plan_json='{}' where tenant_id=? and plan_id=? "
                    "and (plan_json is null or plan_json='');",
                    (tenant_id, plan_id))
            except Exception:
                pass
        _execute(
            "delete from audit_plan_slots where tenant_id=? and plan_id=?;",
            (tenant_id, plan_id))
    else:
        plan_id = str(uuid.uuid4())
        cols = _table_columns("audit_plans")
        if "plan_json" in cols:
            _execute(
                "insert into audit_plans "
                "(plan_id, tenant_id, calendar_audit_id, working_days, created_by, plan_json) "
                "values (?, ?, ?, ?, ?, ?);",
                (plan_id, tenant_id, calendar_audit_id, working_days, created_by or "", "{}"))
        else:
            _execute(
                "insert into audit_plans "
                "(plan_id, tenant_id, calendar_audit_id, working_days, created_by) "
                "values (?, ?, ?, ?, ?);",
                (plan_id, tenant_id, calendar_audit_id, working_days, created_by or ""))

    for d in _next_working_days(sd, working_days):
        for s0, s1 in slots_to_use:
            _execute(
                "insert into audit_plan_slots "
                "(id, tenant_id, plan_id, plan_date, slot_start, slot_end, "
                "department, auditor_name, notes) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (str(uuid.uuid4()), tenant_id, plan_id,
                 d.isoformat(), s0, s1, "", None, None))

    return get_audit_plan_by_calendar_audit(tenant_id, calendar_audit_id), "Audit plan created."

def create_audit_plan_with_dates(
    tenant_id: str,
    calendar_audit_id: str,
    audit_dates: List[str],          # explicit ISO date strings chosen by admin
    created_by: str,
    custom_slots: Optional[List[tuple]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Create or reset an audit plan using a specific list of dates chosen by the admin."""
    init_db()
    if not audit_dates:
        return None, "Please select at least one audit date."
    audit = get_audit_calendar(tenant_id, calendar_audit_id)
    if not audit:
        return None, "Selected audit not found."
    slots_to_use = custom_slots if custom_slots else AUDIT_PLAN_SLOTS

    # parse & deduplicate dates, keep order
    parsed_dates = []
    seen = set()
    for ds in audit_dates:
        try:
            d = date.fromisoformat(str(ds))
            if d not in seen:
                seen.add(d)
                parsed_dates.append(d)
        except Exception:
            pass
    if not parsed_dates:
        return None, "No valid dates provided."
    parsed_dates.sort()

    working_days = len(parsed_dates)

    existing = _fetch_one(
        "select plan_id from audit_plans where tenant_id=? and calendar_audit_id=? limit 1;",
        (tenant_id, calendar_audit_id))
    if existing:
        plan_id = existing["plan_id"]
        _execute(
            "update audit_plans set working_days=?, updated_at=? where tenant_id=? and plan_id=?;",
            (working_days, _now_iso(), tenant_id, plan_id))
        _execute(
            "delete from audit_plan_slots where tenant_id=? and plan_id=?;",
            (tenant_id, plan_id))
    else:
        plan_id = str(uuid.uuid4())
        cols = _table_columns("audit_plans")
        if "plan_json" in cols:
            _execute(
                "insert into audit_plans "
                "(plan_id, tenant_id, calendar_audit_id, working_days, created_by, plan_json) "
                "values (?, ?, ?, ?, ?, ?);",
                (plan_id, tenant_id, calendar_audit_id, working_days, created_by or "", "{}"))
        else:
            _execute(
                "insert into audit_plans "
                "(plan_id, tenant_id, calendar_audit_id, working_days, created_by) "
                "values (?, ?, ?, ?, ?);",
                (plan_id, tenant_id, calendar_audit_id, working_days, created_by or ""))

    for d in parsed_dates:
        for s0, s1 in slots_to_use:
            _execute(
                "insert into audit_plan_slots "
                "(id, tenant_id, plan_id, plan_date, slot_start, slot_end, "
                "department, auditor_name, notes) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (str(uuid.uuid4()), tenant_id, plan_id,
                 d.isoformat(), s0, s1, "", None, None))

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


# ══════════════════════════════════════════════════════════════════════════════
# SMART QUESTION GENERATION — FREE, NO API KEY NEEDED
# Uses rule-based analysis of previous answers to generate follow-up questions
# ══════════════════════════════════════════════════════════════════════════════

import random as _random

# ── Keyword-based gap detection rules ─────────────────────────────────────────
_WEAKNESS_KEYWORDS = [
    "not available", "not found", "missing", "no record", "no evidence",
    "not maintained", "not documented", "not conducted", "not performed",
    "not reviewed", "not applicable", "n/a", "na", "nil", "none",
    "partially", "incomplete", "pending", "not yet", "in progress",
    "not verified", "not validated", "not approved", "not signed",
    "not calibrated", "expired", "overdue", "gap", "deviation",
    "non-conformance", "non-conformity", "ncr", "observation",
    "not compliant", "not aligned", "no procedure", "no sop",
]

_VAGUE_KEYWORDS = [
    "ok", "fine", "good", "satisfactory", "adequate", "yes", "done",
    "available", "maintained", "seen", "verified", "checked",
]

# ── Department-specific follow-up question templates (main + subs) ─────────────
# Each entry: { "main": "...", "subs": ["...", "..."] }
_DEPT_FOLLOWUP_TEMPLATES = {
    "production": {
        "record_accuracy": [
            {"main": "Can you cross-verify the batch quantity recorded in the BMR against the actual weighing/dispensing log?",
             "subs": ["Does the dispensing log show the tare weight, gross weight, and net weight for each raw material?",
                      "Is there a reconciliation of theoretical vs. actual yield documented?",
                      "Are any discrepancies between the BMR and weighing log explained with a deviation note?"]},
            {"main": "Is the environmental monitoring data (temperature, humidity) recorded during this batch within specification?",
             "subs": ["Are the environmental monitoring instruments calibrated and within validity?",
                      "Is there an out-of-range alert or deviation report if any reading exceeded the limit?"]},
            {"main": "Were any process deviations noted during this batch? If yes, is the deviation report attached?",
             "subs": ["Is the deviation classified as critical, major, or minor as per the SOP?",
                      "Is the root cause analysis documented for the deviation?",
                      "Was the impact assessment on product quality completed before batch release?"]},
            {"main": "Is the line clearance documented before batch start with all required checks?",
             "subs": ["Does the line clearance checklist include equipment cleanliness, label removal, and area verification?",
                      "Is the line clearance signed off by both the operator and the supervisor?"]},
            {"main": "Are the equipment cleaning records available for the equipment used in this batch?",
             "subs": ["Is the cleaning validation status current for the equipment type used?",
                      "Are swab/rinse test results documented for the last cleaning cycle?"]},
        ],
        "traceability": [
            {"main": "Can every raw material used in this batch be traced back to the vendor COA and incoming inspection report?",
             "subs": ["Is the vendor COA attached to the incoming inspection record for each lot?",
                      "Are the test results in the vendor COA cross-verified against the internal specification?",
                      "Is the incoming inspection acceptance/rejection decision documented?"]},
            {"main": "Is there a complete audit trail from raw material receipt to finished product release?",
             "subs": ["Can you trace the batch from raw material receiving to in-process to final packaging?",
                      "Are all intermediate hold/storage times documented and within validated limits?"]},
        ],
        "effectiveness": [
            {"main": "Has the corrective action from the last batch deviation been implemented and verified effective?",
             "subs": ["Is the CAPA closure report available with effectiveness verification evidence?",
                      "Has the recurrence of the same deviation been monitored since the CAPA was closed?"]},
            {"main": "Is there evidence that the process validation remains current and covers this product configuration?",
             "subs": ["When was the last revalidation performed for this process?",
                      "Have any changes been made to the process/equipment since the last validation?",
                      "Is the validation protocol and report approved by the quality unit?"]},
        ],
    },
    "hr": {
        "record_accuracy": [
            {"main": "Is the training effectiveness evaluation documented with specific pass/fail criteria?",
             "subs": ["What method was used to evaluate effectiveness (quiz, observation, supervisor sign-off)?",
                      "Is there a defined minimum passing score and was it met?",
                      "If effectiveness was not met, was re-training initiated and documented?"]},
            {"main": "Are competency records updated to reflect the latest SOP revisions the operator was trained on?",
             "subs": ["Does the competency matrix reference the specific SOP version number?",
                      "Is there evidence that the operator read and acknowledged the updated SOP?"]},
            {"main": "Is the annual training plan aligned with the competency matrix for all roles?",
             "subs": ["Does the training plan cover all critical process-specific training needs?",
                      "Is there a gap analysis between planned vs. completed training for the current period?",
                      "Are training needs identified from audit findings, CAPAs, and management review outputs?"]},
        ],
        "traceability": [
            {"main": "Can you trace the operator's qualification back to the specific training session, trainer name, and assessment score?",
             "subs": ["Is the trainer qualified and authorized to conduct the specific training?",
                      "Is the training attendance record complete with date, duration, and signatures?"]},
        ],
        "effectiveness": [
            {"main": "Has the training effectiveness review identified any recurring gaps across operators?",
             "subs": ["Is there a trend analysis of training effectiveness scores over the last review period?",
                      "Were any systemic training issues escalated to management review?"]},
            {"main": "Were any training-related CAPAs raised in the last review period and are they closed?",
             "subs": ["Is the root cause of the training gap identified (content, method, frequency)?",
                      "Has the corrective action prevented recurrence of the same gap?"]},
        ],
    },
    "purchase": {
        "record_accuracy": [
            {"main": "Is the supplier's current ISO/quality certificate on file and within its validity period?",
             "subs": ["Does the certificate cover the specific scope of materials/services being purchased?",
                      "Is there an alert or reminder system for certificate expiry tracking?"]},
            {"main": "Is the Approved Supplier List (ASL) current and does it reflect the latest supplier audit results?",
             "subs": ["When was the ASL last reviewed and updated?",
                      "Are suppliers who failed the last evaluation removed or downgraded on the ASL?",
                      "Is the ASL version-controlled and approved by the quality unit?"]},
            {"main": "Is there a documented risk assessment for single-source critical material suppliers?",
             "subs": ["Is there a contingency plan or alternate supplier identified for critical materials?",
                      "Has the single-source risk been reviewed in the last management review meeting?"]},
        ],
        "traceability": [
            {"main": "Can you trace the purchased material from the PO to the receiving report to the incoming inspection result?",
             "subs": ["Is the PO number referenced on the receiving report and the inspection record?",
                      "Are the quantity received and quantity ordered reconciled?",
                      "Is the material storage location documented after acceptance?"]},
        ],
        "effectiveness": [
            {"main": "Has the supplier performance rating been reviewed in the last scheduled evaluation period?",
             "subs": ["What parameters were used for rating (quality, delivery, responsiveness)?",
                      "Were underperforming suppliers issued a SCAR or placed on probation?",
                      "Were supplier performance results presented in the management review?"]},
        ],
    },
    "quality assurance": {
        "record_accuracy": [
            {"main": "Are CAPA records complete with root cause analysis, corrective action, and effectiveness verification?",
             "subs": ["Is the root cause analysis method documented (5-Why, fishbone, etc.)?",
                      "Is there a defined timeline for corrective action implementation?",
                      "Is the effectiveness check performed after a defined period and documented?",
                      "Are all supporting documents (evidence, photos, test data) attached to the CAPA?"]},
            {"main": "Is the complaint investigation report completed within the defined timeline?",
             "subs": ["Is the complaint classified by severity and regulatory reportability?",
                      "Were containment actions implemented immediately upon complaint receipt?",
                      "Is the investigation linked to the specific batch/lot number?"]},
            {"main": "Is the quality objective tracking sheet updated with actual vs. target performance data?",
             "subs": ["Are quality objectives SMART (Specific, Measurable, Achievable, Relevant, Time-bound)?",
                      "Is there a trend chart showing objective performance over the last 4 quarters?",
                      "Were missed targets escalated with a corrective action plan?"]},
        ],
        "traceability": [
            {"main": "Can you trace a specific customer complaint back to the batch number, investigation, and corrective action?",
             "subs": ["Is the complaint log cross-referenced with the CAPA log?",
                      "Can the batch distribution record identify all customers who received the affected batch?"]},
        ],
        "effectiveness": [
            {"main": "Has the effectiveness of CAPAs raised in the last audit cycle been verified and documented?",
             "subs": ["How many CAPAs from the previous cycle are still open past their due date?",
                      "Is there evidence that the root cause was eliminated (not just the symptom)?"]},
            {"main": "Is there evidence that management review action items have been completed within the assigned timelines?",
             "subs": ["What percentage of MRM action items are closed on time vs. overdue?",
                      "Are overdue items escalated in subsequent MRM meetings?"]},
        ],
    },
    "maintenance": {
        "record_accuracy": [
            {"main": "Is the calibration certificate traceable to national/international standards (NIST/ISO)?",
             "subs": ["Does the certificate mention the name and accreditation number of the calibrating lab?",
                      "Is the uncertainty of measurement documented on the certificate?",
                      "Is the calibration due date clearly marked on the instrument and in the log?"]},
            {"main": "Is the preventive maintenance schedule current and does it cover all critical equipment?",
             "subs": ["Is there a master list of all equipment with their PM frequency?",
                      "Are PM completion rates tracked and reported?",
                      "Is there evidence that overdue PM was escalated and the equipment was taken out of service?"]},
            {"main": "Are equipment qualification records (IQ/OQ/PQ) available and within their revalidation period?",
             "subs": ["Is there a revalidation schedule defined for each qualified equipment?",
                      "Were any changes made to the equipment that would trigger revalidation?"]},
        ],
        "traceability": [
            {"main": "Can you trace the calibration of this specific instrument to the accredited lab certificate?",
             "subs": ["Is the instrument ID on the calibration certificate matching the equipment master list?",
                      "Is the calibration history log maintained showing all past calibration dates and results?"]},
        ],
        "effectiveness": [
            {"main": "Has the preventive maintenance frequency been reviewed based on equipment failure trend data?",
             "subs": ["Is there a failure/breakdown trend analysis for critical equipment?",
                      "Were any PM frequency adjustments made based on the trend analysis?"]},
        ],
    },
    "sales and marketing": {
        "record_accuracy": [
            {"main": "Is the product labeling verified against the latest approved label template and regulatory requirements?",
             "subs": ["Is the label artwork approval record available with sign-off from QA and regulatory?",
                      "Does the label include all mandatory regulatory information (UDI, symbols, expiry)?",
                      "Is there a label reconciliation (issued vs. used vs. destroyed) for this batch?"]},
            {"main": "Are customer-specific requirements (custom labeling, packaging, SKU) documented and verified before shipment?",
             "subs": ["Is there a customer requirement specification or order specification on file?",
                      "Is there a final inspection/verification step before dispatch for customer-specific orders?"]},
        ],
        "traceability": [
            {"main": "Can you trace a specific customer order from PO receipt to dispatch, including all quality checks?",
             "subs": ["Is the dispatch record linked to the specific batch/lot number and inspection report?",
                      "Is the shipping documentation (packing list, invoice, COA) complete and accurate?"]},
        ],
        "effectiveness": [
            {"main": "Has customer satisfaction data been reviewed and acted upon in the last evaluation period?",
             "subs": ["What methods are used to collect customer feedback (surveys, complaints, returns)?",
                      "Were any trends identified and escalated to management review?"]},
        ],
    },
    "management review": {
        "record_accuracy": [
            {"main": "Are all required MRM inputs (audits, complaints, CAPAs, process performance) documented in the minutes?",
             "subs": ["Is there a standardized agenda template that covers all ISO 13485 required inputs?",
                      "Are data/charts/trends presented for each input or just verbal summaries?",
                      "Are external audit findings and regulatory changes included as inputs?"]},
            {"main": "Are MRM action items assigned with specific owners, timelines, and completion criteria?",
             "subs": ["Is there a tracker showing open vs. closed action items from all previous MRMs?",
                      "Are overdue actions highlighted and re-assigned with revised timelines?"]},
        ],
        "traceability": [
            {"main": "Can each MRM action item be traced to its completion evidence and effectiveness verification?",
             "subs": ["Is the completion evidence attached or referenced in the action tracker?",
                      "Is effectiveness of actions reviewed in the subsequent MRM?"]},
        ],
        "effectiveness": [
            {"main": "Were the quality objectives set in the previous MRM achieved? If not, what corrective action was taken?",
             "subs": ["Is there a comparison of current period results vs. the objectives set in the last MRM?",
                      "Were resource allocation decisions from the last MRM implemented?"]},
        ],
    },
}

# ── Generic fallback templates (main + subs) ─────────────────────────────────
_GENERIC_FOLLOWUP_TEMPLATES = {
    "record_accuracy": [
        {"main": "Are all records legible, dated, and signed by authorized personnel?",
         "subs": ["Is there a master list of authorized signatories for each record type?",
                  "Are electronic records protected with audit trail and access controls?"]},
        {"main": "Is the document version control maintained and current?",
         "subs": ["Is there a document master list showing current revision status?",
                  "Are obsolete documents removed from the point of use?"]},
    ],
    "traceability": [
        {"main": "Can the complete audit trail be reconstructed from the available records?",
         "subs": ["Are unique identifiers used consistently across all related records?",
                  "Is there bidirectional traceability between inputs and outputs?"]},
    ],
    "effectiveness": [
        {"main": "Is there evidence that the corrective actions from the previous audit cycle were effective?",
         "subs": ["How many repeat findings were identified in the current audit vs. the previous?",
                  "Is there a trend analysis of audit findings by category?"]},
        {"main": "Is there evidence that preventive actions are reducing recurrence of similar issues?",
         "subs": ["Has the frequency of similar non-conformances decreased after preventive action?",
                  "Is preventive action effectiveness reviewed periodically?"]},
    ],
}


def get_all_completed_answers(
    audit_id: str,
    dept: str,
    *,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return every answered checklist row across ALL sections for the given audit + dept."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept_n = _normalize_text(dept)
    sections = get_generated_sections(audit_id, dept_n, tenant_id=tenant_id) or get_sections_for_department(dept_n, tenant_id=tenant_id, audit_id=audit_id)
    completed: List[Dict[str, Any]] = []
    for section in sections:
        rows = get_checklist_rows_for_audit_section(audit_id, dept_n, section, tenant_id=tenant_id)
        for r in rows:
            obs = str(r.get("observation", "") or "").strip()
            ev = str(r.get("evidence", "") or "").strip()
            if obs and ev:
                completed.append({
                    "section": section, "sr_no": r.get("sr_no", ""),
                    "checklist": r.get("checklist", ""), "observation": obs,
                    "evidence": ev, "clause_no": r.get("clause_no", ""),
                    "item_level": r.get("item_level", "main"),
                })
    return completed


def get_all_pending_questions(
    audit_id: str,
    dept: str,
    *,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return every unanswered checklist row across ALL sections."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept_n = _normalize_text(dept)
    sections = get_generated_sections(audit_id, dept_n, tenant_id=tenant_id) or get_sections_for_department(dept_n, tenant_id=tenant_id, audit_id=audit_id)
    pending: List[Dict[str, Any]] = []
    for section in sections:
        rows = get_checklist_rows_for_audit_section(audit_id, dept_n, section, tenant_id=tenant_id)
        for r in rows:
            obs = str(r.get("observation", "") or "").strip()
            ev = str(r.get("evidence", "") or "").strip()
            if not obs or not ev:
                pending.append({
                    "section": section, "sr_no": r.get("sr_no", ""),
                    "checklist": r.get("checklist", ""),
                    "item_level": r.get("item_level", "main"),
                })
    return pending


def extract_text_from_audit_reports(
    audit_id: str,
    *,
    tenant_id: Optional[str] = None,
    max_chars: int = 8000,
) -> str:
    """Read all uploaded report files for an audit and return combined text."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    a = get_audit(audit_id, tenant_id=tenant_id)
    if not a:
        return ""
    reports = a.get("reports", []) or []
    combined_text = []
    for rpt in reports:
        saved_path = rpt.get("saved_path", "")
        file_name = rpt.get("file_name", "")
        if not saved_path or not os.path.exists(saved_path):
            continue
        try:
            ext = os.path.splitext(file_name)[1].lower()
            if ext == ".pdf":
                try:
                    import fitz
                    doc = fitz.open(saved_path)
                    for page in doc:
                        combined_text.append(page.get_text())
                    doc.close()
                except ImportError:
                    combined_text.append(f"[PDF report uploaded: {file_name}]")
            elif ext in (".csv", ".txt"):
                with open(saved_path, "r", encoding="utf-8", errors="ignore") as f:
                    combined_text.append(f.read())
            elif ext in (".xlsx", ".xls"):
                combined_text.append(f"[Excel report uploaded: {file_name}]")
        except Exception:
            combined_text.append(f"[File: {file_name} — could not extract text]")
    full_text = "\n\n".join(combined_text)
    return full_text[:max_chars] if len(full_text) > max_chars else full_text


def _analyze_answer_weakness(observation: str, evidence: str) -> List[str]:
    """Detect weakness type(s) in an answer. Returns list of tags."""
    tags = []
    combined = (observation + " " + evidence).lower()
    for kw in _WEAKNESS_KEYWORDS:
        if kw in combined:
            tags.append("gap_detected")
            break
    word_count = len(combined.split())
    if word_count < 8:
        tags.append("vague_answer")
    obs_lower = observation.lower().strip()
    if obs_lower in _VAGUE_KEYWORDS or (len(obs_lower) < 20 and any(obs_lower.startswith(v) for v in _VAGUE_KEYWORDS)):
        tags.append("vague_answer")
    if not evidence.strip() or evidence.strip().lower() in ("na", "n/a", "nil", "none", "-"):
        tags.append("weak_evidence")
    return tags if tags else ["solid"]


def build_ai_question_context(
    audit_id: str,
    dept: str,
    current_section: str,
    *,
    tenant_id: Optional[str] = None,
    last_n_answers: int = 10,
) -> Dict[str, Any]:
    """Build structured context dict by scanning answers and files."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept_n = _normalize_text(dept)
    section_n = _normalize_text(current_section)
    completed = get_all_completed_answers(audit_id, dept_n, tenant_id=tenant_id)
    pending = get_all_pending_questions(audit_id, dept_n, tenant_id=tenant_id)
    file_text = extract_text_from_audit_reports(audit_id, tenant_id=tenant_id, max_chars=6000)
    recent_answers = completed[-last_n_answers:]
    last_answer = completed[-1] if completed else None

    # Analyze weaknesses in recent answers
    weak_answers = []
    for ans in recent_answers:
        tags = _analyze_answer_weakness(ans.get("observation", ""), ans.get("evidence", ""))
        if "solid" not in tags:
            weak_answers.append({**ans, "weakness_tags": tags})

    current_section_rows = get_checklist_rows_for_audit_section(
        audit_id, dept_n, section_n, tenant_id=tenant_id)

    return {
        "department": dept_n,
        "current_section": section_n,
        "total_completed": len(completed),
        "total_pending": len(pending),
        "last_answer": last_answer,
        "recent_answers": recent_answers,
        "weak_answers": weak_answers,
        "pending_questions": pending[:20],
        "current_section_questions": [r.get("checklist", "") for r in current_section_rows],
        "file_evidence_text": file_text,
        "existing_question_texts": [r.get("checklist", "") for r in current_section_rows],
    }


def _pick_followup_question(context: Dict[str, Any]) -> Tuple[str, List[str], str]:
    """
    Rule-based engine: pick the best follow-up question based on answer analysis.
    Returns (main_question, sub_questions_list, reasoning).
    """
    dept = context.get("department", "").lower().strip()
    weak_answers = context.get("weak_answers", [])
    existing_qs = {q.lower().strip() for q in context.get("existing_question_texts", []) if q}
    last_answer = context.get("last_answer") or {}

    def _is_duplicate(q: str) -> bool:
        return q.lower().strip() in existing_qs

    # ── Strategy 1: If weak answers found, probe the weakness ─────────────
    if weak_answers:
        wa = weak_answers[-1]  # most recent weak answer
        tags = wa.get("weakness_tags", [])
        original_q = wa.get("checklist", "")

        if "gap_detected" in tags:
            gap_sets = [
                {"main": f"Regarding '{original_q[:80]}...' — what corrective action has been initiated to address the identified gap?",
                 "subs": [f"Is there a documented root cause analysis for the gap found in: '{original_q[:60]}...'?",
                          "Has a CAPA been raised with a defined timeline for closure?",
                          "What interim containment action was taken to prevent product/process impact?"]},
                {"main": f"For the gap found in '{original_q[:80]}...' — is there a documented investigation?",
                 "subs": ["Was the investigation completed within the defined SOP timeline?",
                          "Is the investigation report approved by the quality unit?",
                          "Were affected products/batches identified and dispositioned?"]},
            ]
            for gs in gap_sets:
                if not _is_duplicate(gs["main"]):
                    return gs["main"], gs["subs"], "Gap/non-conformance detected in previous answer. Probing corrective action and investigation depth."

        if "vague_answer" in tags:
            vague_sets = [
                {"main": f"Can you provide specific documentary evidence (document number, date, version) for: '{original_q[:80]}...'?",
                 "subs": ["What specific document/record was reviewed to support this observation?",
                          "What was the document revision number and date?",
                          "Were the findings compared against the acceptance criteria defined in the SOP?"]},
                {"main": f"The observation for '{original_q[:80]}...' needs more detail — what specific records were reviewed?",
                 "subs": ["List the specific record identifiers (log numbers, batch numbers) that were checked.",
                          "What was the actual finding vs. the expected requirement?"]},
            ]
            for vs in vague_sets:
                if not _is_duplicate(vs["main"]):
                    return vs["main"], vs["subs"], "Previous answer was too vague. Requesting specific documentary evidence with sub-questions."

        if "weak_evidence" in tags:
            ev_sets = [
                {"main": f"What specific document, record, or reference supports the observation for: '{original_q[:80]}...'?",
                 "subs": ["Can you show/attach the actual evidence document (log, certificate, report)?",
                          "Is the evidence document signed and dated by the authorized person?"]},
            ]
            for es in ev_sets:
                if not _is_duplicate(es["main"]):
                    return es["main"], es["subs"], "Evidence field was empty or marked N/A. Requesting concrete evidence with verification sub-questions."

    # ── Strategy 2: Department-specific probing questions (main + subs) ────
    dept_key = None
    for k in _DEPT_FOLLOWUP_TEMPLATES:
        if k in dept:
            dept_key = k
            break
    templates = _DEPT_FOLLOWUP_TEMPLATES.get(dept_key, _GENERIC_FOLLOWUP_TEMPLATES)

    completed_count = context.get("total_completed", 0)
    if completed_count < 3:
        category = "record_accuracy"
        reason_prefix = "Early in audit — verifying record accuracy and completeness with detailed sub-questions."
    elif weak_answers:
        category = "effectiveness"
        reason_prefix = "Weaknesses detected — testing implementation effectiveness with follow-up sub-questions."
    else:
        categories = ["record_accuracy", "traceability", "effectiveness"]
        category = _random.choice(categories)
        reason_prefix = f"Answers appear solid — probing deeper into {category.replace('_', ' ')} with sub-questions."

    pool = templates.get(category, [])
    if not pool:
        pool = _GENERIC_FOLLOWUP_TEMPLATES.get(category, [])

    _random.shuffle(pool)
    for item in pool:
        main_q = item.get("main", "") if isinstance(item, dict) else str(item)
        subs = item.get("subs", []) if isinstance(item, dict) else []
        if not _is_duplicate(main_q):
            return main_q, subs, reason_prefix

    # ── Strategy 3: Last resort ──────────────────────────────────────────
    if last_answer:
        la_q = last_answer.get("checklist", "")
        fallback_main = f"Can you cross-reference the records reviewed for '{la_q[:80]}...' with the corresponding entries in the master log/register?"
        fallback_subs = ["Is the master log/register current and version-controlled?",
                         "Are any discrepancies between the reviewed records and the master log documented?"]
        if not _is_duplicate(fallback_main):
            return fallback_main, fallback_subs, "All template questions exhausted — generating cross-reference verification."

    return ("Are all records reviewed in this section legible, dated, signed, and retrievable as per the document control procedure?",
            ["Is there a defined retention period for each record type?", "Are backup copies maintained for critical records?"],
            "Fallback — verifying fundamental record-keeping compliance.")


def add_ai_question_with_subs(
    audit_id: str,
    dept: str,
    section: str,
    main_text: str,
    sub_texts: List[str],
    auditor_name: str,
    *,
    tenant_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Add an AI-generated main question + its sub-questions to the checklist
    with proper hierarchy (item_level=main/sub, parent_order linkage).
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept_n, section_n = _normalize_text(dept), _normalize_text(section)
    if not main_text.strip():
        return False, "Main question text is required."

    existing = load_audit_section_table(audit_id, dept_n, section_n, tenant_id=tenant_id) or []
    rows = list(existing) if existing else [
        {"sr_no": str(i), "checklist": str(item).strip(),
         "observation": "", "evidence": "",
         "item_level": "main", "parent_order": None}
        for i, item in enumerate(
            get_items_for_department_section(dept_n, section_n, tenant_id=tenant_id), start=1)
    ]

    # Assign sr_no for the new main question
    max_sr = max((int(float(str(r.get("sr_no", "0")).strip() or "0")) for r in rows), default=0)
    main_sr = max_sr + 1

    # Add main question
    rows.append({
        "sr_no": str(main_sr),
        "checklist": f"[AI] {main_text.strip()}",
        "observation": "",
        "evidence": "",
        "clause_no": "",
        "item_level": "main",
        "parent_order": None,
    })

    # Add sub-questions linked to the main
    for sub_text in (sub_texts or []):
        sub_text = sub_text.strip()
        if not sub_text:
            continue
        max_sr += 1
        rows.append({
            "sr_no": str(max_sr + 1),
            "checklist": f"[AI] {sub_text}",
            "observation": "",
            "evidence": "",
            "clause_no": "",
            "item_level": "sub",
            "parent_order": main_sr,
        })

    return save_audit_section_table(
        audit_id=audit_id, dept=dept_n, section=section_n,
        rows=rows, auditor_name=auditor_name, tenant_id=tenant_id)


def generate_and_add_ai_question(
    audit_id: str,
    dept: str,
    section: str,
    auditor_name: str,
    *,
    tenant_id: Optional[str] = None,
    api_key: Optional[str] = None,
    auto_add: bool = False,
) -> Tuple[bool, str, str, List[str]]:
    """
    Full pipeline: build context → analyze answers → generate main + sub questions.
    100% FREE — no API key needed.
    Returns: (success, main_question, reasoning, sub_questions_list)
    """
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    context = build_ai_question_context(audit_id, dept, section, tenant_id=tenant_id)
    question, subs, reasoning = _pick_followup_question(context)

    if not question:
        return False, "", "Could not generate a question.", []

    if auto_add:
        add_ok, add_msg = add_ai_question_with_subs(
            audit_id=audit_id, dept=dept, section=section,
            main_text=question, sub_texts=subs,
            auditor_name=auditor_name, tenant_id=tenant_id,
        )
        if not add_ok:
            return True, question, f"Generated but failed to add: {add_msg}", subs
    return True, question, reasoning, subs


def generate_ai_questions_for_department(
    audit_id: str,
    dept: str,
    auditor_name: str,
    *,
    tenant_id: Optional[str] = None,
    api_key: Optional[str] = None,
    max_per_section: int = 1,
) -> List[Dict[str, Any]]:
    """Generate smart follow-up questions (main + subs) for every section. FREE."""
    tenant_id = tenant_id or ensure_seed_files(DEFAULT_TENANT_CODE)
    dept_n = _normalize_text(dept)
    sections = get_generated_sections(audit_id, dept_n, tenant_id=tenant_id) or get_sections_for_department(dept_n, tenant_id=tenant_id, audit_id=audit_id)
    results = []
    for section in sections:
        for _ in range(max_per_section):
            ok, q, reason, subs = generate_and_add_ai_question(
                audit_id, dept_n, section, auditor_name,
                tenant_id=tenant_id, auto_add=True,
            )
            results.append({
                "section": section, "question": q if ok else "",
                "sub_questions": subs if ok else [],
                "reasoning": reason, "added": ok,
            })
    return results