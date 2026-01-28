# report_generator.py
# -----------------------------
# Generates a single PDF report for selected audits (typically Report Submitted / Closed).
# Reads audits via engine.get_audit().
# Writes the PDF under the tenant folder and registers it in engine's Generated Final Reports store.
#
# Output PDF (per-tenant):
#   uploads/tenants/<tenant_id>/generated_reports/<filename>.pdf
#
# Dependencies:
#   reportlab
# -----------------------------

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

import engine


# -----------------------------
# Small utilities
# -----------------------------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_text(s) -> str:
    return " ".join(str(s or "").replace("\n", " ").replace("\r", " ").split())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _tenant_generated_reports_dir(tenant_id: str) -> str:
    # Keep consistent with engine's multi-tenant storage layout
    return os.path.join(engine.UPLOADS_DIR, "tenants", str(tenant_id), "generated_reports")


def _audit_primary_key(a: Dict) -> str:
    """
    Return the canonical identifier stored in the audit payload.
    Some versions store "audit_id", some store "id".
    """
    return _safe_text(a.get("audit_id")) or _safe_text(a.get("id"))


def _engine_get_audit(audit_id: str, tenant_id: str) -> Optional[Dict]:
    """
    Call engine.get_audit in a backwards compatible way.
    """
    try:
        return engine.get_audit(audit_id, tenant_id=tenant_id)
    except TypeError:
        # older engine without tenant_id
        return engine.get_audit(audit_id)


