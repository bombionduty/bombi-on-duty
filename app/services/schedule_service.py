"""
Daily schedule pre-check + weekly schedule reminder (spec sections 30, 44).

The pre-check warns the admin privately (once per day) if the day cannot run
cleanly, so the bot never posts broken reminders.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app import clock, constants
from app.config import get_settings
from app.repositories import schedule_repo, staff_repo, timing_repo
from app.repositories.base import as_bool
from app.telegram import messages, notify

log = logging.getLogger(__name__)


def precheck_problems(d: date) -> list[str]:
    problems: list[str] = []
    # Resolve the EFFECTIVE schedule (dated override, else official template).
    # A day with no dated row is NOT a problem — it simply follows the official
    # weekday template, which is how the store normally runs.
    eff = schedule_repo.resolve(d)
    if str(eff.get("status")) == constants.DAY_CLOSED:
        return []  # closed day is fine

    # On a Shift B half-day the opener also closes (no separate closer) and there
    # is NO Opener Handover, so neither should be required or flagged.
    shift_b = str(eff.get("shift_mode")) == constants.SHIFT_B
    roles = (("opener", "Opener"),) if shift_b else (("opener", "Opener"), ("closer", "Closer"))
    for responsible, label in roles:
        sid = schedule_repo.assigned_staff_id(d, responsible)
        if not sid:
            problems.append(f"No {label} assigned.")
            continue
        staff = staff_repo.get_by_staff_id(sid)
        if not staff or not as_bool(staff.get("Active")):
            problems.append(f"{label} is not an active staff member.")
        elif not staff.get("Telegram User ID"):
            problems.append(f"{label} has no Telegram User ID.")

    if not staff_repo.current_oic():
        problems.append("No Store OIC is configured.")

    # Only the checklists that actually run that day (Handover is suppressed on
    # Shift B) need timing configured.
    types = ([constants.CHECK_OPENING, constants.CHECK_CLOSING] if shift_b
             else constants.CHECKLIST_TYPES)
    for ct in types:
        if not timing_repo.get_timing(ct, d):
            problems.append(f"No timing configured for {ct}.")
    return problems


async def run_precheck(d: date) -> None:
    problems = precheck_problems(d)
    if not problems:
        return
    text = (
        f"<b>Schedule pre-check — {clock.fmt_date(d)}</b>\n\n"
        "Please fix before the day runs:\n"
        + "\n".join(f"• {messages.esc(p)}" for p in problems)
    )
    await notify.send_message(get_settings().admin_telegram_user_id, text)


async def send_weekly_schedule_reminder() -> None:
    """Sunday 18:00 reminder to set next week (spec section 30)."""
    start = clock.today() + timedelta(days=1)
    rows = schedule_repo.week_rows(start, 7)
    missing = [r["Date"] for r in rows
               if str(r.get("Status")) != constants.DAY_CLOSED
               and not (r.get("Opener Staff ID") and r.get("Closer Staff ID"))]
    text = (
        "<b>Weekly schedule reminder</b>\n\n"
        f"Set assignments for the week starting {clock.fmt_date(start)}.\n"
    )
    if missing:
        text += "Dates still missing opener/closer:\n" + "\n".join(f"• {m}" for m in missing)
    else:
        text += "Next week already looks fully assigned. ✅"
    await notify.send_message(get_settings().admin_telegram_user_id, text)
