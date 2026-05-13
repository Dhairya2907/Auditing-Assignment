# report_generator.py
# -----------------------------
# Generates a single PDF report for selected audits.
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

# ReportLab Platypus (flowable-based layout)
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER

import engine


# ─────────────────────────────────────────────
# Small utilities
# ─────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_text(s) -> str:
    return " ".join(str(s or "").replace("\n", " ").replace("\r", " ").split())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _tenant_generated_reports_dir(tenant_id: str) -> str:
    return os.path.join(engine.UPLOADS_DIR, "tenants", str(tenant_id), "generated_reports")


def _audit_primary_key(a: Dict) -> str:
    return _safe_text(a.get("audit_id")) or _safe_text(a.get("id"))


def _engine_get_audit(audit_id: str, tenant_id: str) -> Optional[Dict]:
    try:
        return engine.get_audit(audit_id, tenant_id=tenant_id)
    except TypeError:
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
    return (
        _safe_text(audit.get("closed_at"))
        or _safe_text(audit.get("report_submitted_at"))
        or _safe_text(audit.get("created_at"))
        or "-"
    )


def _audit_display_title(a: Dict) -> str:
    return _safe_text(a.get("title")) or "Untitled"


def _audit_display_dept(a: Dict) -> str:
    return _safe_text(a.get("audited_department")) or _safe_text(a.get("department")) or "-"


def _audit_display_auditor(a: Dict) -> str:
    return _safe_text(a.get("assigned_auditor")) or _safe_text(a.get("auditor")) or "-"


# ─────────────────────────────────────────────
# NC detection
# ─────────────────────────────────────────────
def _is_non_conformity(row: Dict) -> bool:
    """
    A row is a non-conformity when:
      • nc_if_no=True and observation is 'No'  (production / direct-NC style)
      • OR branch_answers.final_comment contains 'non-conformity'  (CAPA style)
    """
    obs = str(row.get("observation", "") or "").strip().lower()
    nc_flag = bool(row.get("nc_if_no", False))
    if nc_flag and obs == "no":
        return True
    branch = row.get("branch_answers") or {}
    if isinstance(branch, dict):
        comment = str(branch.get("final_comment", "") or "").lower()
        if "non-conformity" in comment:
            return True
    return False


