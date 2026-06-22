"""
Daily private summary to the admin (spec sections 27, 28).

build_text() is pure (testable). send_daily_summary() sends it with the evidence
buttons and stores the message id so a later OIC recovery can edit/append it.
"""
from __future__ import annotations

import logging
from datetime import date

from app import clock, constants
from app.config import get_settings
from app.repositories import schedule_repo, task_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import notes as notes_repo
from app.repositories.misc_repo import recovery
from app.telegram import keyboards, messages, notify

log = logging.getLogger(__name__)


def _overall(tasks: list[dict]) -> str:
    if not tasks:
        return "No Data"
    if all(t.get("Original Submission Status") == constants.SUB_CLOSED for t in tasks):
        return "Closed Day"
    statuses = [t.get("Original Submission Status") for t in tasks]
    resolutions = [t.get("Resolution Status") for t in tasks]
    results = [t.get("Checklist Result") for t in tasks]
    if constants.SUB_NOT_SUBMITTED in statuses:
        if all(r in (constants.RES_RECOVERED_OIC, constants.RES_LATE_BY_STAFF)
               for s, r in zip(statuses, resolutions) if s == constants.SUB_NOT_SUBMITTED):
            return "Incomplete but Recovered"
        return "Incomplete"
    if constants.SUB_LATE in statuses:
        return "Complete with Late Tasks"
    if constants.RESULT_ISSUE in results:
        return "Complete with Issues"
    return "Complete"


def _task_block(task: dict) -> str:
    e = messages.esc
    ct = e(task["Checklist Type"])
    status = task.get("Original Submission Status")
    if status == constants.SUB_CLOSED:
        return f"<b>{ct}</b>\nClosed Day"

    lines = [f"<b>{ct}</b>"]
    if status in (constants.SUB_ON_TIME, constants.SUB_LATE):
        lines.append(f"Submission: {e(status)} at "
                     f"{clock.fmt_time(clock.from_iso(task.get('Submitted At')))}")
        lines.append(f"Result: {e(task.get('Checklist Result'))}")
        lines.append(f"Evidence: {e(task.get('Evidence Status'))}")
    elif status == constants.SUB_NOT_SUBMITTED:
        lines.append("Original Submission: Not Submitted")
        lines.append(f"Cutoff: {clock.fmt_time(clock.from_iso(task.get('Cutoff At')))}")
        missing = [i.get("Item Name") for i in task_repo.items_for(task["Task ID"])
                   if as_bool(i.get("Missing At Cutoff"))]
        if missing:
            lines.append("Missing at Cutoff:\n" + "\n".join(f"• {e(m)}" for m in missing))
        lines.append(f"Resolution: {e(task.get('Resolution Status'))}")
    else:
        lines.append(f"Status: {e(status)}")

    # Issue details
    for it in task_repo.items_for(task["Task ID"]):
        if as_bool(it.get("Issue Reported")):
            lines.append(f"Issue — {e(it.get('Item Name'))}: {e(it.get('Issue Details'))}")
    return "\n".join(lines)


def build_text(d: date) -> str:
    sched = schedule_repo.get(d)
    tasks = sorted(task_repo.for_date(d),
                   key=lambda t: constants.CHECKLIST_TYPES.index(t["Checklist Type"])
                   if t.get("Checklist Type") in constants.CHECKLIST_TYPES else 9)
    header = f"<b>Berry Bomb Daily Ops Summary — {clock.fmt_date(d)}</b>"
    if sched and str(sched.get("Status")) == constants.DAY_CLOSED:
        return f"{header}\n\nStore was CLOSED.\nNo checklists were required."

    parts = [header, ""]
    parts.append("<b>Assigned Staff</b>")
    parts.append(f"Opener: {messages.esc(sched.get('Opener Name') if sched else '—') or '—'}")
    parts.append(f"Closer: {messages.esc(sched.get('Closer Name') if sched else '—') or '—'}")
    parts.append("")

    for t in tasks:
        parts.append(_task_block(t))
        parts.append("")

    day_notes = notes_repo.for_date(d)
    if day_notes:
        parts.append("<b>Additional Notes</b>")
        for n in day_notes:
            parts.append(f"• {messages.esc(n.get('Note'))}")
        parts.append("")

    recs = recovery.for_date(d)
    if recs:
        parts.append("<b>OIC Recoveries</b>")
        for r in recs:
            parts.append(f"• {messages.esc(r.get('Original Assigned Staff Name'))}: "
                         f"recovered by {messages.esc(r.get('OIC Name'))}")
        parts.append("")

    parts.append(f"<b>Overall Status</b>\n{_overall(tasks)}")
    return "\n".join(parts)


async def send_daily_summary(d: date) -> None:
    settings = get_settings()
    text = build_text(d)
    sent = await notify.send_message(
        settings.admin_telegram_user_id, text,
        reply_markup=keyboards.summary_buttons(d.isoformat()),
    )
    if sent:
        for t in task_repo.for_date(d):
            task_repo.update(t["Task ID"], {"Daily Summary Message ID": sent.message_id})


async def send_recovery_update(d: date, task: dict) -> None:
    """After an OIC recovery, append a short resolution message (spec section 28)."""
    settings = get_settings()
    text = (
        f"<b>{task['Checklist Type']} Update — {clock.fmt_date(d)}</b>\n\n"
        f"Original Submission: Not Submitted\n"
        f"Resolution: Recovered by Store OIC\n"
        f"Recovered by: {messages.esc(task.get('Recovered By Telegram User ID'))}\n"
        f"Recovered at: {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}"
    )
    await notify.send_message(settings.admin_telegram_user_id, text)
