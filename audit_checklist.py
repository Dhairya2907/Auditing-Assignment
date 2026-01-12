# audit_checklist.py
from __future__ import annotations
from typing import Dict, List

# Master checklist library (you can expand anytime)
DEPARTMENT_CHECKLISTS: Dict[str, List[str]] = {
    "HR": [
        "Competency and training requirements defined",
        "Training records are complete and current",
        "Training effectiveness is evaluated",
        "Regulatory/quality awareness maintained for roles",
        "Personnel files and role descriptions controlled",
    ],
    "Purchase": [
        "Supplier selection and evaluation criteria defined",
        "Approved supplier list maintained and current",
        "Supplier agreements include quality clauses",
        "Incoming inspection linkage with purchasing verified",
        "Supplier performance monitoring and re-evaluation",
    ],
    "Sales and Marketing": [
        "Marketing material approval and control process exists",
        "Claims are consistent with intended use and approvals",
        "Customer feedback captured and communicated to QA",
        "Complaint handling linkage from marketing/customer touchpoints",
        "Promotional content version control and distribution control",
    ],
}

def get_department_checklist(department: str) -> List[str]:
    return DEPARTMENT_CHECKLISTS.get(department, [])

def build_audit_table(department: str) -> List[dict]:
    """
    Builds the table rows to store inside audits.json under one audit record.
    """
    items = get_department_checklist(department)
    rows = []
    for i, item in enumerate(items, start=1):
        rows.append({
            "sr_no": i,
            "checklist": item,
            "observation": "",
            "evidence": "",
        })
    return rows
