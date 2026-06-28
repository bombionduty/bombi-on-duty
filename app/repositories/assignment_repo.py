"""Staff Assignments repository — ad-hoc tasks the admin assigns to staff
(separate from the Opening/Closing checklists). Defensive reads: if the tab
doesn't exist yet (setup_sheet not run), getters return empty instead of raising.
"""
from __future__ import annotations

import logging

from app import clock
from app.repositories.base import gen_id
from app.sheets import client, schema

log = logging.getLogger(__name__)

ST_OPEN = "Open"
ST_DONE = "Done"
ST_CANCELLED = "Cancelled"


def _t():
    return client.table(schema.STAFF_ASSIGNMENTS)


def _now() -> str:
    return clock.iso(clock.now())


def add(*, title: str, staff: dict, due_date: str = "", due_time: str = "",
        recurrence_rule: str = "", series_id: str = "", created_by: str = "") -> dict:
    row = {
        "Assignment ID": gen_id("ASG"),
        "Series ID": series_id or gen_id("ASS"),
        "Title": title,
        "Assigned Staff ID": str(staff.get("Staff ID", "")),
        "Assigned Staff Name": str(staff.get("Staff Name", "")),
        "Assigned Telegram User ID": str(staff.get("Telegram User ID", "")),
        "Due Date": due_date,
        "Due Time": due_time,
        "Status": ST_OPEN,
        "Recurrence Rule": recurrence_rule,
        "Group Message ID": "",
        "Created By": str(created_by or ""),
        "Created At": _now(),
        "Completed At": "",
        "Updated At": _now(),
    }
    _t().append(row)
    return row


def get(assignment_id: str) -> dict | None:
    try:
        return _t().find("Assignment ID", assignment_id)
    except Exception as e:
        log.debug("assignment get failed: %s", e)
        return None


def all_rows() -> list[dict]:
    try:
        return _t().all()
    except Exception as e:
        log.debug("assignment all failed (tab missing?): %s", e)
        return []


def open_rows() -> list[dict]:
    return [a for a in all_rows() if str(a.get("Status")) == ST_OPEN]


def open_in_series(series_id: str) -> list[dict]:
    return [a for a in open_rows() if str(a.get("Series ID")) == str(series_id)]


def update(assignment_id: str, changes: dict) -> bool:
    return _t().update("Assignment ID", assignment_id, {**changes, "Updated At": _now()})
