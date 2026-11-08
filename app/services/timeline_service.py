"""Today's group-notification feed (unified timeline).

One place to see EVERYTHING the bot will post to the staff group on a given day —
across the main checklists, weekly accountability tasks, shift reminders, and the
daily/weekly group recaps — with the time it fires, who gets tagged, and whether
it's already been delivered. The admin can re-announce any already-sent item.

This module only READS state to build the feed; the only side effect is the
explicit `announce()` dispatch the admin triggers per row.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as _time, timedelta

from app import clock, constants
from app.repositories import (
    schedule_repo,
    shift_reminder_repo,
    task_repo,
    timing_repo,
    weekly_repo,
)
from app.repositories.misc_repo import settings_store
from app.services import markers

log = logging.getLogger(__name__)

_CHECK_ICON = {
    constants.CHECK_OPENING: "🌅",
    constants.CHECK_HANDOVER: "🔁",
    constants.CHECK_CLOSING: "🌙",
}


def _h12(hhmm: str) -> str:
    """'22:30' -> '10:30 PM'. Falls back to the raw value if unparseable."""
    try:
        hh, mm = (str(hhmm).split(":") + ["0"])[:2]
        return _time(int(hh), int(mm)).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(hhmm)


def _weekly_spec(raw: str):
    """Parse a 'SUN 18:00' setting into (weekday, 'HH:MM') or (None, None)."""
    try:
        day, hhmm = str(raw).split()
        return day.upper(), hhmm
    except (ValueError, AttributeError):
        return None, None


def _role_names(eff: dict, role: str) -> str:
    """Human names tagged for a shift-reminder target role on this date."""
    want = {"opener": ["opener"], "closer": ["closer"],
            "both": ["opener", "closer"], "peak": ["peak"]}.get(role, [])
    names = [eff.get(f"{r}_name") for r in want if eff.get(f"{r}_id")]
    return ", ".join(n for n in names if n) or "—"


def build(d: date) -> list[dict]:
    """The ordered list of group notifications for date `d`.

    Each event: {time, at, icon, label, who, sent, kind, ref, can_announce}.
    `time` is 24h 'HH:MM' (sort key); `at` is the friendly 12h label.
    """
    eff = schedule_repo.resolve(d)
    closed = str(eff.get("status")) == constants.DAY_CLOSED
    weekday = d.strftime("%a").upper()
    events: list[dict] = []

    # 1) Main checklists (Opening / Handover / Closing).
    posted = {str(t.get("Checklist Type")): t for t in task_repo.for_date(d)}
    for ct in constants.CHECKLIST_TYPES:
        tim = timing_repo.get_timing(ct, d)
        if not tim:
            continue
        t = posted.get(ct)
        role = constants.CHECK_RESPONSIBLE.get(ct, "opener")
        who = (t.get("Assigned Staff Name") if t else "") or eff.get(f"{role}_name") or "—"
        hhmm = tim.release_at.strftime("%H:%M")
        events.append({
            "time": hhmm, "at": _h12(hhmm), "icon": _CHECK_ICON.get(ct, "📋"),
            "label": ct, "who": who, "sent": bool(t),
            "kind": "checklist", "ref": ct, "can_announce": bool(t),
        })

    # 2) Weekly accountability tasks landing today.
    for inst in weekly_repo.instances_for_date(d.isoformat()):
        sent = bool(str(inst.get("Group Message ID")))
        hhmm = str(inst.get("Time") or "00:00")
        events.append({
            "time": hhmm, "at": _h12(hhmm), "icon": "🧾",
            "label": inst.get("Title") or "Weekly checklist",
            "who": inst.get("Doer Name") or "—", "sent": sent,
            "kind": "weekly", "ref": str(inst.get("Instance ID") or ""),
            "can_announce": sent,
        })

    # 3) Shift reminders scheduled for this weekday.
    for r in shift_reminder_repo.active_rows():
        days = shift_reminder_repo.parse_days(r.get("Days"))
        if days and weekday not in days:
            continue
        rid = str(r.get("Reminder ID"))
        for slot in shift_reminder_repo.parse_slots(r.get("Slots")):
            role = slot.get("role", "both")
            who = "Whole group" if role == "group" else _role_names(eff, role)
            key = f"shiftrem::{rid}::{d.isoformat()}::{slot['time']}::{role}"
            events.append({
                "time": slot["time"], "at": _h12(slot["time"]), "icon": "⏰",
                "label": r.get("Title") or "Shift reminder", "who": who,
                "sent": markers.done(key),
                "kind": "shift", "ref": f"{rid}|{slot['time']}|{role}",
                "can_announce": not closed,
            })

    # 4) Group recaps.
    gm = settings_store.get(constants.SETTING_GOOD_MORNING_TIME) or "11:00"
    events.append({
        "time": gm, "at": _h12(gm), "icon": "☀️", "label": "Good Morning recap",
        "who": "Whole group", "sent": markers.done(f"goodmorning::{d.isoformat()}"),
        "kind": "goodmorning", "ref": "", "can_announce": True,
    })
    wsd, wsh = _weekly_spec(settings_store.get(constants.SETTING_WEEKLY_SCHEDULE_REMINDER))
    if wsd == weekday and wsh:
        events.append({
            "time": wsh, "at": _h12(wsh), "icon": "🗓️",
            "label": "Next week's schedule reminder", "who": "Whole group",
            "sent": markers.done(f"weekly_sched::{d.isoformat()}"),
            "kind": "weekly_sched", "ref": "", "can_announce": True,
        })
    wrd, wrh = _weekly_spec(settings_store.get(constants.SETTING_WEEKLY_REPORT_DAY))
    if wrd == weekday and wrh:
        events.append({
            "time": wrh, "at": _h12(wrh), "icon": "📊",
            "label": "Weekly accountability report", "who": "Whole group",
            "sent": markers.done(f"weekly_report::{d.isoformat()}"),
            "kind": "weekly_report", "ref": "", "can_announce": True,
        })

    events.sort(key=lambda e: (e["time"], e["label"]))
    return events


async def announce(kind: str, ref: str, d: date) -> tuple[bool, str]:
    """Re-post a single notification to the staff group, on demand."""
    if kind == "checklist":
        from app.services import task_service
        ok = await task_service.repost_checklist(d, ref)
        return (bool(ok),
                "Re-announced to the group. ✅" if ok
                else "That checklist hasn't been released yet, so there's nothing to re-announce.")

    if kind == "weekly":
        from app.services import weekly_service
        inst = weekly_repo.get_instance(ref)
        if not inst:
            return False, "That weekly task no longer exists."
        await weekly_service.post_card(
            inst, header="🔁 <b>WEEKLY CHECKLIST — re-announced</b>")
        return True, "Re-announced to the group. ✅"

    if kind == "shift":
        from app.services import shift_reminder_service
        try:
            rid, hhmm, role = ref.split("|")
        except ValueError:
            return False, "Could not identify that reminder."
        r = shift_reminder_repo.get(rid)
        if not r:
            return False, "That reminder no longer exists."
        await shift_reminder_service.fire(r, {"time": hhmm, "role": role}, d)
        return True, "Reminder sent to the group. ✅"

    if kind == "goodmorning":
        from app.services import summary_service
        await summary_service.send_good_morning(d - timedelta(days=1))
        return True, "Good Morning recap re-sent. ✅"

    if kind == "weekly_sched":
        from app.services import schedule_service
        await schedule_service.send_weekly_schedule_reminder()
        return True, "Schedule reminder re-sent. ✅"

    if kind == "weekly_report":
        from app.services import report_service
        await report_service.send_weekly_report(d)
        return True, "Weekly report re-sent. ✅"

    return False, "Unknown notification type."
