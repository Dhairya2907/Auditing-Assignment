from __future__ import annotations

import json
import os
import uuid
import hashlib
import hmac
import timetable

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple

# -----------------------------
# Files
# -----------------------------
PEOPLE_FILE = "people.json"
STATE_FILE = "audit_state.json"
AUDITS_FILE = "audits.json"
USERS_FILE = "users.json"
UPLOADS_DIR = "uploads"

DEPARTMENTS_FILE = "departments.json"
SKILLS_CATALOG_FILE = "skills_catalog.json"
DEPT_REQUIRED_SKILLS_FILE = "dept_required_skills.json"

# -----------------------------
# Default departments (seed)
# -----------------------------
DEFAULT_DEPARTMENTS = ["HR", "Purchase", "Sales and Marketing"]

# -----------------------------
# Default controlled skills (seed)
# Stored as skill_key -> skill_label
# -----------------------------
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

# -----------------------------
# Default required skills per department (seed)
# -----------------------------
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
}

# -----------------------------
# Data models
# -----------------------------
@dataclass(frozen=True)
class Person:
    name: str
    department: str
    skills: Set[str]  # skill KEYS (from skills_catalog.json)
    level: str        # "experienced" or "fresher"

# -----------------------------
# Helpers
# -----------------------------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def load_json(path: str, default_obj):
    if not os.path.exists(path):
        return default_obj
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def ensure_dirs() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)

def _normalize_username(name: str) -> str:
    return name.strip().lower().replace(" ", "")

def _normalize_text(s: str) -> str:
    return " ".join(str(s or "").strip().split())

# -----------------------------
# Password hashing (PBKDF2)
# -----------------------------
def _pbkdf2_hash(password: str, salt_hex: str, iterations: int) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return dk.hex()

def make_password_record(password: str) -> Dict:
    salt = os.urandom(16).hex()
    iterations = 150_000
    return {
        "salt": salt,
        "iterations": iterations,
        "hash": _pbkdf2_hash(password, salt, iterations),
    }

def verify_password(password: str, rec: Dict) -> bool:
    salt = rec.get("salt", "")
    it = int(rec.get("iterations", 150_000))
    expected = rec.get("hash", "")
    if not salt or not expected:
        return False
    got = _pbkdf2_hash(password, salt, it)
    return hmac.compare_digest(got, expected)

# -----------------------------
# Catalog: departments
# -----------------------------
def load_departments_catalog() -> List[str]:
    ensure_seed_files()
    deps = load_json(DEPARTMENTS_FILE, [])
    # normalize + unique
    out: List[str] = []
    seen = set()
    for d in deps:
        dn = _normalize_text(d)
        if not dn:
            continue
        key = dn.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dn)
    out.sort(key=lambda x: x.lower())
    return out

def add_department_to_catalog(dept: str) -> None:
    dept = _normalize_text(dept)
    if not dept:
        return
    deps = load_json(DEPARTMENTS_FILE, [])
    lower = {str(d).strip().lower() for d in deps if str(d).strip()}
    if dept.lower() in lower:
        return
    deps.append(dept)
    save_json(DEPARTMENTS_FILE, deps)

# -----------------------------
# Catalog: skills (key -> label)
# -----------------------------
def load_skills_catalog() -> Dict[str, str]:
    ensure_seed_files()
    cat = load_json(SKILLS_CATALOG_FILE, {})
    # normalize labels
    out: Dict[str, str] = {}
    for k, v in (cat or {}).items():
        kk = str(k).strip().lower()
        vv = _normalize_text(v)
        if kk and vv:
            out[kk] = vv
    return out

def _save_skills_catalog(cat: Dict[str, str]) -> None:
    save_json(SKILLS_CATALOG_FILE, cat)

def ensure_skill_in_catalog(label: str) -> str:
    """
    Ensure a skill label exists in catalog.
    If exists (case-insensitive label match), return existing key.
    Otherwise create a new custom key and return it.
    """
    label = _normalize_text(label)
    if not label:
        raise ValueError("Skill label cannot be empty.")

    cat = load_skills_catalog()

    # label match
    for k, v in cat.items():
        if v.strip().lower() == label.lower():
            return k

    # create new key
    new_key = f"custom_{uuid.uuid4().hex[:10]}"
    cat[new_key] = label
    _save_skills_catalog(cat)
    return new_key

def ensure_skill_key_exists(skill_key: str, fallback_label: str = "") -> str:
    """
    If a skill_key is seen in people.json or required skills but not in catalog,
    add it using fallback_label (or key itself) to prevent crashes.
    """
    kk = str(skill_key).strip().lower()
    if not kk:
        raise ValueError("Skill key cannot be empty.")
    cat = load_skills_catalog()
    if kk in cat:
        return kk
    label = _normalize_text(fallback_label) or kk
    cat[kk] = label
    _save_skills_catalog(cat)
    return kk

