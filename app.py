import streamlit as st
from typing import List, Dict, Set
from datetime import datetime, date
from zoneinfo import ZoneInfo

import engine
import timetable  # timetable.py must be in same folder

st.set_page_config(
    page_title="Audit Assignment System",
    page_icon="✅",
    layout="wide",
)

engine.ensure_seed_files()

# -----------------------------
# Session state
# -----------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {
        "logged_in": False,
        "username": None,
        "role": None,
        "person_name": None,
    }


def logout():
    st.session_state.auth = {
        "logged_in": False,
        "username": None,
        "role": None,
        "person_name": None,
    }
    st.rerun()


def require_login():
    if not st.session_state.auth["logged_in"]:
        st.stop()


def audits_table(audits: List[Dict]):
    if not audits:
        st.info("No audits found.")
        return

    rows = []
    for a in audits:
        rows.append(
            {
                "Audit ID": a.get("audit_id"),
                "Title": a.get("title"),
                "Dept": a.get("audited_department"),
                "Auditor": a.get("assigned_auditor"),
                "Status": a.get("status"),
                "Created": a.get("created_at"),
                "Due": a.get("due_date"),
                "Reports": len(a.get("reports", [])),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


# -----------------------------
# Timetable reminder helpers
# -----------------------------
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
            start_dt = datetime.combine(date.fromisoformat(today), datetime.strptime(start_s, "%H:%M").time())
            end_dt = datetime.combine(date.fromisoformat(today), datetime.strptime(end_s, "%H:%M").time())
            if tz:
                start_dt = start_dt.replace(tzinfo=tz)
                end_dt = end_dt.replace(tzinfo=tz)

            if start_dt <= now < end_dt:
                ongoing_msg = f"⏱️ Your audit is happening now ({slot}) for **{dept}**."
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
            st.info(f"🔔 You have an audit in **{mins} min** at **{slot.split('-')[0]}** for **{dept}**.")


# -----------------------------
# Helpers: persistent dropdown options
# -----------------------------
def get_department_options_with_other() -> List[str]:
    return engine.load_departments_catalog() + ["Other"]

def get_skill_catalog() -> Dict[str, str]:
    return engine.load_skills_catalog()


# -----------------------------
# Login UI
# -----------------------------
if not st.session_state.auth["logged_in"]:
    st.title("✅ Audit Assignment System")
    st.caption(
        "RBAC enabled: Admin has full access; Auditor sees only assigned audits; "
        "auditor must upload and submit report before completing an audit."
    )

    with st.form("login_form"):
        username = st.text_input("Username", placeholder="admin or auditor username")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        submitted = st.form_submit_button("Login")

    if submitted:
        ok, u, msg = engine.authenticate(username, password)
        if not ok:
            st.error(msg)
        else:
            st.session_state.auth = {
                "logged_in": True,
                "username": u["username"],
                "role": u["role"],
                "person_name": u.get("person_name"),
            }
            st.success("Logged in.")
            st.rerun()

    st.markdown("### Default seed credentials")
    st.write("- Admin: **admin / admin123**")
    st.write("- Auditor: username is lowercase name (no spaces), password: **auditor123**")
    st.stop()


# -----------------------------
# Main App
# -----------------------------
require_login()

role = st.session_state.auth["role"]
username = st.session_state.auth["username"]
person_name = st.session_state.auth["person_name"]

if role == "auditor" and person_name:
    show_auditor_timetable_reminder(person_name, remind_within_minutes=30)

st.sidebar.title("Navigation")
st.sidebar.write(f"Logged in as: **{username}**")
st.sidebar.write(f"Role: **{role}**")
st.sidebar.button("Logout", on_click=logout)

all_audits = engine.list_audits()

# -----------------------------
# Sidebar menus with nested Checklist
# -----------------------------
checklist_department = None

if role == "admin":
    page = st.sidebar.radio(
        "Admin Menu",
        ["Dashboard", "Auditors & Skills", "Create & Assign Audit", "Audit Plan", "Checklist", "Audit Details"],
        key="admin_menu_radio"
    )

    if page == "Checklist":
        st.sidebar.markdown("**Checklist sub-menu**")
        checklist_department = st.sidebar.radio(
            "Department",
            options=engine.load_departments_catalog(),
            key="admin_checklist_dept_radio"
        )

else:
    page = st.sidebar.radio(
        "Auditor Menu",
        ["My Audits", "My Timetable", "Checklist", "Audit Details"],
        key="auditor_menu_radio"
    )

    if page == "Checklist":
        st.sidebar.markdown("**Checklist sub-menu**")
        my_audits = [a for a in all_audits if a.get("assigned_auditor") == person_name]
        my_depts = sorted({(a.get("audited_department") or "").strip() for a in my_audits if (a.get("audited_department") or "").strip()},
                          key=lambda x: x.lower())
        if not my_depts:
            checklist_department = None
        else:
            checklist_department = st.sidebar.radio(
                "Department",
                options=my_depts,
                key="auditor_checklist_dept_radio"
            )

# -----------------------------
# Admin Pages
# -----------------------------
if role == "admin" and page == "Dashboard":
    st.title("Admin Dashboard")

    st.subheader("All audits")
    audits_table(all_audits)

    st.subheader("Auditor availability (FREE/BUSY)")
    people = engine.load_people()
    state = engine.load_state()
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

elif role == "admin" and page == "Auditors & Skills":
    st.title("Auditors & Skills")
    st.caption("Add auditors (name, dept, skills). New departments/skills added via 'Other' will appear in dropdowns next time.")

    left, right = st.columns([1, 1])

    with left:
        st.subheader("Add New Auditor")
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

            # Skills with OTHER (persistent)
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
                    k = engine.ensure_skill_in_catalog(lbl)
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
                    engine.add_department_to_catalog(department.strip())

                ok, msg = engine.add_auditor(
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

        st.divider()
        st.subheader("Department required skills")
        dept_req = engine.load_dept_required_skills()
        skill_cat = get_skill_catalog()
        for dept in engine.load_departments_catalog():
            req_keys = dept_req.get(dept, [])
            pretty = [skill_cat.get(k, k) for k in req_keys]
            st.write(f"**{dept}**")
            st.write(pretty if pretty else ["(No required skills defined yet)"])

    with right:
        st.subheader("Auditor Dashboard (people.json)")
        people_raw = engine.list_people_records()
        state = engine.load_state()
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
            ok, msg = engine.delete_auditor(delete_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

elif role == "admin" and page == "Create & Assign Audit":
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
        existing_req = engine.get_required_skills_for_dept(target_dept) if target_dept else set()

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
                req_keys.append(engine.ensure_skill_in_catalog(lbl))
            required_override = set(req_keys) if req_keys else set()
            save_as_default = st.checkbox("Save these required skills as default for this department", value=True)

    with col2:
        scope = st.text_area("Scope (optional)", placeholder="Write scope or checklist reference...")
        due_date = st.text_input("Due Date (optional)", placeholder="YYYY-MM-DD")

    if st.button("Assign Auditor", type="primary"):
        if not target_dept:
            st.error("Department is required.")
        else:
            audit, msg = engine.create_and_assign_audit(
                created_by=username,
                target_dept=target_dept,
                allow_fresher_fallback=allow_fallback,
                title=title,
                scope=scope,
                due_date=due_date,
                required_skill_keys_override=required_override if required_override is not None and len(required_override) > 0 else None,
                save_required_skills_as_default=save_as_default,
            )
            if not audit:
                st.error(msg)
            else:
                st.success(msg)
                st.json(audit)

elif role == "admin" and page == "Audit Plan":
    import pandas as pd
    from datetime import date

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

        required = engine.get_required_skills_for_dept(audited_dept) if audited_dept else set()
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
            req_keys = [engine.ensure_skill_in_catalog(lbl) for lbl in labels]
            required = set(req_keys)
            save_as_default = st.checkbox("Save as default required skills for this department", value=True, key="tt_save_req")

        people = engine.load_people()
        state = engine.load_state()
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
                engine.add_department_to_catalog(audited_dept)
                if save_as_default:
                    engine.set_dept_required_skills(audited_dept, sorted(required))

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

elif role == "admin" and page == "Checklist":
    st.title("Checklist (Admin)")
    st.caption("Create department-wise checklists with sections. Auditors will fill Observation and Evidence during audits.")

    import pandas as pd

    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu.")
        st.stop()

    dept_for_checklist = checklist_department

    st.subheader(f"Department: {dept_for_checklist}")

    sections = engine.get_sections_for_department(dept_for_checklist)
    pick_section = st.selectbox("Section", ["(Create New)"] + sections, key=f"chk_admin_section_{dept_for_checklist}")

    new_section = ""
    if pick_section == "(Create New)":
        new_section = st.text_input("New Section Name", key=f"chk_admin_new_section_{dept_for_checklist}").strip()

    section_name = new_section if pick_section == "(Create New)" else pick_section

    existing_items = engine.get_items_for_department_section(dept_for_checklist, section_name) if section_name else []
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
                engine.upsert_section_items(dept_for_checklist, section_name, cleaned)
                st.success(f"Saved checklist for: {dept_for_checklist} → {section_name}")
                st.rerun()

    with cB:
        if pick_section != "(Create New)" and st.button("Delete Section", key=f"chk_admin_delete_{dept_for_checklist}_{pick_section}"):
            engine.delete_section(dept_for_checklist, pick_section)
            st.success(f"Deleted section: {dept_for_checklist} → {pick_section}")
            st.rerun()

    with cC:
        st.info("Tip: Create sections like Resource Planning, Onboarding, Training Planning, etc.")

elif role == "auditor" and page == "Checklist":
    st.title("Checklist (Auditor)")
    st.caption("Pick your department from sidebar; then select the audit and section to fill Observation and Evidence.")

    import pandas as pd

    my_audits = [a for a in all_audits if a.get("assigned_auditor") == person_name]

    if not my_audits:
        st.info("No audits assigned to you yet.")
        st.stop()

    if not checklist_department:
        st.info("Select a department from the sidebar Checklist sub-menu.")
        st.stop()

    dept = checklist_department
    dept_audits = [a for a in my_audits if (a.get("audited_department") or "").strip().lower() == dept.strip().lower()]

    if not dept_audits:
        st.info(f"No audits assigned to you for department: {dept}")
        st.stop()

    audit_options = [
        f'{a.get("audit_id")} | {a.get("title") or "-"} | Status: {a.get("status")}'
        for a in dept_audits
    ]
    pick = st.selectbox("Select Audit", options=audit_options, key=f"aud_chk_pick_audit_{dept}")

    audit_id = pick.split("|", 1)[0].strip()
    audit = engine.get_audit(audit_id)

    if not audit:
        st.error("Audit not found.")
        st.stop()

    sections = engine.get_sections_for_department(dept)
    if not sections:
        st.info(f"No checklist sections found for department '{dept}'. Ask Admin to create them.")
        st.stop()

    section = st.selectbox("Select Checklist Section", options=sections, key=f"aud_chk_section_{audit_id}_{dept}")

    saved_rows = engine.load_audit_section_table(audit_id, dept, section)
    if saved_rows:
        df = pd.DataFrame(saved_rows)
        df = df.rename(columns={
            "sr_no": "SR No",
            "checklist": "Checklist",
            "observation": "Observation",
            "evidence": "Evidence",
        })
    else:
        items = engine.get_items_for_department_section(dept, section)
        df = pd.DataFrame({
            "SR No": list(range(1, len(items) + 1)),
            "Checklist": items,
            "Observation": ["" for _ in items],
            "Evidence": ["" for _ in items],
        })

    st.caption("Fill Observation and Evidence. SR No and Checklist are locked.")
    edited = st.data_editor(
        df,
        use_container_width=True,
        disabled=["SR No", "Checklist"],
        key=f"aud_chk_editor_{audit_id}_{dept}_{section}",
    )

    if st.button("Save Checklist Observations", type="primary", key=f"aud_chk_save_{audit_id}_{dept}_{section}"):
        rows_to_save = []
        for _, r in edited.iterrows():
            rows_to_save.append({
                "sr_no": str(r.get("SR No", "")).strip(),
                "checklist": str(r.get("Checklist", "")).strip(),
                "observation": str(r.get("Observation", "")).strip(),
                "evidence": str(r.get("Evidence", "")).strip(),
            })
        ok, msg = engine.save_audit_section_table(audit_id, dept, section, rows_to_save)
        if ok:
            st.success(f"Saved: {dept} → {section}")
            st.rerun()
        else:
            st.error(msg)

elif (role == "admin" and page == "Audit Details") or (role == "auditor" and page == "Audit Details"):
    st.title("Audit Details")

    audit_ids = [a.get("audit_id") for a in all_audits]
    selected_id = st.selectbox("Select Audit ID", options=audit_ids)

    audit = engine.get_audit(selected_id) if selected_id else None
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

    # -----------------------------
    # Section-wise checklist (Admin view + Auditor fill)
    # -----------------------------
    st.divider()
    st.subheader("Department Checklist (Section-wise)")

    import pandas as pd

    dept = audit.get("audited_department", "")
    sections = engine.get_sections_for_department(dept)

    if not sections:
        if role == "admin":
            st.info(
                f"No checklist sections found for department '{dept}'. "
                "Go to Admin Menu → Checklist to add sections and items."
            )
        else:
            st.info(
                f"No checklist sections found for department '{dept}'. "
                "Ask Admin to add checklist sections and items."
            )
    else:
        section = st.selectbox("Select Checklist Section", options=sections, key=f"sec_pick_{audit.get('audit_id')}")

        saved_rows = engine.load_audit_section_table(audit.get("audit_id"), dept, section)

        if saved_rows:
            df = pd.DataFrame(saved_rows)
            df = df.rename(columns={
                "sr_no": "SR No",
                "checklist": "Checklist",
                "observation": "Observation",
                "evidence": "Evidence",
            })
        else:
            items = engine.get_items_for_department_section(dept, section)
            df = pd.DataFrame({
                "SR No": list(range(1, len(items) + 1)),
                "Checklist": items,
                "Observation": ["" for _ in items],
                "Evidence": ["" for _ in items],
            })

        if role == "auditor":
            st.caption("Fill Observation and Evidence. SR No and Checklist are locked.")
            edited = st.data_editor(
                df,
                use_container_width=True,
                disabled=["SR No", "Checklist"],
                key=f"aud_chk_{audit.get('audit_id')}_{section}",
            )

            if st.button("Save Checklist Observations", type="primary", key=f"save_chk_{audit.get('audit_id')}_{section}"):
                rows_to_save = []
                for _, r in edited.iterrows():
                    rows_to_save.append({
                        "sr_no": str(r.get("SR No", "")).strip(),
                        "checklist": str(r.get("Checklist", "")).strip(),
                        "observation": str(r.get("Observation", "")).strip(),
                        "evidence": str(r.get("Evidence", "")).strip(),
                    })
                ok, msg = engine.save_audit_section_table(audit.get("audit_id"), dept, section, rows_to_save)
                if ok:
                    st.success(f"Saved: {dept} → {section}")
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.caption("Admin view (read-only). Auditors fill Observation and Evidence.")
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Reports")
    reports = audit.get("reports", [])
    if not reports:
        st.info("No reports uploaded yet.")
    else:
        for r in reports:
            st.write(
                f"- {r.get('file_name')} | uploaded_by: {r.get('uploaded_by')} | uploaded_at: {r.get('uploaded_at')}"
            )
            if role == "admin":
                try:
                    with open(r.get("saved_path", ""), "rb") as f:
                        st.download_button(
                            label=f"Download: {r.get('file_name')}",
                            data=f.read(),
                            file_name=r.get("file_name"),
                            mime="application/octet-stream",
                            key=f"dl_{audit.get('audit_id')}_{r.get('saved_path')}",
                        )
                except Exception:
                    st.warning("Download unavailable for this file path.")

    if role == "auditor":
        st.subheader("Auditor Actions")

        st.markdown("#### 1) Upload Report (PDF/XLSX/XLS/CSV)")
        up = st.file_uploader("Choose a file", type=["pdf", "xlsx", "xls", "csv"])
        if up is not None:
            if st.button("Upload Report"):
                ok, msg = engine.save_report_file(
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
        if st.button("Submit Report", type="primary"):
            ok, msg = engine.submit_report(audit["audit_id"], person_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

        st.markdown("#### 3) Complete Audit (blocked without submission)")
        if st.button("Complete Audit"):
            ok, msg = engine.complete_audit(audit["audit_id"], person_name)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    if role == "admin":
        st.subheader("Admin Controls")
        new_status = st.selectbox(
            "Set Status",
            ["Assigned", "In Progress", "Report Submitted", "Closed"],
            index=["Assigned", "In Progress", "Report Submitted", "Closed"].index(audit.get("status", "Assigned")),
        )
        if st.button("Update Status"):
            ok, msg = engine.set_audit_status(audit["audit_id"], new_status)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# -----------------------------
# Auditor Pages
# -----------------------------
if role == "auditor" and page == "My Audits":
    st.title("My Audits")
    my = [a for a in all_audits if a.get("assigned_auditor") == person_name]
    audits_table(my)
    st.info("Rule: Upload at least one report, submit it, then you can complete the audit.")

elif role == "auditor" and page == "My Timetable":
    import pandas as pd
    from datetime import timedelta

    st.title("My Timetable")
    st.caption("Shows the timetable slots assigned to you by Admin.")

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
