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
from app.repositories import schedule_repo, staff_repo, task_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import notes as notes_repo
from app.repositories.misc_repo import recovery, reviews
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


def _gm_checklist_status(task: dict | None) -> str:
    if not task:
        return "🔴 Not Submitted"
    status = task.get("Original Submission Status")
    res = task.get("Resolution Status")
    if status == constants.SUB_CLOSED:
        return "➖ Closed Day"
    if res == constants.RES_RECOVERED_OIC:
        return "🟢 Recovered by OIC"
    if res == constants.RES_LATE_BY_STAFF or status == constants.SUB_LATE:
        return "🟠 Submitted Late"
    if status == constants.SUB_ON_TIME:
        return "✅ Submitted On Time"
    return "🔴 Not Submitted"


def _gm_assignment_status(a: dict) -> str:
    if str(a.get("Status")) == "Done":
        return "✅ Done 📷" if str(a.get("Completed Via")) == "photo" else "✅ Done"
    return "🔴 Not Done"


def good_morning_text(d: date) -> str:
    """Group recap of the previous day's checklists + assigned tasks."""
    e = messages.esc
    sched = schedule_repo.get(d)
    by_type = {t.get("Checklist Type"): t for t in task_repo.for_date(d)}
    opener = (sched.get("Opener Name") if sched else "") or "—"
    closer = (sched.get("Closer Name") if sched else "") or "—"

    lines = [f"🌞 <b>Good morning!</b> Here's yesterday's log — {e(clock.fmt_date(d))}", ""]
    if sched and str(sched.get("Status")) == constants.DAY_CLOSED:
        lines.append("Store was <b>CLOSED</b> — no checklists required.")
    else:
        for ct, emoji, who in (
            (constants.CHECK_OPENING, "🌅", opener),
            (constants.CHECK_HANDOVER, "🔁", opener),
            (constants.CHECK_CLOSING, "🌙", closer),
        ):
            lines.append(f"{emoji} <b>{e(ct)}</b>: {e(who)} — {_gm_checklist_status(by_type.get(ct))}")

    from app.repositories import assignment_repo
    todays = [a for a in assignment_repo.all_rows()
              if str(a.get("Due Date")) == d.isoformat()
              and str(a.get("Status")) != assignment_repo.ST_CANCELLED]
    if todays:
        lines.append("")
        lines.append("📋 <b>Tasks</b>")
        for a in todays:
            lines.append(f"• {e(a.get('Title'))} — {e(a.get('Assigned Staff Name'))}: "
                         f"{_gm_assignment_status(a)}")
    return "\n".join(lines)


async def send_good_morning(d: date) -> None:
    await notify.send_message(get_settings().staff_group_chat_id, good_morning_text(d))


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


def submission_text(task: dict) -> str:
    """Short, instant summary for ONE submitted checkpoint."""
    from app.telegram.messages import CHECK_EMOJI
    e = messages.esc
    ct = task["Checklist Type"]
    emoji = CHECK_EMOJI.get(ct, "📋")
    status = task.get("Original Submission Status")
    result = task.get("Checklist Result")
    # Friendlier status line: a late completion keeps 'Not Submitted' on record
    # for accountability, but show it clearly as a late submission here.
    if task.get("Resolution Status") == constants.RES_LATE_BY_STAFF or status == constants.SUB_LATE:
        status_disp, status_emoji = "Submitted Late (after cutoff)", "🟠"
    elif status == constants.SUB_ON_TIME:
        status_disp, status_emoji = "Submitted On Time", "✅"
    else:
        status_disp, status_emoji = str(status), "🟡"
    lines = [
        f"{emoji} <b>{e(ct)} just submitted</b>",
        "",
        f"👤 Assigned: {e(task.get('Assigned Staff Name'))}",
        f"{status_emoji} Status: {e(status_disp)}",
        f"{'🎉' if result == constants.RESULT_ALL_COMPLETE else '📝'} Result: {e(result)}",
        f"📎 Evidence: {e(task.get('Evidence Status'))}",
        f"🕐 Time: {clock.fmt_time(clock.from_iso(task.get('Submitted At')))}",
    ]
    issues = [it for it in task_repo.items_for(task["Task ID"]) if as_bool(it.get("Issue Reported"))]
    if issues:
        lines.append("")
        lines.append("⚠️ <b>Issues reported:</b>")
        for it in issues:
            lines.append(f"   • {e(it.get('Item Name'))}: {e(it.get('Issue Details'))}")
    lines.append("\n📤 Sending the evidence below…")
    return "\n".join(lines)


async def send_submission_alert(task: dict) -> None:
    """Instant admin summary + push the evidence photos (spec sections 27, 28)."""
    from app.services import evidence_delivery
    admin = get_settings().admin_telegram_user_id
    await notify.send_message(admin, submission_text(task),
                              reply_markup=keyboards.summary_buttons(str(task["Date"])))
    await evidence_delivery.send_evidence(str(task["Date"]), task["Checklist Type"])


def _review_brief(task: dict) -> str:
    e = messages.esc
    from app.telegram.messages import CHECK_EMOJI
    ct = task["Checklist Type"]
    emoji = CHECK_EMOJI.get(ct, "📋")
    when = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
    lines = [
        f"{emoji} <b>{e(ct)}</b> — {e(task.get('Assigned Staff Name'))}",
        f"Result: {e(task.get('Checklist Result'))} · Submitted {when}",
    ]
    for it in task_repo.items_for(task["Task ID"]):
        if as_bool(it.get("Issue Reported")):
            lines.append(f"⚠️ {e(it.get('Item Name'))}: {e(it.get('Issue Details'))}")
    return "\n".join(lines)


async def notify_submission(task: dict, ev_status: str) -> None:
    """On every submission: admin gets an info summary; the OIC gets the
    evidence pushed automatically with Looks Complete / Mark Incomplete buttons."""
    from app.services import evidence_delivery
    admin_id = get_settings().admin_telegram_user_id
    # The reviewer is the OIC — UNLESS the task is assigned to the OIC (or there's
    # no OIC), in which case it falls back to the admin.
    target, _target_name, _is_admin_fb = staff_repo.oversight_target(
        task.get("Assigned Telegram User ID"))

    # Admin informational summary (skip if the review already goes to the admin).
    if target != admin_id:
        await send_submission_alert(task)

    flag = ""
    if ev_status == constants.EV_DUPLICATE:
        flag = "\n\n⚠️ <b>Possible duplicate image — please check carefully.</b>"
    elif ev_status == constants.EV_REVIEW:
        flag = "\n\n⚠️ <b>System flag: review recommended.</b>"

    review = reviews.add(task["Task ID"], "Submission review")
    await notify.send_message(target, "🧐 <b>Please review this submission</b>\n\n"
                              + _review_brief(task) + flag)
    await evidence_delivery.send_evidence(str(task["Date"]), task["Checklist Type"],
                                          to_chat_id=target)
    await notify.send_message(target, "👇 Tap after checking the photos above:",
                              reply_markup=keyboards.review_buttons(review["Review ID"]))


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
