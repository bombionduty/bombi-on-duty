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
    return task.get("Original Submission Status") == constants.SUB_PENDING


async def send_due_reminders(task: dict) -> None:
    if not _is_incomplete(task):
        return
    d = clock.parse_date(str(task["Date"]))
    timing = timing_repo.get_timing(task["Checklist Type"], d)
    if not timing:
        return
    now = clock.now()
    missing = task_service.missing_items(task["Task ID"])
    if not missing and task_service.attestation_done(task["Task ID"]):
        return
    for i, when in enumerate(timing.reminders_at):
        if now < when:
            continue
        key = f"reminder::{task['Task ID']}::{i}"
        if markers.done(key):
            continue
        tg = task.get("Assigned Telegram User ID")
        if tg:
            await notify.send_message(tg, messages.staff_reminder(task, missing))
        markers.mark(key)


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
    oic = staff_repo.current_oic()
    if not oic or not oic.get("Telegram User ID"):
        log.warning("No OIC configured; cannot escalate task %s", task["Task ID"])
        markers.mark(key)
        return
    missing = task_service.missing_items(task["Task ID"])
    sent = await notify.send_message(
        oic["Telegram User ID"],
        messages.oic_alert(task_service.with_mention(task), missing, after_cutoff=False),
        reply_markup=keyboards.oic_followup_buttons(task["Task ID"], allow_recovery=False),
    )
    if sent:
        task_repo.update(task["Task ID"], {"OIC Alert Message ID": sent.message_id})
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

    # Notify assigned employee + OIC (spec section 18).
    tg = task.get("Assigned Telegram User ID")
    if tg:
        await notify.send_message(
            tg,
            f"🔴 <b>{task['Checklist Type']} cutoff reached.</b>\n\n"
            f"Missing at cutoff:\n" + ("\n".join(f"   ⚠️ {m}" for m in missing) or "   ⚠️ —")
            + "\n\n👉 You can still submit — it'll be recorded as <b>completed late</b>. "
            "Tap /mytask to finish it.",
        )
    oic = staff_repo.current_oic()
    if oic and oic.get("Telegram User ID"):
        sent = await notify.send_message(
            oic["Telegram User ID"],
            messages.oic_alert(fresh, missing, after_cutoff=True),
            reply_markup=keyboards.oic_followup_buttons(task["Task ID"], allow_recovery=True),
        )
        if sent:
            task_repo.update(task["Task ID"], {"OIC Alert Message ID": sent.message_id})
    markers.mark(key)
