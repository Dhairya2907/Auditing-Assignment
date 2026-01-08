import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

PEOPLE_FILE = "people.json"
SCHEDULE_FILE = "schedule.json"


# -------------------------
# JSON Helpers
# -------------------------
def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -------------------------
# People Helpers
# -------------------------
def load_people() -> List[Dict[str, Any]]:
    """
    people.json example:
    [
      {"name":"Amit", "skills":["HR auditing"], "active": true},
      {"name":"Neha", "skills":["Purchase auditing"], "active": true}
    ]
    """
    return _read_json(PEOPLE_FILE, [])


def list_auditor_names(active_only: bool = True) -> List[str]:
    people = load_people()
    names = []
    for p in people:
        if active_only and not p.get("active", True):
            continue
        if p.get("name"):
            names.append(p["name"])
    return sorted(set(names))


# -------------------------
# Slot Generator
# -------------------------
def generate_daily_slots(
    start_time: str = "09:30",
    end_time: str = "18:30",
    slot_minutes: int = 60
) -> List[str]:
    fmt = "%H:%M"
    start_dt = datetime.strptime(start_time, fmt)
    end_dt = datetime.strptime(end_time, fmt)

    slots = []
    cur = start_dt
    while cur + timedelta(minutes=slot_minutes) <= end_dt:
        nxt = cur + timedelta(minutes=slot_minutes)
        slots.append(f"{cur.strftime(fmt)}-{nxt.strftime(fmt)}")
        cur = nxt
    return slots


# -------------------------
# Schedule Storage
# -------------------------
def load_schedule() -> Dict[str, Any]:
    """
    schedule.json structure:
    {
      "days": {
        "2026-01-06": {
          "09:30-10:30": [
            {"department":"HR","auditor":"Amit"},
            {"department":"Purchase","auditor":"Neha"}
          ]
        }
      }
    }
    """
    return _read_json(SCHEDULE_FILE, {"days": {}})


def save_schedule(schedule: Dict[str, Any]) -> None:
    if "days" not in schedule or not isinstance(schedule["days"], dict):
        schedule = {"days": {}}
    _write_json(SCHEDULE_FILE, schedule)


def ensure_day_slots(date_str: str, slots: List[str]) -> Dict[str, Any]:
    schedule = load_schedule()
    schedule.setdefault("days", {})
    schedule["days"].setdefault(date_str, {})
    for s in slots:
        schedule["days"][date_str].setdefault(s, [])
    save_schedule(schedule)
    return schedule


# -------------------------
# Rules
# -------------------------
def auditor_is_busy(schedule: Dict[str, Any], date_str: str, slot: str, auditor: str) -> bool:
    audits = schedule.get("days", {}).get(date_str, {}).get(slot, [])
    return any(a.get("auditor") == auditor for a in audits)


def get_free_auditors_for_slot(date_str: str, slot: str) -> List[str]:
    schedule = load_schedule()
    all_auditors = list_auditor_names(active_only=True)
    return [a for a in all_auditors if not auditor_is_busy(schedule, date_str, slot, a)]


def add_audit_to_slot(date_str: str, slot: str, department: str, auditor: str) -> Tuple[bool, str]:
    if not date_str or not slot or not department or not auditor:
        return False, "Missing date, slot, department, or auditor."

    schedule = load_schedule()
    schedule.setdefault("days", {})
    schedule["days"].setdefault(date_str, {})
    schedule["days"][date_str].setdefault(slot, [])

    # Same auditor cannot be double-booked in same slot
    if auditor_is_busy(schedule, date_str, slot, auditor):
        return False, f"{auditor} is already booked in {slot} on {date_str}."

    schedule["days"][date_str][slot].append({"department": department, "auditor": auditor})
    save_schedule(schedule)
    return True, "Audit added successfully."


def get_slot_audits(date_str: str, slot: str) -> List[Dict[str, Any]]:
    schedule = load_schedule()
    return schedule.get("days", {}).get(date_str, {}).get(slot, []) or []


def remove_audit_from_slot(date_str: str, slot: str, department: str, auditor: str) -> Tuple[bool, str]:
    schedule = load_schedule()
    day = schedule.get("days", {}).get(date_str, {})
    audits = day.get(slot, [])

    new_audits = []
    removed = False
    for a in audits:
        if not removed and a.get("department") == department and a.get("auditor") == auditor:
            removed = True
            continue
        new_audits.append(a)

    if not removed:
        return False, "No matching audit found to remove."

    schedule["days"][date_str][slot] = new_audits
    save_schedule(schedule)
    return True, "Audit removed."


def flatten_timetable(date_str: str) -> List[Dict[str, Any]]:
    schedule = load_schedule()
    day = schedule.get("days", {}).get(date_str, {})

    rows = []
    for slot, audits in sorted(day.items(), key=lambda x: x[0]):
        if not audits:
            rows.append({"Date": date_str, "Time Slot": slot, "Department": "", "Auditor": "", "Status": "Empty"})
        else:
            for a in audits:
                rows.append({
                    "Date": date_str,
                    "Time Slot": slot,
                    "Department": a.get("department", ""),
                    "Auditor": a.get("auditor", ""),
                    "Status": "Scheduled"
                })
    return rows
