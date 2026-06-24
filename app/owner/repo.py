"""
Owner Mode storage access (AdminSettings tab for now).

All reads are defensive: if the AdminSettings tab doesn't exist yet (e.g. before
setup_sheet has been run), every getter returns a safe default instead of
raising — so routing and the scheduler can never crash on a missing tab.
"""
from __future__ import annotations

import logging
import uuid

from app import clock
from app.owner import constants as oc
from app.sheets import client, schema

log = logging.getLogger(__name__)

KEY_OWNER_GROUP = "owner_group_chat_id"


def _gen(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return clock.iso(clock.now())


def _settings():
    return client.table(schema.ADMIN_SETTINGS)


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        row = _settings().find("Setting Key", key)
        if row and str(row.get("Setting Value")) != "":
            return str(row.get("Setting Value"))
    except Exception as e:  # tab missing / sheet unreachable -> safe default
        log.debug("owner get_setting(%s) fell back to default: %s", key, e)
    return default


def set_setting(key: str, value: str, description: str = "") -> None:
    t = _settings()
    now = clock.iso(clock.now())
    if t.find("Setting Key", key):
        t.update("Setting Key", key, {"Setting Value": value, "Updated At": now})
    else:
        t.append({"Setting Key": key, "Setting Value": value,
                  "Description": description, "Updated At": now})


def get_owner_group_id() -> int | None:
    v = get_setting(KEY_OWNER_GROUP)
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


def set_owner_group_id(chat_id) -> None:
    set_setting(KEY_OWNER_GROUP, str(chat_id), "Registered Owner Mode group chat")


def clear_owner_group_id() -> None:
    set_setting(KEY_OWNER_GROUP, "", "Owner Mode group unregistered")


def setting_or_default(key: str) -> str:
    return get_setting(key, oc.DEFAULTS.get(key, "")) or oc.DEFAULTS.get(key, "")


# --------------------------------------------------------------- AdminTasks
def _tasks():
    return client.table(schema.ADMIN_TASKS)


def add_task(
    title: str,
    *,
    due_date: str = "",
    due_time: str = "",
    category: str = oc.CAT_GENERAL,
    note: str = "",
    responsible: str = "",
    status: str = oc.ST_OPEN,
    source_message_id: str = "",
    recurrence_id: str = "",
) -> dict:
    row = {
        "Task ID": _gen("OT"),
        "Title": title,
        "Note": note,
        "Category": category,
        "Status": status,
        "Responsible": responsible,
        "Due Date": due_date,
        "Due Time": due_time,
        "Original Due Date": due_date,
        "Recurrence ID": recurrence_id,
        "Workflow": "",
        "Created At": _now(),
        "Completed At": "",
        "Next Reminder At": "",
        "Source Message ID": str(source_message_id or ""),
        "Updated At": _now(),
    }
    _tasks().append(row)
    return row


def get_task(task_id: str) -> dict | None:
    return _tasks().find("Task ID", task_id)


def update_task(task_id: str, changes: dict) -> bool:
    return _tasks().update("Task ID", task_id, {**changes, "Updated At": _now()})


def all_tasks() -> list[dict]:
    return _tasks().all()


def active_tasks() -> list[dict]:
    """Open + Waiting (not completed/skipped)."""
    return [t for t in all_tasks()
            if str(t.get("Status")) in (oc.ST_OPEN, oc.ST_WAITING)]


# ----------------------------------------------------------- AdminHistory
def _history():
    return client.table(schema.ADMIN_HISTORY)


def open_occurrences(recurrence_id: str) -> list[dict]:
    return [t for t in all_tasks()
            if str(t.get("Recurrence ID")) == str(recurrence_id)
            and str(t.get("Status")) in (oc.ST_OPEN, oc.ST_WAITING)]


# ----------------------------------------------------------- AdminRecurring
def _recurring():
    return client.table(schema.ADMIN_RECURRING)


def add_recurring(title: str, category: str, rule: str, *, time: str = "",
                  lead_days: str = "", responsible: str = "") -> str:
    rid = _gen("OR")
    _recurring().append({
        "Recurrence ID": rid, "Title": title, "Category": category,
        "Responsible": responsible, "Rule": rule, "Days Of Week": "",
        "Day Of Month": "", "Time": time, "Lead Days": lead_days,
        "Active": "TRUE", "Last Generated": "", "Notes": "",
        "Created At": _now(), "Updated At": _now(),
    })
    return rid


def get_recurring(rid: str) -> dict | None:
    return _recurring().find("Recurrence ID", rid)


def active_recurring() -> list[dict]:
    from app.repositories.base import as_bool
    return [r for r in _recurring().all() if as_bool(r.get("Active"))]


def update_recurring(rid: str, changes: dict) -> bool:
    return _recurring().update("Recurrence ID", rid, {**changes, "Updated At": _now()})


def log_history(task_id: str, action: str, detail: str = "") -> None:
    try:
        _history().append({
            "History ID": _gen("OH"), "Timestamp": _now(),
            "Task ID": task_id, "Action": action, "Detail": detail,
        })
    except Exception:
        pass  # history is best-effort, never block an action