# ─────────────────────────────────────────────
# Style helpers
# ─────────────────────────────────────────────
def _build_styles():
    base = getSampleStyleSheet()
    normal = base["Normal"]

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=normal,
        fontSize=20,
        fontName="Helvetica-Bold",
        spaceAfter=6,
        textColor=colors.HexColor("#1e293b"),
    )
    h1 = ParagraphStyle(
        "H1",
        parent=normal,
        fontSize=14,
        fontName="Helvetica-Bold",
        spaceAfter=4,
        spaceBefore=10,
        textColor=colors.HexColor("#1e293b"),
    )
    h2 = ParagraphStyle(
        "H2",
        parent=normal,
        fontSize=11,
        fontName="Helvetica-Bold",
        spaceAfter=3,
        spaceBefore=6,
        textColor=colors.HexColor("#334155"),
    )
    h3 = ParagraphStyle(
        "H3",
        parent=normal,
        fontSize=10,
        fontName="Helvetica-Bold",
        spaceAfter=2,
        spaceBefore=4,
        textColor=colors.HexColor("#475569"),
    )
    body = ParagraphStyle(
        "Body",
        parent=normal,
        fontSize=9,
        fontName="Helvetica",
        spaceAfter=2,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    cell = ParagraphStyle(
        "Cell",
        parent=normal,
        fontSize=8,
        fontName="Helvetica",
        leading=11,
        textColor=colors.HexColor("#1e293b"),
        wordWrap="LTR",
    )
    cell_hdr = ParagraphStyle(
        "CellHdr",
        parent=normal,
        fontSize=8,
        fontName="Helvetica-Bold",
        leading=11,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    nc_cell = ParagraphStyle(
        "NCCell",
        parent=cell,
        textColor=colors.HexColor("#991b1b"),
    )
    return {
        "title": title_style, "h1": h1, "h2": h2, "h3": h3,
        "body": body, "cell": cell, "cell_hdr": cell_hdr, "nc_cell": nc_cell,
    }


def _make_on_page(report_settings: Dict):
    """Return an onPage callback that applies footer + watermark from settings."""
    ftr = report_settings.get("footer", {})
    wm  = report_settings.get("watermark", {})

    left_text   = str(ftr.get("left_text",   "ISO 13485 Audit Report — Confidential") or "")
    center_text = str(ftr.get("center_text", "") or "")
    right_tmpl  = str(ftr.get("right_text",  "Page {page}") or "")

    wm_enabled  = bool(wm.get("enabled", False))
    wm_text     = str(wm.get("text",  "CONFIDENTIAL") or "CONFIDENTIAL")
    wm_opacity  = float(wm.get("opacity", 0.08))
    wm_angle    = float(wm.get("angle",   45))
    wm_size     = int(wm.get("font_size", 72))
    wm_hex      = str(wm.get("color", "#cccccc") or "#cccccc")

    def _on_page(canvas_obj, doc):
        w, h = A4
        canvas_obj.saveState()

        # ── watermark ──────────────────────────────────────────────────────
        if wm_enabled and wm_text:
            canvas_obj.saveState()
            try:
                wm_color = colors.HexColor(wm_hex)
            except Exception:
                wm_color = colors.HexColor("#cccccc")
            canvas_obj.setFillColor(wm_color)
            canvas_obj.setFont("Helvetica-Bold", wm_size)
            canvas_obj.setFillAlpha(wm_opacity)
            canvas_obj.translate(w / 2, h / 2)
            canvas_obj.rotate(wm_angle)
            canvas_obj.drawCentredString(0, 0, wm_text)
            canvas_obj.restoreState()

        # ── footer ─────────────────────────────────────────────────────────
        right_text = right_tmpl.replace("{page}", str(doc.page))
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(colors.HexColor("#94a3b8"))
        canvas_obj.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        if left_text:
            canvas_obj.drawString(18 * mm, 10 * mm, left_text)
        if center_text:
            canvas_obj.drawCentredString(w / 2, 10 * mm, center_text)
        if right_text:
            canvas_obj.drawRightString(w - 18 * mm, 10 * mm, right_text)

        canvas_obj.restoreState()

    return _on_page


# ─────────────────────────────────────────────
# Table builders
# ─────────────────────────────────────────────
HEADER_BG   = colors.HexColor("#1e293b")
ALT_ROW_BG  = colors.HexColor("#f8fafc")
GRID_COLOR  = colors.HexColor("#e2e8f0")
NC_ROW_BG   = colors.HexColor("#fff1f2")
NC_HDR_BG   = colors.HexColor("#991b1b")


def _checklist_table(rows: List[Dict], styles: Dict, page_w: float) -> Optional[Table]:
    """
    Build one table for a checklist section.
    Columns: Sr No | Question | Observation | Evidence | Write Your Observation | Clause No.
    """
    usable = page_w - 36 * mm

    # Column widths (total = usable)
    col_w = [
        10 * mm,        # Sr No
        usable * 0.30,  # Question
        16 * mm,        # Observation
        usable * 0.20,  # Evidence
        usable * 0.26,  # Write Your Observation
        18 * mm,        # Clause No.
    ]

    hdr = styles["cell_hdr"]
    cell = styles["cell"]

    header_row = [
        Paragraph("Sr No", hdr),
        Paragraph("Question", hdr),
        Paragraph("Observation", hdr),
        Paragraph("Evidence", hdr),
        Paragraph("Write Your Observation", hdr),
        Paragraph("Clause No.", hdr),
    ]
    table_data = [header_row]

    row_styles: List[Tuple] = []
    data_row_idx = 1

    for r in rows:
        if not isinstance(r, dict):
            continue
        # skip sub-questions that were never shown (no observation)
        obs_val = _safe_text(r.get("observation", ""))
        if not obs_val:
            continue

        sr  = _safe_text(r.get("sr_no")) or "-"
        chk = _safe_text(r.get("checklist")) or "-"
        obs = obs_val or "-"
        evd = _safe_text(r.get("evidence")) or "-"
        fob = _safe_text(r.get("full_observation")) or "-"
        cln = _safe_text(r.get("clause_no")) or "-"

        is_nc = _is_non_conformity(r)
        c = styles["nc_cell"] if is_nc else cell

        table_data.append([
            Paragraph(sr, c),
            Paragraph(chk, c),
            Paragraph(obs, c),
            Paragraph(evd, c),
            Paragraph(fob, c),
            Paragraph(cln, c),
        ])

        if is_nc:
            row_styles.append(("BACKGROUND", (0, data_row_idx), (-1, data_row_idx), NC_ROW_BG))

        # Alternate row shading for non-NC rows
        elif data_row_idx % 2 == 0:
            row_styles.append(("BACKGROUND", (0, data_row_idx), (-1, data_row_idx), ALT_ROW_BG))

        data_row_idx += 1

    if len(table_data) == 1:
        return None  # no filled rows

    base_style = TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GRID_COLOR),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
    ])
    for cmd in row_styles:
        base_style.add(*cmd)

    return Table(table_data, colWidths=col_w, style=base_style, repeatRows=1, splitByRow=True)


