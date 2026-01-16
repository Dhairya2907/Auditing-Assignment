# report_generator.py
# -----------------------------
# Generates a single PDF report for CLOSED audits.
# Reads audits via engine.list_audits() and engine.get_audit().
# Does NOT modify audits.json (read-only).
#
# Output:
#   uploads/generated_reports/<filename>.pdf
#   uploads/generated_reports/generated_reports.json  (metadata log)
#
# Dependencies:
#   reportlab (already available in your environment per your setup)
# -----------------------------

from __future__ import annotations

# report_generator.py
# -----------------------------
# Generates a single PDF report for CLOSED audits.
# Reads audits via engine.list_audits() and engine.get_audit().
# Does NOT modify audits.json (read-only).
#
# Output:
#   uploads/generated_reports/<filename>.pdf
#   uploads/generated_reports/generated_reports.json  (metadata log)
#
# Dependencies:
#   reportlab
# -----------------------------

import os
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

# Your existing modules
import engine


# -----------------------------
# Config
# -----------------------------
REPORTS_DIR = os.path.join(engine.UPLOADS_DIR, "generated_reports")
REPORTS_INDEX_FILE = os.path.join(REPORTS_DIR, "generated_reports.json")


# -----------------------------
# Small utilities
# -----------------------------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_text(s) -> str:
    return " ".join(str(s or "").replace("\n", " ").replace("\r", " ").split())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def ensure_reports_storage() -> None:
    _ensure_dir(REPORTS_DIR)
    if not os.path.exists(REPORTS_INDEX_FILE):
        _write_json(REPORTS_INDEX_FILE, {"reports": []})


def list_generated_reports() -> List[Dict]:
    ensure_reports_storage()
    data = _read_json(REPORTS_INDEX_FILE, {"reports": []})
    reports = data.get("reports", [])
    return reports if isinstance(reports, list) else []

def delete_generated_report(report_id: str) -> Tuple[bool, str]:
    """
    Deletes a generated report entry and its PDF file.
    Admin-only enforcement must be done in app.py.
    """
    ensure_reports_storage()
    report_id = str(report_id or "").strip()
    if not report_id:
        return False, "Invalid report id."

    data = _read_json(REPORTS_INDEX_FILE, {"reports": []})
    reports = data.get("reports", [])
    if not isinstance(reports, list) or not reports:
        return False, "No reports found."

    kept: List[Dict] = []
    target: Optional[Dict] = None

    for r in reports:
        if not isinstance(r, dict):
            continue
        if str(r.get("report_id", "")).strip() == report_id:
            target = r
        else:
            kept.append(r)

    if not target:
        return False, "Report not found."

    # Delete PDF file (best effort)
    file_path = str(target.get("file_path", "") or "").strip()
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            return False, f"Could not delete PDF file: {e}"

    # Save updated index
    data["reports"] = kept
    _write_json(REPORTS_INDEX_FILE, data)

    return True, "Report deleted successfully."