# -----------------------------
# Required skills per department
# -----------------------------
def load_dept_required_skills() -> Dict[str, List[str]]:
    ensure_seed_files()
    data = load_json(DEPT_REQUIRED_SKILLS_FILE, {})
    out: Dict[str, List[str]] = {}
    for dept, keys in (data or {}).items():
        d = _normalize_text(dept)
        if not d:
            continue
        ks = []
        for k in (keys or []):
            kk = str(k).strip().lower()
            if kk:
                ks.append(kk)
        # unique preserve order
        seen = set()
        uniq = []
        for k in ks:
            if k in seen:
                continue
            seen.add(k)
            uniq.append(k)
        out[d] = uniq
    return out

def set_dept_required_skills(dept: str, skill_keys: List[str]) -> None:
    dept = _normalize_text(dept)
    if not dept:
        raise ValueError("Department cannot be empty.")

    # ensure dept exists in dept catalog
    add_department_to_catalog(dept)

    # normalize keys and ensure they exist in catalog
    cleaned: List[str] = []
    seen = set()
    for k in (skill_keys or []):
        kk = str(k).strip().lower()
        if not kk:
            continue
        kk = ensure_skill_key_exists(kk)
        if kk in seen:
            continue
        seen.add(kk)
        cleaned.append(kk)

    data = load_json(DEPT_REQUIRED_SKILLS_FILE, {})
    data[dept] = cleaned
    save_json(DEPT_REQUIRED_SKILLS_FILE, data)

def get_required_skills_for_dept(dept: str) -> Set[str]:
    dept = _normalize_text(dept)
    mapping = load_dept_required_skills()
    keys = mapping.get(dept, [])
    return set(keys)

# -----------------------------
# Seed files (NO recursion)
# -----------------------------
def ensure_seed_files() -> None:
    """
    Creates required JSON files if missing.
    IMPORTANT: This must NOT call load_people()/load_users() to avoid recursion.
    """
    ensure_dirs()

    # seed departments.json
    if not os.path.exists(DEPARTMENTS_FILE):
        save_json(DEPARTMENTS_FILE, DEFAULT_DEPARTMENTS)

    # seed skills_catalog.json
    if not os.path.exists(SKILLS_CATALOG_FILE):
        save_json(SKILLS_CATALOG_FILE, DEFAULT_SKILLS)

    # seed dept_required_skills.json
    if not os.path.exists(DEPT_REQUIRED_SKILLS_FILE):
        save_json(DEPT_REQUIRED_SKILLS_FILE, DEFAULT_DEPT_REQUIRED_SKILLS)

    # seed people.json
    if not os.path.exists(PEOPLE_FILE):
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
        save_json(PEOPLE_FILE, sample_people)

    if not os.path.exists(STATE_FILE):
        save_json(STATE_FILE, {"busy_by_name": {}, "audit_history": []})

    if not os.path.exists(AUDITS_FILE):
        save_json(AUDITS_FILE, {"audits": []})

    if not os.path.exists(USERS_FILE):
        # Build users from people.json directly (no load_people call)
        raw_people = load_json(PEOPLE_FILE, [])
        users = {"users": []}

        users["users"].append(
            {
                "username": "admin",
                "role": "admin",
                "person_name": None,
                "password": make_password_record("admin123"),
                "created_at": _now_iso(),
            }
        )

        for p in raw_people:
            nm = str(p.get("name", "")).strip()
            if not nm:
                continue
            uname = _normalize_username(nm)
            users["users"].append(
                {
                    "username": uname,
                    "role": "auditor",
                    "person_name": nm,
                    "password": make_password_record("auditor123"),
                    "created_at": _now_iso(),
                }
            )
        save_json(USERS_FILE, users)

# -----------------------------
# Loaders
# -----------------------------
def load_people() -> List[Person]:
    ensure_seed_files()
    raw = load_json(PEOPLE_FILE, [])
    people: List[Person] = []

    dept_catalog = load_departments_catalog()
    dept_lower = {d.lower(): d for d in dept_catalog}

    skill_cat = load_skills_catalog()

    for item in raw:
        name = _normalize_text(item.get("name", ""))
        dept = _normalize_text(item.get("department", ""))
        level = str(item.get("level", "experienced")).strip().lower()
        skills_raw = item.get("skills", [])
        skills = set(str(s).strip().lower() for s in skills_raw if str(s).strip())

        if not name:
            continue

        # if dept not in catalog, auto-add it (so it becomes dropdown next time)
        if dept and dept.lower() not in dept_lower:
            add_department_to_catalog(dept)
            dept_lower[dept.lower()] = dept

        if level not in {"experienced", "fresher"}:
            raise ValueError(f"Invalid level for {name}: '{level}'. Use 'experienced' or 'fresher'.")

        # ensure all skill keys exist in catalog (avoid crashes)
        for k in list(skills):
            if k not in skill_cat:
                ensure_skill_key_exists(k, fallback_label=k)

        people.append(Person(name=name, department=dept, skills=skills, level=level))

    return people

