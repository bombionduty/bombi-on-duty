"""Weekly accountability checklists (Feature 3).

Two layers:
  * Weekly Tasks      — the permanent library (e.g. "General Cleaning", Sat 23:00).
                        Each entry is a single photo-proof item with its own doer
                        default + reminder/cutoff times.
  * Weekly Instances  — one row per week's occurrence of a task, carrying the
                        two-step doer→checker photo state.

Defensive reads: if a tab doesn't exist yet, getters return empty instead of
raising (the auto-header-sync creates the tabs on first write).
"""
from __future__ import annotations

import logging

from app import clock
from app.repositories.base import gen_id
from app.sheets import client, schema

log = logging.getLogger(__name__)

# Instance status values.
ST_PENDING = "Pending"       # posted / awaiting the doer's completion photo
ST_DOER_DONE = "Doer Done"   # doer photo in — awaiting a different staffer to verify
ST_VERIFIED = "Verified"     # checker photo in — fully accountable + done
ST_MISSING = "Missing"       # cutoff passed without full verification

OPEN_STATES = {ST_PENDING, ST_DOER_DONE}


def _now() -> str:
    return clock.iso(clock.now())


# ------------------------------------------------------------- definitions
def _defs():
    return client.table(schema.WEEKLY_TASKS)


def all_defs() -> list[dict]:
    try:
        return _defs().all()
    except Exception as e:
        log.debug("weekly defs read failed (tab missing?): %s", e)
        return []


def active_defs() -> list[dict]:
    from app.repositories.base import as_bool
    return [d for d in all_defs() if as_bool(d.get("Active"))]


def get_def(weekly_id: str) -> dict | None:
    try:
        return _defs().find("Weekly ID", weekly_id)
    except Exception:
        return None


def add_def(*, title: str, instructions: str, weekday: str, time: str,
            reminder_times: str, cutoff_time: str,
            default_doer: dict | None = None, requires_verification: bool = False,
            created_by: str = "") -> dict:
    row = {
        "Weekly ID": gen_id("WK"),
        "Title": title,
        "Instructions": instructions,
        "Weekday": weekday.upper(),
        "Time": time,
        "Reminder Times": reminder_times,
        "Cutoff Time": cutoff_time,
        "Default Doer Staff ID": str((default_doer or {}).get("Staff ID", "")),
        "Default Doer Name": str((default_doer or {}).get("Staff Name", "")),
        "Requires Verification": bool(requires_verification),
        "Active": True,
        "Created By": str(created_by or ""),
        "Created At": _now(),
        "Updated At": _now(),
    }
    _defs().append(row)
    return row


def update_def(weekly_id: str, changes: dict) -> bool:
    return _defs().update("Weekly ID", weekly_id, {**changes, "Updated At": _now()})


# --------------------------------------------------------------- instances
def _inst():
    return client.table(schema.WEEKLY_INSTANCES)


def all_instances() -> list[dict]:
    try:
        return _inst().all()
    except Exception as e:
        log.debug("weekly instances read failed (tab missing?): %s", e)
        return []


def get_instance(instance_id: str) -> dict | None:
    try:
        return _inst().find("Instance ID", instance_id)
    except Exception:
        return None


def instance_for(weekly_id: str, date_iso: str) -> dict | None:
    for r in all_instances():
        if str(r.get("Weekly ID")) == str(weekly_id) and str(r.get("Date")) == date_iso:
            return r
    return None


def instances_for_date(date_iso: str) -> list[dict]:
    return [r for r in all_instances() if str(r.get("Date")) == date_iso]


def open_instances() -> list[dict]:
    return [r for r in all_instances() if str(r.get("Status")) in OPEN_STATES]


def add_instance(*, weekly_id: str, title: str, date_iso: str, weekday: str,
                 doer: dict | None, time: str, cutoff_at: str,
                 requires_verification: bool = False) -> dict:
    row = {
        "Instance ID": gen_id("WKI"),
        "Weekly ID": weekly_id,
        "Title": title,
        "Date": date_iso,
        "Weekday": weekday.upper(),
        "Requires Verification": bool(requires_verification),
        "Doer Staff ID": str((doer or {}).get("Staff ID", "")),
        "Doer Name": str((doer or {}).get("Staff Name", "")),
        "Doer Telegram User ID": str((doer or {}).get("Telegram User ID", "")),
        "Status": ST_PENDING,
        "Doer Photo File ID": "",
        "Doer Submitted At": "",
        "Checker Staff ID": "",
        "Checker Name": "",
        "Checker Telegram User ID": "",
        "Checker Photo File ID": "",
        "Checker Verified At": "",
        "Group Message ID": "",
        "Time": time,
        "Cutoff At": cutoff_at,
        "Missing At Cutoff": False,
        "Created At": _now(),
        "Updated At": _now(),
    }
    _inst().append(row)
    return row


def update_instance(instance_id: str, changes: dict) -> bool:
    return _inst().update("Instance ID", instance_id, {**changes, "Updated At": _now()})
