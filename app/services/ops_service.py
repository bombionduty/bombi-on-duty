"""
Per-task lifecycle actions driven by the scheduler (spec sections 18, 22, 23).

  * send_due_reminders  — staff reminders listing only missing items.
  * escalate_if_due     — one consolidated OIC alert at escalation time.
  * cutoff_if_due       — mark Not Submitted, record missing items, notify.

All actions are guarded by the markers ledger so they fire exactly once.
"""
from __future__ import annotations

import logging
from datetime import date

from app import clock, constants
from app.config import get_settings
from app.repositories import staff_repo, task_repo, timing_repo
from app.repositories.misc_repo import audit
from app.services import markers, task_service
from app.telegram import keyboards, messages, notify

log = logging.getLogger(__name__)

_OPEN_STATUSES = {constants.SUB_PENDING}


def _is_incomplete(task: dict) -> bool:
    # Pending — OR a blank status (which is how a mis-stored row can read). We
    # deliberately include blank so such a task still gets reminders/cutoff
    # (cutoff then rewrites its status, healing the row).
    status = str(task.get("Original Submission Status") or "")
    return status in ("", constants.SUB_PENDING)


def _peak_mention(task: dict) -> str:
    """A tappable mention for the closing peak-support staffer, or ''."""
    import html as _html

    sid = str(task.get("Peak Staff ID") or "")
    if not sid:
        return ""
    s = staff_repo.get_by_staff_id(sid)
    uname = str((s or {}).get("Telegram Username") or "").lstrip("@")
    name = task.get("Peak Staff Name") or "peak support"
    tgid = task.get("Peak Telegram User ID")
    if uname:
        return f"@{uname}"
    if tgid:
        return f'<a href="tg://user?id={tgid}">{_html.escape(str(name))}</a>'
    return _html.escape(str(name))


async def _notify_admin_too(target, text: str, reply_markup=None) -> None:
    """Send the same alert to the admin as well, unless the admin IS the target
    (so OIC escalations/cutoffs reach the owner even on the OIC's day off)."""
    admin = get_settings().admin_telegram_user_id
    if admin and str(admin) != str(target):
        try:
            await notify.send_message(admin, text, reply_markup=reply_markup)
        except Exception:
            log.exception("admin copy of alert failed")


async def nudge_group(task_id: str) -> tuple[bool, str]:
    """Manually post a reminder to the group for a still-pending task (admin
    'nudge' button). Works before or after cutoff."""
    task = task_repo.get(task_id)
    if not task:
        return False, "That checklist no longer exists."
    # Intentionally NOT blocking on a 'Submitted At' read here — the admin asked
    # to nudge, and that field can be unreliable on an older mis-stored row. Only
    # a clearly on-time/late submission is skipped.
    if task.get("Original Submission Status") in (constants.SUB_ON_TIME, constants.SUB_LATE):
        return False, "That checklist was already submitted. ✅"
    missing = task_service.missing_items(task_id)
    fresh = task_service.with_mention(task)
    mention = fresh.get("_assignee_mention") or task.get("Assigned Staff Name")
    peak = _peak_mention(task)
    if peak:
        mention = f"{mention} / {peak}"
    # Always use the CONFIGURED staff group — the chat id stored on the task row
    # can be corrupted on an older mis-stored row, which made the send fail.
    group = get_settings().staff_group_chat_id
    sent = await notify.send_message(group, f"{mention}\n\n" + messages.staff_reminder(task, missing))
    if sent:
        from app.repositories import reminder_repo
        reminder_repo.log_reminder(task_id, group, sent.message_id)
    return True, "📣 Posted a reminder to the group."


async def send_due_reminders(task: dict) -> None:
    if not _is_incomplete(task):
        return
    d = clock.parse_date(str(task["Date"]))
    timing = timing_repo.get_timing(task["Checklist Type"], d)
    if not timing:
        return
    now = clock.now()
    missing = task_service.missing_items(task["Task ID"])
    # NOTE: we deliberately do NOT skip when nothing is "missing" — a task that is
    # still PENDING (not submitted) must keep getting its scheduled nudges, even if
    # everything is filled in, because the staff still has to tap Submit.
    for i, when in enumerate(timing.reminders_at):
        if now < when:
            continue
        key = f"reminder::{task['Task ID']}::{i}"
        if markers.done(key):
            continue
        # Post in the GROUP, tagging the assignee — visible to the admin and it
        # pings the staff even if they haven't started a private bot chat.
        fresh = task_service.with_mention(task)
        mention = fresh.get("_assignee_mention") or task.get("Assigned Staff Name")
        # Also tag the closing peak-support staffer (if any) — either of them can
        # finish the shared closing checklist (spec Feature 2).
        peak_mention = _peak_mention(task)
        if peak_mention:
            mention = f"{mention} / {peak_mention}"
        group = get_settings().staff_group_chat_id  # configured group (robust)
        sent = await notify.send_message(group, f"{mention}\n\n" + messages.staff_reminder(task, missing))
        # Track the group reminder so we can delete it once the task is submitted.
        if sent:
            from app.repositories import reminder_repo
            reminder_repo.log_reminder(task["Task ID"], group, sent.message_id)
        # Best-effort private DM too (works only if they've started the bot).
        for tg in (task.get("Assigned Telegram User ID"),
                   task.get("Peak Telegram User ID")):
            if tg:
                await notify.send_message(tg, messages.staff_reminder(task, missing))
        markers.mark(key)