def _nc_summary_table(nc_rows: List[Dict], styles: Dict, page_w: float) -> Optional[Table]:
    """
    Build the non-conformity summary table.
    Columns: Sr No | Section | Question | Observation | Evidence | Write Your Observation
    """
    if not nc_rows:
        return None

    usable = page_w - 36 * mm
    col_w = [
        10 * mm,
        usable * 0.14,  # Section
        usable * 0.28,  # Question
        14 * mm,        # Observation
        usable * 0.22,  # Evidence
        usable * 0.22,  # Write Your Observation
    ]

    hdr = styles["cell_hdr"]
    nc_cell = styles["nc_cell"]

    header_row = [
        Paragraph("Sr No", hdr),
        Paragraph("Section", hdr),
        Paragraph("Question", hdr),
        Paragraph("Observation", hdr),
        Paragraph("Evidence", hdr),
        Paragraph("Write Your Observation", hdr),
    ]
    table_data = [header_row]

    for r in nc_rows:
        sr  = _safe_text(r.get("sr_no")) or "-"
        sec = _safe_text(r.get("_section")) or "-"
        chk = _safe_text(r.get("checklist")) or "-"
        obs = _safe_text(r.get("observation")) or "-"
        evd = _safe_text(r.get("evidence")) or "-"
        fob = _safe_text(r.get("full_observation")) or "-"
        table_data.append([
            Paragraph(sr, nc_cell),
            Paragraph(sec, nc_cell),
            Paragraph(chk, nc_cell),
            Paragraph(obs, nc_cell),
            Paragraph(evd, nc_cell),
            Paragraph(fob, nc_cell),
        ])

    style = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NC_HDR_BG),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [NC_ROW_BG, colors.HexColor("#ffe4e6")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#fecaca")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
    ])
    return Table(table_data, colWidths=col_w, style=style, repeatRows=1, splitByRow=True)