def _engine_register_final_report(
    *,
    tenant_id: str,
    created_by: str,
    pdf_rel_path: str,
    audit_ids: List[str],
    summary: str,
    allowed_users: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Call engine.register_final_generated_report in a backwards compatible way.

    IMPORTANT: Your current engine.py supports:
      register_final_generated_report(created_by, summary, audit_ids, pdf_rel_path, allowed_users, tenant_id)
    """
    try:
        ok, _row, msg = engine.register_final_generated_report(
            tenant_id=tenant_id,
            created_by=created_by,
            summary=summary,
            audit_ids=audit_ids,
            pdf_rel_path=pdf_rel_path,
            allowed_users=allowed_users,
        )
        return bool(ok), str(msg)
    except TypeError:
        # older engine without tenant_id param (and maybe different return shape)
        try:
            ok, _row, msg = engine.register_final_generated_report(
                created_by=created_by,
                summary=summary,
                audit_ids=audit_ids,
                pdf_rel_path=pdf_rel_path,
                allowed_users=allowed_users,
            )
            return bool(ok), str(msg)
        except Exception as e:
            return False, f"Engine register failed: {e}"
    except Exception as e:
        return False, f"Engine register failed: {e}"


def get_audit_display_date(audit: Dict) -> str:
    """
    Date priority:
      1) closed_at
      2) report_submitted_at
      3) created_at
    Returns as string as-is (ISO stored by your engine).
    """
    return (
        _safe_text(audit.get("closed_at"))
        or _safe_text(audit.get("report_submitted_at"))
        or _safe_text(audit.get("created_at"))
        or "-"
    )


def _audit_display_title(a: Dict) -> str:
    return _safe_text(a.get("title")) or "Untitled"


def _audit_display_dept(a: Dict) -> str:
    # Your app uses audited_department
    return _safe_text(a.get("audited_department")) or _safe_text(a.get("department")) or "-"


def _audit_display_auditor(a: Dict) -> str:
    return _safe_text(a.get("assigned_auditor")) or _safe_text(a.get("auditor")) or "-"


def _kv_line(k: str, v: str) -> str:
    return f"{k}: {(_safe_text(v) or '-')}"



# -----------------------------
# PDF layout helpers
# -----------------------------
def _new_page(c: canvas.Canvas, title: str = "") -> Dict[str, float]:
    c.showPage()
    w, h = A4
    y = h - 18 * mm
    if title:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(18 * mm, y, title)
        y -= 10 * mm
    return {"w": w, "h": h, "y": y}


def _draw_wrapped_text(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    font_name: str = "Helvetica",
    font_size: int = 10,
    leading: float = 12,
) -> float:
    """
    Draw wrapped text at (x, y) downward.
    Returns the new y after drawing.
    """
    c.setFont(font_name, font_size)
    lines = simpleSplit(text or "", font_name, font_size, max_width)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _ensure_space_or_page(
    c: canvas.Canvas,
    y: float,
    needed: float,
    page_title: str = "",
) -> float:
    """
    If not enough vertical space, create new page and return new y.
    """
    bottom_margin = 18 * mm
    if y - needed < bottom_margin:
        state = _new_page(c, page_title)
        return state["y"]
    return y


# -----------------------------
# Core: Generate PDF
# -----------------------------
def generate_final_audit_report_pdf(
    *,
    tenant_id: str,
    generated_by: str,
    selected_audit_ids: List[str],
    admin_summaries_by_audit_id: Dict[str, str],
    output_filename: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Creates one PDF report for selected audits.

    admin_summaries_by_audit_id:
      dict where keys MUST be the same IDs passed in selected_audit_ids.
      { "<selected_id>": "<summary text written by admin>" }

    Returns:
      (ok, message, saved_pdf_abs_path_or_None)
    """
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return False, "Tenant not found in session. Please logout and login again.", None

    # Validate selection
    ids = [str(x or "").strip() for x in (selected_audit_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))  # de-dup, preserve order
    if not ids:
        return False, "No audits selected.", None

    # Load audits while preserving the selected ID for summary mapping
    audits: List[Dict] = []
    missing_ids: List[str] = []

    for selected_id in ids:
        a = _engine_get_audit(selected_id, tenant_id)
        if a:
            a["_selected_id"] = str(selected_id)
            audits.append(a)
        else:
            missing_ids.append(selected_id)

    if not audits:
        if missing_ids:
            return False, "Selected audits were not found.", None
        return False, "No audits selected.", None

    # Sort audits: by date then title then dept then auditor
    def _sort_key(a: Dict):
        dt = get_audit_display_date(a)
        title = _audit_display_title(a).lower()
        dept = _audit_display_dept(a).lower()
        auditor = _audit_display_auditor(a).lower()
        return (dt, title, dept, auditor)

    audits.sort(key=_sort_key)

    # File name
    if not output_filename:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = f"Final_Audit_Report_{stamp}.pdf"
    if not output_filename.lower().endswith(".pdf"):
        output_filename = output_filename + ".pdf"

    # Ensure tenant report folder
    reports_dir = _tenant_generated_reports_dir(tenant_id)
    _ensure_dir(reports_dir)

    pdf_abs_path = os.path.join(reports_dir, output_filename)

    # Build PDF
    c = canvas.Canvas(pdf_abs_path, pagesize=A4)
    w, h = A4
    max_w = w - 36 * mm

    # -------------------------
    # Cover page
    # -------------------------
    y = h - 22 * mm
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, y, "Final Audit Report")
    y -= 10 * mm

    c.setFont("Helvetica", 11)
    c.drawString(18 * mm, y, _kv_line("Generated at", _now_iso()))
    y -= 6 * mm
    c.drawString(18 * mm, y, _kv_line("Generated by", generated_by))
    y -= 6 * mm
    c.drawString(18 * mm, y, _kv_line("Tenant", tenant_id))
    y -= 10 * mm

    if missing_ids:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(18 * mm, y, "Warning: Some selected audits were not found and were skipped:")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for mid in missing_ids:
            y = _ensure_space_or_page(c, y, needed=8 * mm, page_title="Final Audit Report")
            y = _draw_wrapped_text(c, f"- {mid}", 20 * mm, y, max_w, font_name="Helvetica", font_size=9, leading=11)
        y -= 6 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(18 * mm, y, f"Included audits: {len(audits)}")
    y -= 10 * mm

    # Summary list
    c.setFont("Helvetica-Bold", 10)
    c.drawString(18 * mm, y, "Summary List")
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    for idx, a in enumerate(audits, start=1):
        audit_key = _audit_primary_key(a) or _safe_text(a.get("_selected_id"))
        label = (
            f"{idx}. {_audit_display_title(a)} | {_audit_display_dept(a)}"
            f" | Auditor: {_audit_display_auditor(a)}"
            f" | Date: {get_audit_display_date(a)}"
            f" | ID: {audit_key}"
        )
        y = _ensure_space_or_page(c, y, needed=10 * mm, page_title="Final Audit Report")
        y = _draw_wrapped_text(c, label, 18 * mm, y, max_w, font_name="Helvetica", font_size=9, leading=11)

    # -------------------------
    # Details pages
    # -------------------------
    c.showPage()
    y = h - 18 * mm

    for idx, a in enumerate(audits, start=1):
        selected_id = _safe_text(a.get("_selected_id"))
        audit_key = _audit_primary_key(a) or selected_id
        title = _audit_display_title(a)
        auditor = _audit_display_auditor(a)
        dept = _audit_display_dept(a)
        date_str = get_audit_display_date(a)
        status = _safe_text(a.get("status")) or "-"

        # Header per audit
        y = _ensure_space_or_page(c, y, needed=55 * mm, page_title="")
        c.setFont("Helvetica-Bold", 13)
        c.drawString(18 * mm, y, f"Audit {idx}: {title}")
        y -= 8 * mm

        c.setFont("Helvetica", 10)
        c.drawString(18 * mm, y, _kv_line("Audit ID", audit_key))
        y -= 6 * mm
        c.drawString(18 * mm, y, _kv_line("Status", status))
        y -= 6 * mm
        c.drawString(18 * mm, y, _kv_line("Auditor Name", auditor))
        y -= 6 * mm
        c.drawString(18 * mm, y, _kv_line("Audited Department", dept))
        y -= 6 * mm
        c.drawString(18 * mm, y, _kv_line("Date", date_str))
        y -= 6 * mm

        # Admin Summary
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18 * mm, y, "Summary (Admin)")
        y -= 6 * mm

        # IMPORTANT: map summary by SELECTED ID (matches app.py selection)
        summary = _safe_text((admin_summaries_by_audit_id or {}).get(selected_id, "")).strip()
        if not summary:
            summary = "(No summary provided.)"

        y = _ensure_space_or_page(c, y, needed=22 * mm, page_title=title)
        y = _draw_wrapped_text(c, summary, 18 * mm, y, max_w, font_name="Helvetica", font_size=10, leading=13)
        y -= 4 * mm

        # Checklist
        c.setFont("Helvetica-Bold", 11)
        y = _ensure_space_or_page(c, y, needed=12 * mm, page_title=title)
        c.drawString(18 * mm, y, "Checklist")
        y -= 7 * mm

        checklists = a.get("checklists", {})
        dept_block = checklists.get(dept, {}) if isinstance(checklists, dict) else {}

        if not isinstance(dept_block, dict) or not dept_block:
            c.setFont("Helvetica", 10)
            c.drawString(18 * mm, y, "(Checklist not filled for this audit.)")
            y -= 10 * mm
        else:
            for section_name in sorted(dept_block.keys(), key=lambda x: str(x).lower()):
                rows = dept_block.get(section_name, [])
                if not isinstance(rows, list):
                    continue

                y = _ensure_space_or_page(c, y, needed=14 * mm, page_title=title)
                c.setFont("Helvetica-Bold", 10)
                c.drawString(18 * mm, y, f"Section: {_safe_text(section_name)}")
                y -= 6 * mm

                for r in rows:
                    if not isinstance(r, dict):
                        continue

                    sr = _safe_text(r.get("sr_no")) or "-"
                    chk = _safe_text(r.get("checklist")) or "-"
                    obs = _safe_text(r.get("observation")) or "-"
                    evd = _safe_text(r.get("evidence")) or "-"

                    block = f"{sr}. {chk}\nObservation: {obs}\nEvidence: {evd}"
                    y = _ensure_space_or_page(c, y, needed=18 * mm, page_title=title)
                    y = _draw_wrapped_text(
                        c,
                        block,
                        20 * mm,
                        y,
                        max_w - 2 * mm,
                        font_name="Helvetica",
                        font_size=9,
                        leading=11,
                    )
                    y -= 2 * mm

                y -= 3 * mm

        # Submitted files list
        y = _ensure_space_or_page(c, y, needed=16 * mm, page_title=title)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18 * mm, y, "Submitted Files")
        y -= 7 * mm

        reports = a.get("reports", [])
        if not isinstance(reports, list) or not reports:
            c.setFont("Helvetica", 10)
            c.drawString(18 * mm, y, "(No files uploaded.)")
            y -= 10 * mm
        else:
            c.setFont("Helvetica", 9)
            for rr in reports:
                if not isinstance(rr, dict):
                    continue
                fname = _safe_text(rr.get("file_name")) or "-"
                uploaded_at = _safe_text(rr.get("uploaded_at")) or "-"
                uploaded_by = _safe_text(rr.get("uploaded_by")) or "-"
                line = f"- {fname} | uploaded_by: {uploaded_by} | uploaded_at: {uploaded_at}"
                y = _ensure_space_or_page(c, y, needed=10 * mm, page_title=title)
                y = _draw_wrapped_text(c, line, 18 * mm, y, max_w, font_name="Helvetica", font_size=9, leading=11)

            y -= 4 * mm

        # Separator line
        y = _ensure_space_or_page(c, y, needed=12 * mm, page_title=title)
        c.line(18 * mm, y, w - 18 * mm, y)
        y -= 10 * mm

    c.save()

    # Register in engine
    pdf_rel_path = os.path.join("generated_reports", output_filename).replace("\\", "/")

    # IMPORTANT: engine expects real audit_ids, not display ids
    audit_ids_for_engine: List[str] = []
    for a in audits:
        real_id = _audit_primary_key(a)
        if real_id:
            audit_ids_for_engine.append(real_id)

    audit_ids_for_engine = [x for x in audit_ids_for_engine if x]
    audit_ids_for_engine = list(dict.fromkeys(audit_ids_for_engine))

    # Build one consolidated summary stored in DB (engine has only "summary" field)
    # This is separate from per-audit summaries inside the PDF.
    summary_lines: List[str] = []
    summary_lines.append(f"Final report generated by {generated_by} at {_now_iso()}.")
    summary_lines.append(f"Included audits: {len(audits)}.")
    summary_lines.append("Audit list:")
    for i, a in enumerate(audits, start=1):
        sid = _safe_text(a.get("_selected_id"))
        t = _audit_display_title(a)
        d = _audit_display_dept(a)
        au = _audit_display_auditor(a)
        st = _safe_text(a.get("status")) or "-"
        summary_lines.append(f"{i}. {t} | {d} | Auditor: {au} | Status: {st} | SelectedID: {sid}")

    consolidated_summary = "\n".join(summary_lines)

    ok, msg = _engine_register_final_report(
        tenant_id=tenant_id,
        created_by=_safe_text(generated_by),
        pdf_rel_path=pdf_rel_path,
        audit_ids=audit_ids_for_engine,
        summary=consolidated_summary,
        allowed_users=None,  # let engine auto-derive (admin + auditors)
    )

    if not ok:
        return False, f"PDF created but could not be registered: {msg}", pdf_abs_path

    return True, f"Report generated: {output_filename}", pdf_abs_path