async def clear_reminders(task_id: str) -> None:
    """Delete the group reminder messages for a task (called on submit) so the
    chat doesn't keep stale 'still pending' nudges after it's done."""
    from app.repositories import reminder_repo
    group = get_settings().staff_group_chat_id
    for r in reminder_repo.pending_for(task_id):
        chat = r.get("Chat ID") or group
        if await notify.delete_message(chat, r.get("Message ID")):
            reminder_repo.mark_deleted(r.get("Message ID"))


async def escalate_if_due(task: dict) -> None:
    if not _is_incomplete(task):
        return
    d = clock.parse_date(str(task["Date"]))
    timing = timing_repo.get_timing(task["Checklist Type"], d)
    if not timing or clock.now() < timing.oic_escalation_at:
        return
    key = f"escalation::{task['Task ID']}"
    if markers.done(key):
        return
    # Escalate to the OIC — or the admin if the task is assigned to the OIC.
    target, _, _ = staff_repo.oversight_target(task.get("Assigned Telegram User ID"))
    missing = task_service.missing_items(task["Task ID"])
    alert = messages.oic_alert(task_service.with_mention(task), missing, after_cutoff=False)
    markup = keyboards.oic_followup_buttons(task["Task ID"], allow_recovery=False)
    sent = await notify.send_message(target, alert, reply_markup=markup)
    if sent:
        task_repo.update(task["Task ID"], {"OIC Alert Message ID": sent.message_id})
    # Also send to the admin (so it's covered even on the OIC's day off).
    await _notify_admin_too(target, alert, markup)
    markers.mark(key)


async def cutoff_if_due(task: dict) -> None:
    if not _is_incomplete(task):
        return
    d = clock.parse_date(str(task["Date"]))
    timing = timing_repo.get_timing(task["Checklist Type"], d)
    if not timing or clock.now() < timing.cutoff_at:
        return
    key = f"cutoff::{task['Task ID']}"
    if markers.done(key):
        return

    missing = task_service.missing_items(task["Task ID"])
    # flag the still-missing items on the task-item records
    for it in task_repo.items_for(task["Task ID"]):
        if str(it.get("Item Name")) in missing:
            task_repo.update_item(it["Task Item ID"], {"Missing At Cutoff": True})

    task_repo.update(task["Task ID"], {
        "Original Submission Status": constants.SUB_NOT_SUBMITTED,
        "Not Submitted At": clock.iso(clock.now()),
        "Evidence Status": constants.EV_MISSING,
        "Resolution Status": constants.RES_STILL_INCOMPLETE,
    })
    audit.log("system", "Scheduler", "System", "cutoff_not_submitted",
              "Task", task["Task ID"], original_staff_id=task.get("Assigned Staff ID", ""),
              new_value=", ".join(missing))

    fresh = task_service.with_mention(task_repo.get(task["Task ID"]))
    fresh["_missing_text"] = ", ".join(missing)
    await task_service.refresh_group_card(task["Task ID"])

    # Notify assigned employee (+ peak support) + OIC (spec section 18).
    for tg in (task.get("Assigned Telegram User ID"),
               task.get("Peak Telegram User ID")):
        if tg:
            await notify.send_message(
                tg,
                f"🔴 <b>{task['Checklist Type']} cutoff reached.</b>\n\n"
                f"Missing at cutoff:\n" + ("\n".join(f"   ⚠️ {m}" for m in missing) or "   ⚠️ —")
                + "\n\n👉 You can still submit — it'll be recorded as <b>completed late</b>. "
                "Tap /mytask to finish it.",
            )
    # Cutoff alert to the OIC — or the admin if the task is assigned to the OIC.
    target, _, _ = staff_repo.oversight_target(task.get("Assigned Telegram User ID"))
    alert = messages.oic_alert(fresh, missing, after_cutoff=True)
    markup = keyboards.oic_followup_buttons(task["Task ID"], allow_recovery=True)
    sent = await notify.send_message(target, alert, reply_markup=markup)
    if sent:
        task_repo.update(task["Task ID"], {"OIC Alert Message ID": sent.message_id})
    # Also send to the admin (covered even on the OIC's day off).
    await _notify_admin_too(target, alert, markup)
    markers.mark(key)