# ─────────────────────────────────────────────
# Core: Generate PDF
# ─────────────────────────────────────────────
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
    Returns: (ok, message, saved_pdf_abs_path_or_None)
    """
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return False, "Tenant not found in session. Please logout and login again.", None

    ids = [str(x or "").strip() for x in (selected_audit_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return False, "No audits selected.", None

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
        return False, "Selected audits were not found.", None

    def _sort_key(a: Dict):
        return (
            get_audit_display_date(a),
            _audit_display_title(a).lower(),
            _audit_display_dept(a).lower(),
            _audit_display_auditor(a).lower(),
        )
    audits.sort(key=_sort_key)

    if not output_filename:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = f"Final_Audit_Report_{stamp}.pdf"
    if not output_filename.lower().endswith(".pdf"):
        output_filename += ".pdf"

    reports_dir = _tenant_generated_reports_dir(tenant_id)
    _ensure_dir(reports_dir)
    pdf_abs_path = os.path.join(reports_dir, output_filename)

    # ── Load report settings ─────────────────────────────────────────────────
    report_settings = engine.get_report_settings(tenant_id=tenant_id)
    hdr_cfg = report_settings.get("header", {})
    company_name  = str(hdr_cfg.get("company_name",  "") or "").strip()
    report_title  = str(hdr_cfg.get("report_title",  "ISO 13485 Audit Report") or "ISO 13485 Audit Report").strip()
    tagline       = str(hdr_cfg.get("tagline",        "") or "").strip()
    show_divider  = bool(hdr_cfg.get("show_divider",  True))

    on_page_cb = _make_on_page(report_settings)

    # ── Build Platypus story ─────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        pdf_abs_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        title=report_title,
        author=generated_by,
    )
    page_w, _ = A4
    styles = _build_styles()
    story = []

    def P(text, style_key="body"):
        return Paragraph(_safe_text(text) or "-", styles[style_key])

    def HR(color=GRID_COLOR, thickness=0.5):
        return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=4)

    def gap(h=4):
        return Spacer(1, h * mm)

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(gap(8))

    # Company name / report title header block
    if company_name:
        story.append(Paragraph(company_name, ParagraphStyle(
            "CoverCompany", parent=styles["body"],
            fontSize=11, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#6366f1"),
            spaceAfter=2, alignment=TA_CENTER,
        )))
    story.append(Paragraph(report_title, ParagraphStyle(
        "CoverTitle", parent=styles["title"],
        fontSize=22, alignment=TA_CENTER, spaceAfter=2,
    )))
    if tagline:
        story.append(Paragraph(tagline, ParagraphStyle(
            "CoverTagline", parent=styles["body"],
            fontSize=10, textColor=colors.HexColor("#64748b"),
            spaceAfter=2, alignment=TA_CENTER,
        )))
    if show_divider:
        story.append(HR(color=colors.HexColor("#6366f1"), thickness=1.5))
    else:
        story.append(HR())

    story.append(gap(2))
    story.append(P(f"Generated at: {_now_iso()}"))
    story.append(P(f"Generated by: {_safe_text(generated_by)}"))
    story.append(gap(4))

    if missing_ids:
        story.append(P("Warning — some selected audits were not found and were skipped:"))
        for mid in missing_ids:
            story.append(P(f"  • {mid}"))
        story.append(gap(2))

    story.append(P(f"Included audits: {len(audits)}", "h2"))
    story.append(gap(2))

    # Summary list on cover
    cov_data = [
        [
            Paragraph("#", styles["cell_hdr"]),
            Paragraph("Title", styles["cell_hdr"]),
            Paragraph("Department", styles["cell_hdr"]),
            Paragraph("Auditor", styles["cell_hdr"]),
            Paragraph("Date", styles["cell_hdr"]),
            Paragraph("Status", styles["cell_hdr"]),
        ]
    ]
    for idx, a in enumerate(audits, 1):
        cov_data.append([
            Paragraph(str(idx), styles["cell"]),
            Paragraph(_audit_display_title(a), styles["cell"]),
            Paragraph(_audit_display_dept(a), styles["cell"]),
            Paragraph(_audit_display_auditor(a), styles["cell"]),
            Paragraph(get_audit_display_date(a), styles["cell"]),
            Paragraph(_safe_text(a.get("status")) or "-", styles["cell"]),
        ])

    usable = page_w - 36 * mm
    cov_table = Table(
        cov_data,
        colWidths=[8*mm, usable*0.27, usable*0.17, usable*0.20, usable*0.18, usable*0.14],
        style=TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), HEADER_BG),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
            ("GRID",          (0, 0), (-1, -1), 0.4, GRID_COLOR),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ]),
        repeatRows=1,
        splitByRow=True,
    )
    story.append(cov_table)
    story.append(PageBreak())

    # ── Detail pages: one per audit ───────────────────────────────────────────
    for idx, a in enumerate(audits, 1):
        selected_id = _safe_text(a.get("_selected_id"))
        audit_key   = _audit_primary_key(a) or selected_id
        title       = _audit_display_title(a)
        auditor     = _audit_display_auditor(a)
        dept        = _audit_display_dept(a)
        date_str    = get_audit_display_date(a)
        status      = _safe_text(a.get("status")) or "-"

        # ── Audit header ──────────────────────────────────────────────────────
        hdr_block = [
            P(f"Audit {idx}: {title}", "h1"),
            HR(),
            P(f"Audit ID: {audit_key}"),
            P(f"Status: {status}"),
            P(f"Auditor: {auditor}"),
            P(f"Department: {dept}"),
            P(f"Date: {date_str}"),
            gap(3),
        ]
        story.extend(hdr_block)

        # ── Admin summary ─────────────────────────────────────────────────────
        summary = _safe_text((admin_summaries_by_audit_id or {}).get(selected_id, "")).strip()
        story.append(P("Summary (Admin)", "h2"))
        story.append(P(summary or "(No summary provided.)"))
        story.append(gap(4))

        # ── Checklist tables ──────────────────────────────────────────────────
        story.append(P("Audit Checklist", "h2"))
        story.append(HR())

        checklists = a.get("checklists", {})
        dept_key = str(dept or "").strip().lower()
        # Try exact key first, then normalized
        dept_block = {}
        if isinstance(checklists, dict):
            dept_block = (
                checklists.get(dept)
                or checklists.get(dept_key)
                or {}
            )

        all_nc_rows: List[Dict] = []  # collect NCs across all sections

        if not isinstance(dept_block, dict) or not dept_block:
            story.append(P("(Checklist not filled for this audit.)"))
        else:
            for section_name, rows in dept_block.items():
                if not isinstance(rows, list):
                    continue

                story.append(gap(2))
                story.append(P(f"Section: {_safe_text(section_name)}", "h3"))

                tbl = _checklist_table(rows, styles, page_w)
                if tbl:
                    story.append(tbl)
                else:
                    story.append(P("(No answers recorded for this section.)"))

                # Collect NCs for this section
                for r in rows:
                    if isinstance(r, dict) and _is_non_conformity(r):
                        rc = dict(r)
                        rc["_section"] = _safe_text(section_name)
                        all_nc_rows.append(rc)

                story.append(gap(2))

        # ── Non-Conformity Summary table ──────────────────────────────────────
        story.append(gap(4))
        story.append(P("Non-Conformity Summary", "h2"))
        story.append(HR())

        if all_nc_rows:
            nc_tbl = _nc_summary_table(all_nc_rows, styles, page_w)
            if nc_tbl:
                story.append(nc_tbl)
        else:
            story.append(P("No non-conformities recorded for this audit."))

        story.append(gap(4))

        # ── Submitted files ───────────────────────────────────────────────────
        story.append(P("Submitted Files", "h2"))
        story.append(HR())
        reports = a.get("reports", [])
        if not isinstance(reports, list) or not reports:
            story.append(P("(No files uploaded.)"))
        else:
            for rr in reports:
                if not isinstance(rr, dict):
                    continue
                fname       = _safe_text(rr.get("file_name")) or "-"
                uploaded_at = _safe_text(rr.get("uploaded_at")) or "-"
                uploaded_by = _safe_text(rr.get("uploaded_by")) or "-"
                story.append(P(f"• {fname}  |  Uploaded by: {uploaded_by}  |  Date: {uploaded_at}"))

        story.append(gap(6))
        story.append(HR())

        # Page break between audits (not after the last one)
        if idx < len(audits):
            story.append(PageBreak())

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=on_page_cb, onLaterPages=on_page_cb)

    # ── Register in engine ────────────────────────────────────────────────────
    pdf_rel_path = os.path.join("generated_reports", output_filename).replace("\\", "/")
    audit_ids_for_engine = list(dict.fromkeys(
        _audit_primary_key(a) for a in audits if _audit_primary_key(a)
    ))

    summary_lines = [
        f"Final report generated by {generated_by} at {_now_iso()}.",
        f"Included audits: {len(audits)}.",
        "Audit list:",
    ]
    for i, a in enumerate(audits, 1):
        summary_lines.append(
            f"{i}. {_audit_display_title(a)} | {_audit_display_dept(a)}"
            f" | Auditor: {_audit_display_auditor(a)}"
            f" | Status: {_safe_text(a.get('status')) or '-'}"
            f" | ID: {_safe_text(a.get('_selected_id'))}"
        )
    consolidated_summary = "\n".join(summary_lines)

    ok, msg = _engine_register_final_report(
        tenant_id=tenant_id,
        created_by=_safe_text(generated_by),
        pdf_rel_path=pdf_rel_path,
        audit_ids=audit_ids_for_engine,
        summary=consolidated_summary,
        allowed_users=None,
    )

    if not ok:
        return False, f"PDF created but could not be registered: {msg}", pdf_abs_path

    return True, f"Report generated: {output_filename}", pdf_abs_path