def load_state() -> Dict:
    ensure_seed_files()
    state = load_json(STATE_FILE, {"busy_by_name": {}, "audit_history": []})
    state.setdefault("busy_by_name", {})
    state.setdefault("audit_history", [])
    return state

def save_state(state: Dict) -> None:
    save_json(STATE_FILE, state)

def load_audits() -> Dict:
    ensure_seed_files()
    data = load_json(AUDITS_FILE, {"audits": []})
    data.setdefault("audits", [])
    return data

def save_audits(data: Dict) -> None:
    save_json(AUDITS_FILE, data)

def load_users() -> Dict:
    ensure_seed_files()
    data = load_json(USERS_FILE, {"users": []})
    data.setdefault("users", [])
    return data

def find_user(username: str) -> Optional[Dict]:
    for u in load_users().get("users", []):
        if str(u.get("username", "")).lower() == str(username).lower():
            return u
    return None

# -----------------------------
# RBAC auth
# -----------------------------
def authenticate(username: str, password: str) -> Tuple[bool, Optional[Dict], str]:
    ensure_seed_files()
    u = find_user(username)
    if not u:
        return False, None, "Invalid username or password."
    if not verify_password(password, u.get("password", {})):
        return False, None, "Invalid username or password."
    return True, u, "Login successful."

# -----------------------------
# Eligibility / assignment rules
# -----------------------------
def is_busy(state: Dict, person_name: str) -> bool:
    return person_name in state.get("busy_by_name", {})

def has_all_required_skills(person: Person, required_skills: Set[str]) -> bool:
    return required_skills.issubset(person.skills)

def eligible_people(
    people: List[Person],
    state: Dict,
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

def lock_auditor(state: Dict, auditor_name: str, audit_id: str, target_dept: str, required_skills: Set[str], level: str) -> None:
    state["busy_by_name"][auditor_name] = {
        "audit_id": audit_id,
        "audited_department": target_dept,
        "required_skills": sorted(required_skills),
        "level": level,
        "started_at": _now_iso(),
        "status": "ongoing",
    }

def unlock_auditor(state: Dict, auditor_name: str) -> None:
    if auditor_name in state.get("busy_by_name", {}):
        del state["busy_by_name"][auditor_name]

# -----------------------------
# Audit record management
# -----------------------------
def list_audits() -> List[Dict]:
    return load_audits().get("audits", [])

def get_audit(audit_id: str) -> Optional[Dict]:
    for a in list_audits():
        if a.get("audit_id") == audit_id:
            return a
    return None

def _save_updated_audit(updated: Dict) -> None:
    data = load_audits()
    audits = data.get("audits", [])
    for i, a in enumerate(audits):
        if a.get("audit_id") == updated.get("audit_id"):
            audits[i] = updated
            save_audits(data)
            return
    raise ValueError("Audit not found while saving.")

def create_and_assign_audit(
    created_by: str,
    target_dept: str,
    allow_fresher_fallback: bool,
    title: str = "",
    scope: str = "",
    due_date: str = "",
    required_skill_keys_override: Optional[Set[str]] = None,
    save_required_skills_as_default: bool = False,
) -> Tuple[Optional[Dict], str]:
    ensure_seed_files()

    target_dept = _normalize_text(target_dept)
    if not target_dept:
        return None, "Department is required."

    # ensure department exists in catalog so it appears next time
    add_department_to_catalog(target_dept)

    # required skills: from catalog mapping, or override from UI for custom departments
    if required_skill_keys_override is not None:
        required_skills = set(str(k).strip().lower() for k in required_skill_keys_override if str(k).strip())
        # ensure keys exist in skills catalog
        for k in list(required_skills):
            ensure_skill_key_exists(k, fallback_label=k)
        if save_required_skills_as_default:
            set_dept_required_skills(target_dept, sorted(required_skills))
    else:
        required_skills = get_required_skills_for_dept(target_dept)

    if not required_skills:
        return None, "No required skills defined for this department. Enter required skills (or save them as default)."

    people = load_people()
    state = load_state()
    audits_data = load_audits()

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
    }

    audits_data["audits"].append(audit)
    save_audits(audits_data)

    lock_auditor(state, chosen.name, audit_id, target_dept, required_skills, chosen.level)
    save_state(state)

    return audit, f"Assigned {chosen.name} to audit '{target_dept}'."

def set_audit_status(audit_id: str, new_status: str) -> Tuple[bool, str]:
    a = get_audit(audit_id)
    if not a:
        return False, "Audit not found."
    a["status"] = new_status
    _save_updated_audit(a)
    return True, "Status updated."

