"""
Task + Task Item repository (spec sections 17, 35 & 'Tasks'/'Task Items' tabs).

A Task is one checkpoint for one date assigned to one staff member. Task Items
are the frozen snapshot of the checklist template at generation time.
"""
from __future__ import annotations

from datetime import date, datetime

from app import constants
from app.repositories.base import as_bool, gen_id, now_iso
from app.sheets import client, schema


def _tasks():
    return client.table(schema.TASKS)


def _items():
    return client.table(schema.TASK_ITEMS)


def task_key(d: date, checklist_type: str) -> str:
    """Idempotency key: one task per date+checkpoint (spec section 42)."""
    return f"{d.isoformat()}::{checklist_type}"


def get(task_id: str) -> dict | None:
    return _tasks().find("Task ID", task_id)


def get_by_key(d: date, checklist_type: str) -> dict | None:
    return _tasks().find("Task Key", task_key(d, checklist_type))


def get_by_token_hash(token_hash: str) -> dict | None:
    return _tasks().find("Task Token Hash", token_hash)


def for_date(d: date) -> list[dict]:
    return _tasks().find_all("Date", d.isoformat())


def all_unresolved() -> list[dict]:
    """Tasks not in a terminal state, for the scheduler to consider."""
    terminal = {constants.RES_RECOVERED_OIC, constants.RES_RESOLVED_ADMIN,
                constants.RES_CLOSED_NO_RECOVERY}
    out = []
    for t in _tasks().all():
        if t.get("Original Submission Status") == constants.SUB_CLOSED:
            continue
        if t.get("Resolution Status") in terminal:
            continue
        out.append(t)
    return out


def create_task(
    d: date,
    checklist_type: str,
    *,
    token_hash: str,
    staff: dict,
    release_at: datetime,
    cutoff_at: datetime,
    group_chat_id: int,
) -> dict:
    row = {
        "Task ID": gen_id("TASK"),
        "Task Key": task_key(d, checklist_type),
        "Task Token Hash": token_hash,
        "Date": d.isoformat(),
        "Checklist Type": checklist_type,
        "Assigned Staff ID": staff.get("Staff ID", ""),
        "Assigned Staff Name": staff.get("Staff Name", ""),
        "Assigned Telegram User ID": str(staff.get("Telegram User ID", "")),
        "Release At": release_at.isoformat(),
        "Cutoff At": cutoff_at.isoformat(),
        "Initial Message ID": "",
        "Staff Group Chat ID": str(group_chat_id),
        "OIC Alert Message ID": "",
        "Daily Summary Message ID": "",
        "Started At": "",
        "Submitted At": "",
        "Original Submission Status": constants.SUB_PENDING,
        "Checklist Result": "",
        "Evidence Status": "",
        "Resolution Status": constants.RES_NONE,
        "Not Submitted At": "",
        "Review Required": False,
        "Recovered By Staff ID": "",
        "Recovered By Telegram User ID": "",
        "Recovered At": "",
        "Current Version": 1,
        "Created At": now_iso(),
        "Updated At": now_iso(),
    }
    return _tasks().append(row)


def create_closed_task(d: date, checklist_type: str) -> dict:
    """Placeholder record so a closed day still appears in summaries."""
    row = {
        "Task ID": gen_id("TASK"),
        "Task Key": task_key(d, checklist_type),
        "Task Token Hash": "",
        "Date": d.isoformat(),
        "Checklist Type": checklist_type,
        "Original Submission Status": constants.SUB_CLOSED,
        "Resolution Status": constants.RES_NONE,
        "Created At": now_iso(),
        "Updated At": now_iso(),
        "Current Version": 1,
    }
    return _tasks().append(row)


def update(task_id: str, changes: dict) -> bool:
    changes = {**changes, "Updated At": now_iso()}
    return _tasks().update("Task ID", task_id, changes)


# ---------------------------------------------------------------- Task Items
def add_items(task_id: str, template_items: list[dict]) -> list[dict]:
    rows = []
    for tmpl in template_items:
        rows.append({
            "Task Item ID": gen_id("TI"),
            "Task ID": task_id,
            "Template Item ID": tmpl.get("Item ID", ""),
            "Item Name": tmpl.get("Item Name", ""),
            "Instructions": tmpl.get("Instructions", ""),
            "Item Type": tmpl.get("Item Type", ""),
            "Required": as_bool(tmpl.get("Required", True)),
            "Sort Order": tmpl.get("Sort Order", 0),
            "Response": "",
            "Issue Reported": False,
            "Issue Details": "",
            "Completed": False,
            "Completed At": "",
            "Missing At Cutoff": False,
            "Recovered": False,
            "Recovered At": "",
        })
    _items().append_many(rows)
    return rows


def items_for(task_id: str) -> list[dict]:
    rows = _items().find_all("Task ID", task_id)
    return sorted(rows, key=lambda r: int(r.get("Sort Order") or 0))


def get_item(task_item_id: str) -> dict | None:
    return _items().find("Task Item ID", task_item_id)


def update_item(task_item_id: str, changes: dict) -> bool:
    return _items().update("Task Item ID", task_item_id, changes)


def update_items(changes_by_id: dict[str, dict]) -> int:
    """Update many task items in a single Sheets call (used on submit)."""
    return _items().update_many("Task Item ID", changes_by_id)
