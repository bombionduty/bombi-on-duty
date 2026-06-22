"""Checklist template repository (spec sections 32-35 & 'Checklist Templates' tab)."""
from __future__ import annotations

from datetime import date

from app import clock, constants
from app.repositories.base import as_bool, gen_id, now_iso
from app.sheets import client, schema


def _t():
    return client.table(schema.CHECKLIST_TEMPLATES)


def all_items(checklist_type: str | None = None) -> list[dict]:
    rows = _t().all()
    if checklist_type:
        rows = [r for r in rows if r.get("Checklist Type") == checklist_type]
    return sorted(rows, key=lambda r: _sort_key(r))


def _sort_key(r: dict):
    try:
        return (str(r.get("Checklist Type")), int(r.get("Sort Order") or 0))
    except (TypeError, ValueError):
        return (str(r.get("Checklist Type")), 0)


def get(item_id: str) -> dict | None:
    return _t().find("Item ID", item_id)


def _weekday_ok(days_of_week: str, d: date) -> bool:
    days = [x.strip().upper() for x in str(days_of_week).split(",") if x.strip()]
    if not days:
        return True  # blank = every day
    return d.strftime("%a").upper() in days


def active_items_for(checklist_type: str, d: date) -> list[dict]:
    """The items that apply to a task generated for `d`.

    Filters by: Active, Checklist Type, effective date window, and weekday.
    This is what gets snapshotted into Task Items (spec section 35).
    """
    out = []
    for r in all_items(checklist_type):
        if not as_bool(r.get("Active")):
            continue
        eff_from = r.get("Effective From")
        eff_until = r.get("Effective Until")
        if eff_from and clock.parse_date(str(eff_from)) > d:
            continue
        if eff_until and clock.parse_date(str(eff_until)) < d:
            continue
        if not _weekday_ok(r.get("Days of Week", ""), d):
            continue
        out.append(r)
    return out


def add_item(
    checklist_type: str,
    item_name: str,
    item_type: str,
    *,
    required: bool = True,
    instructions: str = "",
    sort_order: int | None = None,
    effective_from: str = "",
    effective_until: str = "",
    days_of_week: str = "",
    minimum_value: str = "",
    maximum_value: str = "",
    unit: str = "",
    created_by: str = "",
) -> dict:
    if sort_order is None:
        existing = all_items(checklist_type)
        sort_order = (max((int(r.get("Sort Order") or 0) for r in existing), default=0) + 10)
    row = {
        "Item ID": gen_id("ITEM"),
        "Checklist Type": checklist_type,
        "Item Name": item_name,
        "Instructions": instructions,
        "Item Type": item_type,
        "Required": required,
        "Active": True,
        "Sort Order": sort_order,
        "Effective From": effective_from,
        "Effective Until": effective_until,
        "Days of Week": days_of_week,
        "Minimum Value": minimum_value,
        "Maximum Value": maximum_value,
        "Unit": unit,
        "Created By": created_by,
        "Created At": now_iso(),
        "Updated At": now_iso(),
    }
    return _t().append(row)


def update_item(item_id: str, changes: dict) -> bool:
    changes = {**changes, "Updated At": now_iso()}
    return _t().update("Item ID", item_id, changes)


def archive_item(item_id: str) -> bool:
    """Never hard-delete items with history (spec section 32)."""
    return update_item(item_id, {"Active": False, "Effective Until": clock.today().isoformat()})
