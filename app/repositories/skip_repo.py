"""Per-date manual on/off for Feed notifications.

The admin can toggle any single notification OFF for one day from the Feed tab
(e.g. skip a reminder today). A row exists per (date, kind, ref); its `Skipped`
flag is the switch. Toggling back ON flips the flag — rows are never deleted, so
we never need a sheet row-delete.

Scope is one calendar day only: nothing here recurs to other dates.
"""
from __future__ import annotations

from datetime import date

from app.repositories.base import as_bool, now_iso
from app.sheets import client, schema


def _t():
    return client.table(schema.NOTIFICATION_SKIPS)


def _key(d: date, kind: str, ref: str) -> str:
    return f"{d.isoformat()}|{kind}|{ref}"


def is_skipped(d: date, kind: str, ref: str) -> bool:
    """True when the admin has turned this notification OFF for date `d`.
    Any read error defaults to NOT skipped — a transient failure must never
    silently suppress a notification."""
    try:
        row = _t().find("Key", _key(d, kind, ref))
        return bool(row) and as_bool(row.get("Skipped"))
    except Exception:
        return False


def set_skip(d: date, kind: str, ref: str, skipped: bool, by: str = "") -> None:
    key = _key(d, kind, ref)
    changes = {"Skipped": bool(skipped), "Updated At": now_iso(), "Updated By": by}
    t = _t()
    if t.find("Key", key):
        t.update("Key", key, changes)
    else:
        t.append({"Key": key, "Date": d.isoformat(), "Kind": kind, "Ref": ref,
                  **changes})