def save_report_file(
    audit_id: str,
    uploaded_by: str,
    original_filename: str,
    file_bytes: bytes,
) -> Tuple[bool, str]:
    ensure_seed_files()
    ensure_dirs()

    a = get_audit(audit_id)
    if not a:
        return False, "Audit not found."

    ext = os.path.splitext(original_filename)[1].lower()
    allowed = {".pdf", ".xlsx", ".xls", ".csv"}
    if ext not in allowed:
        return False, "Invalid file type. Allowed: PDF, XLSX/XLS, CSV."

    audit_folder = os.path.join(UPLOADS_DIR, f"audit_{audit_id}")
    os.makedirs(audit_folder, exist_ok=True)

    safe_name = original_filename.replace("\\", "_").replace("/", "_")
    saved_path = os.path.join(audit_folder, f"{uuid.uuid4().hex}_{safe_name}")

    with open(saved_path, "wb") as f:
        f.write(file_bytes)

    a["reports"].append(
        {
            "file_name": safe_name,
            "saved_path": saved_path,
            "uploaded_at": _now_iso(),
            "uploaded_by": uploaded_by,
        }
    )

    if a["status"] == "Assigned":
        a["status"] = "In Progress"

    _save_updated_audit(a)
    return True, "Report uploaded successfully."

def submit_report(audit_id: str, auditor_name: str) -> Tuple[bool, str]:
    a = get_audit(audit_id)
    if not a:
        return False, "Audit not found."
    if a.get("assigned_auditor") != auditor_name:
        return False, "You are not assigned to this audit."
    if not a.get("reports"):
        return False, "Report upload is mandatory before submission."

    a["status"] = "Report Submitted"
    a["report_submitted_at"] = _now_iso()
    _save_updated_audit(a)
    return True, "Report submitted."

def complete_audit(audit_id: str, auditor_name: str) -> Tuple[bool, str]:
    a = get_audit(audit_id)
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
    _save_updated_audit(a)

    state = load_state()
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
    save_state(state)

    return True, "Audit completed and auditor unlocked."

# -----------------------------
# Admin: people + users management
# -----------------------------
def list_people_records() -> List[Dict]:
    ensure_seed_files()
    return load_json(PEOPLE_FILE, [])

def add_auditor(
    name: str,
    department: str,
    level: str,
    skills: Set[str],
    password: str = "auditor123",
) -> Tuple[bool, str]:
    ensure_seed_files()

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

    # ensure department exists in catalog so it appears in dropdown next time
    add_department_to_catalog(department)

    # ensure skill keys exist in catalog
    cleaned_skills: Set[str] = set()
    for k in skills:
        kk = str(k).strip().lower()
        if not kk:
            continue
        kk = ensure_skill_key_exists(kk, fallback_label=kk)
        cleaned_skills.add(kk)

    if not cleaned_skills:
        return False, "At least one valid skill is required."

    people_raw = load_json(PEOPLE_FILE, [])
    if any(_normalize_text(p.get("name", "")).lower() == name.lower() for p in people_raw):
        return False, "Auditor with this name already exists."

    people_raw.append(
        {
            "name": name,
            "department": department,
            "skills": sorted(cleaned_skills),
            "level": level,
        }
    )
    save_json(PEOPLE_FILE, people_raw)

    users_data = load_users()
    uname = _normalize_username(name)

    if any(str(u.get("username", "")).lower() == uname.lower() for u in users_data.get("users", [])):
        return True, f"Auditor added. Login already existed for username '{uname}'."

    users_data["users"].append(
        {
            "username": uname,
            "role": "auditor",
            "person_name": name,
            "password": make_password_record(password),
            "created_at": _now_iso(),
        }
    )
    save_json(USERS_FILE, users_data)

    return True, f"Auditor added successfully. Username: {uname} | Password: {password}"

def delete_auditor(name: str) -> Tuple[bool, str]:
    ensure_seed_files()
    name = _normalize_text(name)
    if not name:
        return False, "Name is required."

    state = load_state()
    if is_busy(state, name):
        return False, "Cannot delete. Auditor is locked in an ongoing audit."

    people_raw = load_json(PEOPLE_FILE, [])
    new_people = [p for p in people_raw if _normalize_text(p.get("name", "")).lower() != name.lower()]
    if len(new_people) == len(people_raw):
        return False, "Auditor not found."
    save_json(PEOPLE_FILE, new_people)

    users_data = load_users()
    users_data["users"] = [
        u for u in users_data.get("users", [])
        if not (u.get("role") == "auditor" and _normalize_text(u.get("person_name", "")).lower() == name.lower())
    ]
    save_json(USERS_FILE, users_data)

    return True, "Auditor deleted successfully (people.json and users.json updated)."