def _append_report_index(entry: Dict) -> None:
    ensure_reports_storage()
    data = _read_json(REPORTS_INDEX_FILE, {"reports": []})
    if not isinstance(data, dict):
        data = {"reports": []}
    if not isinstance(data.get("reports", []), list):
        data["reports"] = []
    data["reports"].append(entry)
    _write_json(REPORTS_INDEX_FILE, data)


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
    generated_by: str,
    admin_summaries_by_audit_id: Dict[str, str],
    include_statuses: Optional[List[str]] = None,
    output_filename: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Creates one PDF report for audits matching include_statuses (default: ["Closed"]).

    admin_summaries_by_audit_id:
      { "<audit_id>": "<summary text written by admin>" }

    Returns:
      (ok, message, saved_pdf_path_or_None)
    """
    engine.ensure_seed_files()
    ensure_reports_storage()

    statuses = include_statuses or ["Closed"]
    statuses_lower = {s.strip().lower() for s in statuses if str(s).strip()}

    all_audits = engine.list_audits()
    selected = [
        a for a in all_audits
        if str(a.get("status", "")).strip().lower() in statuses_lower
    ]

    if not selected:
        return False, "No audits found for selected statuses.", None

    # Sort audits: by date then title then dept then auditor
    def _sort_key(a: Dict):
        dt = get_audit_display_date(a)
        title = _safe_text(a.get("title")).lower()
        dept = _safe_text(a.get("audited_department")).lower()
        auditor = _safe_text(a.get("assigned_auditor")).lower()
        return (dt, title, dept, auditor)

    selected.sort(key=_sort_key)

    # File name
    if not output_filename:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = f"Final_Audit_Report_{stamp}.pdf"

    pdf_path = os.path.join(REPORTS_DIR, output_filename)

    # Build PDF
    c = canvas.Canvas(pdf_path, pagesize=A4)
    w, h = A4
    max_w = w - 36 * mm

    # Cover page
    y = h - 22 * mm
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, y, "Final Audit Report")
    y -= 10 * mm

    c.setFont("Helvetica", 11)
    c.drawString(18 * mm, y, f"Generated at: {_now_iso()}")
    y -= 6 * mm
    c.drawString(18 * mm, y, f"Generated by: {_safe_text(generated_by) or '-'}")
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(18 * mm, y, f"Included audits (status: {', '.join(statuses)}): {len(selected)}")
    y -= 10 * mm

    # Simple overall list
    c.setFont("Helvetica-Bold", 10)
    c.drawString(18 * mm, y, "Summary List")
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    for idx, a in enumerate(selected, start=1):
        label = f"{idx}. {(_safe_text(a.get('title')) or 'Untitled')} | {(_safe_text(a.get('audited_department')) or '-')}"
        label += f" | Auditor: {(_safe_text(a.get('assigned_auditor')) or '-')}"
        label += f" | Date: {get_audit_display_date(a)}"
        y = _ensure_space_or_page(c, y, needed=10 * mm, page_title="Final Audit Report")
        y = _draw_wrapped_text(c, label, 18 * mm, y, max_w, font_name="Helvetica", font_size=9, leading=11)

    # Start details pages
    c.showPage()
    y = h - 18 * mm

    for idx, a in enumerate(selected, start=1):
        audit_id = _safe_text(a.get("audit_id"))
        title = _safe_text(a.get("title")) or "Untitled"
        auditor = _safe_text(a.get("assigned_auditor")) or "-"
        dept = _safe_text(a.get("audited_department")) or "-"
        date_str = get_audit_display_date(a)

        # Header per audit
        y = _ensure_space_or_page(c, y, needed=45 * mm, page_title="")
        c.setFont("Helvetica-Bold", 13)
        c.drawString(18 * mm, y, f"Audit {idx}: {title}")
        y -= 8 * mm

        c.setFont("Helvetica", 10)
        c.drawString(18 * mm, y, f"Auditor Name: {auditor}")
        y -= 6 * mm
        c.drawString(18 * mm, y, f"Audited Department: {dept}")
        y -= 6 * mm
        c.drawString(18 * mm, y, f"Date: {date_str}")
        y -= 6 * mm

        # Admin Summary
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18 * mm, y, "Summary (Admin)")
        y -= 6 * mm

        summary = _safe_text(admin_summaries_by_audit_id.get(audit_id, "")).strip()
        if not summary:
            summary = "(No summary provided.)"

        y = _ensure_space_or_page(c, y, needed=20 * mm, page_title=title)
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
                    y = _draw_wrapped_text(c, block, 20 * mm, y, max_w - 2 * mm, font_name="Helvetica", font_size=9, leading=11)
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

    # Write metadata entry
    entry = {
        "report_id": str(uuid.uuid4()),
        "file_name": output_filename,
        "file_path": pdf_path,
        "generated_at": _now_iso(),
        "generated_by": _safe_text(generated_by),
        "statuses_included": statuses,
        "audit_ids_included": [(_safe_text(a.get("audit_id"))) for a in selected if _safe_text(a.get("audit_id"))],
    }
    _append_report_index(entry)

    return True, f"Report generated: {output_filename}", pdf_path
