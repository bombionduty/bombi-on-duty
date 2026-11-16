"""
Timing repository (spec sections 21 & 'Checklist Timing' + 'Timing Overrides').

Resolves the four configurable times for a checkpoint on a given date, in this
priority order (most specific wins):
  1. Timing Overrides row for that exact date + checklist type
  2. Checklist Timing row for the matching Day Type (Weekend/Weekday)
  3. Checklist Timing row for Day Type 'Default'
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app import clock
from app.repositories.base import as_bool, now_iso
from app.sheets import client, schema


def _timing():
    return client.table(schema.CHECKLIST_TIMING)


def _overrides():
    return client.table(schema.TIMING_OVERRIDES)


@dataclass
class TaskTiming:
    release_at: datetime
    reminders_at: list[datetime]
    oic_escalation_at: datetime
    cutoff_at: datetime


def _parse_reminders(raw: str) -> list[time]:
    return [clock.parse_time(x) for x in str(raw).split(",") if x.strip()]


def _day_type(d: date) -> str:
    return "Weekend" if d.weekday() >= 5 else "Weekday"


SHIFT_B_DAY_TYPE = "Shift B"


def _shift_b_row(checklist_type: str) -> dict | None:
    """The admin-configured 'Shift B' timing row for a checklist type, if any."""
    try:
        for r in _timing().all():
            if (r.get("Checklist Type") == checklist_type
                    and str(r.get("Day Type")) == SHIFT_B_DAY_TYPE
                    and as_bool(r.get("Active", True))):
                return r
    except Exception:
        pass
    return None


def _row_for(checklist_type: str, d: date) -> dict | None:
    # 1) date-specific override
    for r in _overrides().find_all("Date", d.isoformat()):
        if r.get("Checklist Type") == checklist_type:
            return r
    timing_rows = [
        r for r in _timing().all()
        if r.get("Checklist Type") == checklist_type and as_bool(r.get("Active", True))
    ]
    by_day = {r.get("Day Type"): r for r in timing_rows}
    # 2) a Shift B day prefers the configured Shift B row (if the admin set one)
    try:
        from app.repositories import schedule_repo
        if schedule_repo.is_shift_b(d) and by_day.get(SHIFT_B_DAY_TYPE):
            return by_day[SHIFT_B_DAY_TYPE]
    except Exception:
        pass
    # 3) matching day type, 4) Default (Shift B rows never match a normal day)
    return by_day.get(_day_type(d)) or by_day.get("Default")


def _resolve_dt(d: date, t: time, base_release: time) -> datetime:
    """Build an aware datetime; if a time is earlier than release it crosses
    midnight into the next calendar day (spec section 21: times crossing midnight)."""
    dt = clock.combine(d, t)
    if t < base_release:
        dt += timedelta(days=1)
    return dt


def get_timing(checklist_type: str, d: date) -> TaskTiming | None:
    row = _row_for(checklist_type, d)
    if not row:
        return None
    release = clock.parse_time(str(row["Release Time"]))
    release_at = clock.combine(d, release)
    reminders = [_resolve_dt(d, t, release) for t in _parse_reminders(row.get("Staff Reminder Times", ""))]
    esc = _resolve_dt(d, clock.parse_time(str(row["OIC Escalation Time"])), release)
    cutoff = _resolve_dt(d, clock.parse_time(str(row["Cutoff Time"])), release)
    timing = TaskTiming(release_at, sorted(reminders), esc, cutoff)
    return _apply_shift_b(checklist_type, d, timing)


def _apply_shift_b(checklist_type: str, d: date, timing: "TaskTiming") -> TaskTiming | None:
    """On an optional half-day (Shift B): there is no Opener Handover (the opener
    also closes), and the Opening check opens at the day's duty-start time instead
    of the normal morning release. The whole opening window (reminders / escalation
    / cutoff) shifts by the same amount so the spacing is preserved."""
    from app import constants
    from app.repositories import schedule_repo
    if not schedule_repo.is_shift_b(d):
        return timing
    if checklist_type == constants.CHECK_HANDOVER:
        return None  # suppressed on half days
    if checklist_type == constants.CHECK_OPENING:
        ds = schedule_repo.duty_start_time(d)
        if ds:
            new_release = clock.combine(d, ds)
            # If the admin configured a Shift B timing row, trust its absolute
            # reminders / escalation / cutoff (the per-day Duty Start only moves
            # the opening RELEASE). Otherwise shift the whole window by the same
            # delta so nothing is left stranded in the morning.
            if _shift_b_row(checklist_type) is not None:
                return TaskTiming(new_release, timing.reminders_at,
                                  timing.oic_escalation_at, timing.cutoff_at)
            delta = new_release - timing.release_at
            return TaskTiming(
                new_release,
                sorted(r + delta for r in timing.reminders_at),
                timing.oic_escalation_at + delta,
                timing.cutoff_at + delta,
            )
    return timing


def upsert_default(
    checklist_type: str,
    day_type: str,
    release: str,
    reminders: str,
    escalation: str,
    cutoff: str,
) -> None:
    t = _timing()
    existing = [
        r for r in t.all()
        if r.get("Checklist Type") == checklist_type and r.get("Day Type") == day_type
    ]
    changes = {
        "Release Time": release,
        "Staff Reminder Times": reminders,
        "OIC Escalation Time": escalation,
        "Cutoff Time": cutoff,
        "Active": True,
        "Updated At": now_iso(),
    }
    if existing:
        # update first matching by checklist type then patch day type rows manually
        rows = t.all()
        for idx, r in enumerate(rows):
            if r.get("Checklist Type") == checklist_type and r.get("Day Type") == day_type:
                t._apply_changes(idx + 2, changes)  # noqa: SLF001 (internal helper, acceptable here)
                t._invalidate()
                return
    t.append({"Checklist Type": checklist_type, "Day Type": day_type, **changes})
