"""Shift reminders — configurable recurring nudges (no photo, no submission).

Each reminder is one row. Its time slots are encoded in the "Slots" cell as
"HH:MM=role;HH:MM=role" (role ∈ opener/closer/both/peak/group) so a single
reminder can tag different on-shift people at different times. "Days" is a
comma list of weekdays (empty = every day).
"""
from __future__ import annotations

import logging

from app import clock
from app.repositories.base import as_bool, gen_id
from app.sheets import client, schema

log = logging.getLogger(__name__)

ROLES = ("opener", "closer", "both", "peak", "group")


def _now() -> str:
    return clock.iso(clock.now())


def _t():
    return client.table(schema.SHIFT_REMINDERS)


def all_rows() -> list[dict]:
    try:
        return _t().all()
    except Exception as e:
        log.debug("shift reminders read failed (tab missing?): %s", e)
        return []


def active_rows() -> list[dict]:
    return [r for r in all_rows() if as_bool(r.get("Active"))]


def get(reminder_id: str) -> dict | None:
    try:
        return _t().find("Reminder ID", reminder_id)
    except Exception:
        return None


def add(*, title: str, message: str, days: str, slots: str,
        active: bool = True, created_by: str = "") -> dict:
    row = {
        "Reminder ID": gen_id("REM"),
        "Title": title, "Message": message,
        "Days": days, "Slots": slots,
        "Active": active, "Created By": str(created_by or ""),
        "Created At": _now(), "Updated At": _now(),
    }
    _t().append(row)
    return row


def update(reminder_id: str, changes: dict) -> bool:
    return _t().update("Reminder ID", reminder_id, {**changes, "Updated At": _now()})


def delete(reminder_id: str) -> bool:
    # Soft-delete: just deactivate (keeps history + is simplest/safest).
    return update(reminder_id, {"Active": False})


# ---------------------------------------------------------- encode / decode
def parse_slots(slots: str) -> list[dict]:
    """"15:00=opener;17:00=closer" -> [{'time':'15:00','role':'opener'}, …]."""
    out = []
    for part in str(slots or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            t, role = part.split("=", 1)
        else:
            t, role = part, "both"
        t, role = t.strip(), role.strip().lower()
        if role not in ROLES:
            role = "both"
        if t:
            out.append({"time": t, "role": role})
    return out


def encode_slots(slots: list[dict]) -> str:
    return ";".join(f"{s['time']}={s.get('role', 'both')}" for s in slots if s.get("time"))


def parse_days(days: str) -> list[str]:
    return [d.strip().upper() for d in str(days or "").split(",") if d.strip()]
