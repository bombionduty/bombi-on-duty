"""Schedule repository (spec sections 30 & 40 'Schedule' tab)."""
from __future__ import annotations

from datetime import date

from app import clock, constants
from app.repositories import staff_repo
from app.repositories.base import now_iso
from app.sheets import client, schema


def _t():
    return client.table(schema.SCHEDULE)


def get(d: date) -> dict | None:
    return _t().find("Date", d.isoformat())


def upsert(
    d: date,
    status: str | None = None,
    opener_staff_id: str | None = None,
    closer_staff_id: str | None = None,
    notes: str | None = None,
) -> dict:
    existing = get(d)
    opener = staff_repo.get_by_staff_id(opener_staff_id) if opener_staff_id else None
    closer = staff_repo.get_by_staff_id(closer_staff_id) if closer_staff_id else None

    changes: dict = {"Updated At": now_iso()}
    if status is not None:
        changes["Status"] = status
    if opener_staff_id is not None:
        changes["Opener Staff ID"] = opener_staff_id
        changes["Opener Name"] = opener["Staff Name"] if opener else ""
    if closer_staff_id is not None:
        changes["Closer Staff ID"] = closer_staff_id
        changes["Closer Name"] = closer["Staff Name"] if closer else ""
    if notes is not None:
        changes["Notes"] = notes

    if existing:
        _t().update("Date", d.isoformat(), changes)
        return get(d)  # type: ignore[return-value]

    row = {
        "Date": d.isoformat(),
        "Day": d.strftime("%a").upper(),
        "Status": status or constants.DAY_OPEN,
        "Opener Staff ID": opener_staff_id or "",
        "Opener Name": opener["Staff Name"] if opener else "",
        "Closer Staff ID": closer_staff_id or "",
        "Closer Name": closer["Staff Name"] if closer else "",
        "Notes": notes or "",
        "Created At": now_iso(),
        "Updated At": now_iso(),
    }
    return _t().append(row)


def set_closed(d: date, closed: bool = True) -> dict:
    return upsert(d, status=constants.DAY_CLOSED if closed else constants.DAY_OPEN)


def assigned_staff_id(d: date, responsible: str) -> str:
    """responsible is 'opener' or 'closer'."""
    row = get(d)
    if not row:
        return ""
    return str(row.get("Opener Staff ID" if responsible == "opener" else "Closer Staff ID") or "")


def week_rows(start: date, days: int = 7) -> list[dict]:
    out = []
    for i in range(days):
        d = date.fromordinal(start.toordinal() + i)
        out.append(get(d) or {"Date": d.isoformat(), "Day": d.strftime("%a").upper(), "Status": ""})
    return out


def copy_week(source_start: date, target_start: date, overwrite: bool = False) -> dict:
    """Copy 7 days of opener/closer/status. Returns {copied, skipped}."""
    copied, skipped = [], []
    for i in range(7):
        src = get(date.fromordinal(source_start.toordinal() + i))
        tgt_date = date.fromordinal(target_start.toordinal() + i)
        if not src:
            skipped.append(tgt_date.isoformat())
            continue
        existing = get(tgt_date)
        has_data = existing and (
            existing.get("Opener Staff ID") or existing.get("Closer Staff ID")
        )
        if has_data and not overwrite:
            skipped.append(tgt_date.isoformat())
            continue
        upsert(
            tgt_date,
            status=src.get("Status") or constants.DAY_OPEN,
            opener_staff_id=str(src.get("Opener Staff ID") or ""),
            closer_staff_id=str(src.get("Closer Staff ID") or ""),
            notes=str(src.get("Notes") or ""),
        )
        copied.append(tgt_date.isoformat())
    return {"copied": copied, "skipped": skipped}
