"""Schedule repository (spec sections 30 & 40 'Schedule' tab).

Two layers:
  * Official Schedule — a permanent weekday template (MON..SUN) with a default
    opener / closer / closing-peak-support. Set once, followed every week.
  * Per-date Schedule — explicit overrides for a specific date (no-show, swap).

The EFFECTIVE assignment for a date = the explicit value if set, else the
official default for that weekday. Editing a date never changes the template.
"""
from __future__ import annotations

from datetime import date

from app import clock, constants
from app.repositories import staff_repo
from app.repositories.base import now_iso
from app.sheets import client, schema


def _t():
    return client.table(schema.SCHEDULE)


def _official_t():
    return client.table(schema.OFFICIAL_SCHEDULE)


def _weekday(d: date) -> str:
    return d.strftime("%a").upper()  # MON, TUE, ...


def _name(staff_id: str) -> str:
    if not staff_id:
        return ""
    s = staff_repo.get_by_staff_id(staff_id)
    return str(s.get("Staff Name")) if s else ""


def get(d: date) -> dict | None:
    return _t().find("Date", d.isoformat())


# ---------------------------------------------------------- official schedule
def get_official() -> dict:
    """{weekday -> row} for MON..SUN (missing weekdays simply absent)."""
    out = {}
    for r in _official_t().all():
        wd = str(r.get("Weekday") or "").upper()
        if wd:
            out[wd] = r
    return out


def set_official(weekday: str, *, opener_staff_id: str = "", closer_staff_id: str = "",
                 closing_peak_staff_id: str = "") -> dict:
    wd = weekday.upper()
    changes = {
        "Opener Staff ID": opener_staff_id or "", "Opener Name": _name(opener_staff_id),
        "Closer Staff ID": closer_staff_id or "", "Closer Name": _name(closer_staff_id),
        "Closing Peak Staff ID": closing_peak_staff_id or "",
        "Closing Peak Name": _name(closing_peak_staff_id),
        "Updated At": now_iso(),
    }
    t = _official_t()
    if t.find("Weekday", wd):
        t.update("Weekday", wd, changes)
    else:
        t.append({"Weekday": wd, **changes})
    return t.find("Weekday", wd) or {"Weekday": wd, **changes}


# --------------------------------------------------- effective resolution
def resolve(d: date) -> dict:
    """Effective opener/closer/peak for a date, with the source of each value
    ('set' = explicit override, 'official' = from template, 'none' = unassigned)."""
    explicit = get(d) or {}
    off = get_official().get(_weekday(d), {})

    def pick(date_field: str, off_field: str) -> tuple[str, str]:
        v = str(explicit.get(date_field) or "")
        if v:
            return v, "set"
        ov = str(off.get(off_field) or "")
        return ov, ("official" if ov else "none")

    op, op_src = pick("Opener Staff ID", "Opener Staff ID")
    cl, cl_src = pick("Closer Staff ID", "Closer Staff ID")
    pk, pk_src = pick("Closing Peak Staff ID", "Closing Peak Staff ID")
    return {
        "date": d.isoformat(),
        "day": _weekday(d),
        "status": str(explicit.get("Status") or ""),
        "opener_id": op, "opener_name": _name(op), "opener_src": op_src,
        "closer_id": cl, "closer_name": _name(cl), "closer_src": cl_src,
        "peak_id": pk, "peak_name": _name(pk), "peak_src": pk_src,
        # raw explicit ids so the UI knows what's actually overridden
        "explicit_opener_id": str(explicit.get("Opener Staff ID") or ""),
        "explicit_closer_id": str(explicit.get("Closer Staff ID") or ""),
        "explicit_peak_id": str(explicit.get("Closing Peak Staff ID") or ""),
    }


# ---------------------------------------------------------------- per-date
def upsert(
    d: date,
    status: str | None = None,
    opener_staff_id: str | None = None,
    closer_staff_id: str | None = None,
    closing_peak_staff_id: str | None = None,
    notes: str | None = None,
) -> dict:
    existing = get(d)
    changes: dict = {"Updated At": now_iso()}
    if status is not None:
        changes["Status"] = status
    if opener_staff_id is not None:
        changes["Opener Staff ID"] = opener_staff_id
        changes["Opener Name"] = _name(opener_staff_id)
    if closer_staff_id is not None:
        changes["Closer Staff ID"] = closer_staff_id
        changes["Closer Name"] = _name(closer_staff_id)
    if closing_peak_staff_id is not None:
        changes["Closing Peak Staff ID"] = closing_peak_staff_id
        changes["Closing Peak Name"] = _name(closing_peak_staff_id)
    if notes is not None:
        changes["Notes"] = notes

    if existing:
        _t().update("Date", d.isoformat(), changes)
        return get(d)  # type: ignore[return-value]

    row = {
        "Date": d.isoformat(),
        "Day": _weekday(d),
        "Status": status or constants.DAY_OPEN,
        "Opener Staff ID": opener_staff_id or "", "Opener Name": _name(opener_staff_id),
        "Closer Staff ID": closer_staff_id or "", "Closer Name": _name(closer_staff_id),
        "Closing Peak Staff ID": closing_peak_staff_id or "",
        "Closing Peak Name": _name(closing_peak_staff_id),
        "Notes": notes or "",
        "Created At": now_iso(),
        "Updated At": now_iso(),
    }
    return _t().append(row)


def set_closed(d: date, closed: bool = True) -> dict:
    return upsert(d, status=constants.DAY_CLOSED if closed else constants.DAY_OPEN)


def assigned_staff_id(d: date, responsible: str) -> str:
    """Effective opener/closer for a date (explicit override, else official)."""
    r = resolve(d)
    return r["opener_id"] if responsible == "opener" else r["closer_id"]


def peak_staff_id(d: date) -> str:
    """Effective closing peak-support staff for a date."""
    return resolve(d)["peak_id"]


def week_rows(start: date, days: int = 7) -> list[dict]:
    """Effective schedule for a span of days (resolved against the official
    template), for the Admin Mini App to display + edit."""
    out = []
    for i in range(days):
        d = date.fromordinal(start.toordinal() + i)
        r = resolve(d)
        r["status"] = r["status"] or constants.DAY_OPEN
        out.append(r)
    return out


def copy_week(source_start: date, target_start: date, overwrite: bool = False) -> dict:
    """Copy 7 days of opener/closer/peak/status. Returns {copied, skipped}."""
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
            closing_peak_staff_id=str(src.get("Closing Peak Staff ID") or ""),
            notes=str(src.get("Notes") or ""),
        )
        copied.append(tgt_date.isoformat())
    return {"copied": copied, "skipped": skipped}
