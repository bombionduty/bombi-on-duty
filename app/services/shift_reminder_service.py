"""Shift reminders — fire configurable nudges to whoever is on shift.

Pure reminders: tag the on-shift staff (from the effective schedule) at each
configured time and post a message to the group. No photo, no submission.
"""
from __future__ import annotations

import html as _html
import logging
from datetime import date, datetime

from app import clock, constants
from app.config import get_settings
from app.repositories import schedule_repo, shift_reminder_repo as repo, staff_repo
from app.telegram import messages, notify

log = logging.getLogger(__name__)


def _mention(staff_id: str, name: str, tg_id) -> str:
    s = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    uname = str((s or {}).get("Telegram Username") or "").lstrip("@")
    name = name or "staff"
    if uname:
        return f"@{uname}"
    if tg_id:
        return f'<a href="tg://user?id={tg_id}">{_html.escape(str(name))}</a>'
    return _html.escape(str(name))


def _tg(staff_id: str):
    s = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    return (s or {}).get("Telegram User ID")


def _targets_for(role: str, d: date) -> list[str]:
    """Tappable mentions for the given target role on date d (effective schedule)."""
    eff = schedule_repo.resolve(d)
    want = {"opener": ["opener"], "closer": ["closer"], "both": ["opener", "closer"],
            "peak": ["peak"]}.get(role, [])
    out = []
    for r in want:
        sid = eff.get(f"{r}_id")
        if sid:
            out.append(_mention(sid, eff.get(f"{r}_name"), _tg(sid)))
    return out


def _is_closed(d: date) -> bool:
    return str(schedule_repo.resolve(d).get("status")) == constants.DAY_CLOSED


def due(now: datetime) -> list[dict]:
    """Reminder slots that should fire at `now` (weekday matches + time matches).
    Returns [{reminder, slot, key}]; the caller marker-guards each key."""
    out = []
    today = now.date()
    weekday = today.strftime("%a").upper()
    hhmm = now.strftime("%H:%M")
    for r in repo.active_rows():
        days = repo.parse_days(r.get("Days"))
        if days and weekday not in days:
            continue
        for slot in repo.parse_slots(r.get("Slots")):
            if slot["time"] != hhmm:
                continue
            rid = str(r.get("Reminder ID"))
            out.append({"reminder": r, "slot": slot,
                        "key": f"shiftrem::{rid}::{today.isoformat()}::{slot['time']}::{slot['role']}"})
    return out


async def fire(reminder: dict, slot: dict, d: date) -> None:
    """Post one reminder nudge to the staff group, tagging the on-shift role."""
    if _is_closed(d):
        return  # shop is closed that day — no nudge
    role = slot.get("role", "both")
    mentions = [] if role == "group" else _targets_for(role, d)
    title = messages.esc(reminder.get("Title") or "Reminder")
    body = messages.esc(reminder.get("Message") or "")
    tag_line = (" ".join(mentions) + "\n\n") if mentions else ""
    text = f"⏰ <b>{title}</b>\n\n{tag_line}{body}".rstrip()
    await notify.send_message(get_settings().staff_group_chat_id, text)
