"""
Task generation + status logic (spec sections 10, 17, 20, 35).

This is the heart of the daily flow:
  * release_due_tasks(): create+post a checkpoint when its release time arrives.
  * missing_items(): which required proofs are still outstanding.
  * recompute_status(): derive Evidence Status from the task items.
  * refresh_group_card(): keep the single group message up to date.

Idempotency: every task has a Task Key (date+checkpoint). We never create a
second task for the same key, so reminders/releases survive restarts safely.
"""
from __future__ import annotations

import logging
from datetime import date

from app import clock, constants
from app.config import get_settings
from app.repositories import (
    checklist_repo,
    schedule_repo,
    staff_repo,
    task_repo,
    timing_repo,
)
from app.repositories.base import as_bool
from app.repositories.misc_repo import audit
from app.security import hash_token, new_task_token
from app.telegram import keyboards, messages, notify

log = logging.getLogger(__name__)


# --------------------------------------------------------------- generation
async def release_due_tasks(d: date) -> list[dict]:
    """Create + post any checkpoint whose release time has passed for date `d`.

    Returns the list of tasks released on this call (usually 0 or 1).
    """
    sched = schedule_repo.get(d)
    if not sched:
        return []  # pre-check handles missing schedule warnings
    if str(sched.get("Status")) == constants.DAY_CLOSED:
        _ensure_closed_tasks(d)
        return []

    now = clock.now()
    released = []
    for checklist_type in constants.CHECKLIST_TYPES:
        if task_repo.get_by_key(d, checklist_type):
            continue  # already created — idempotent
        timing = timing_repo.get_timing(checklist_type, d)
        if not timing or now < timing.release_at:
            continue
        task = await _create_and_post(d, checklist_type, timing, sched)
        if task:
            released.append(task)
    return released


def _ensure_closed_tasks(d: date) -> None:
    for checklist_type in constants.CHECKLIST_TYPES:
        if not task_repo.get_by_key(d, checklist_type):
            task_repo.create_closed_task(d, checklist_type)


async def _create_and_post(d, checklist_type, timing, sched) -> dict | None:
    responsible = constants.CHECK_RESPONSIBLE[checklist_type]
    staff_id = schedule_repo.assigned_staff_id(d, responsible)
    staff = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    if not staff or not as_bool(staff.get("Active")):
        log.warning("No active %s assigned for %s on %s", responsible, checklist_type, d)
        return None

    token = new_task_token()
    task = task_repo.create_task(
        d, checklist_type,
        token_hash=hash_token(token),
        staff=staff,
        release_at=timing.release_at,
        cutoff_at=timing.cutoff_at,
        group_chat_id=get_settings().staff_group_chat_id,
    )
    # Snapshot the active template items (spec section 35).
    template_items = checklist_repo.active_items_for(checklist_type, d)
    task_repo.add_items(task["Task ID"], template_items)

    # Post the single group card with the deep-link button.
    role_label = "opener" if responsible == "opener" else "closer"
    text = messages.group_card(with_mention(task), role_label)
    # The button deep-links by Task ID. Access is still strictly controlled
    # server-side by validated Telegram initData (only the assignee or admin),
    # so a guessable id is safe — and it lets us re-attach the button anytime.
    sent = await notify.send_message(
        get_settings().staff_group_chat_id, text,
        reply_markup=keyboards.open_checklist_button(task["Task ID"]),
    )
    if sent:
        task_repo.update(task["Task ID"], {"Initial Message ID": sent.message_id})
    audit.log("system", "Scheduler", "System", "task_released",
              "Task", task["Task ID"], original_staff_id=staff.get("Staff ID", ""))
    return task_repo.get(task["Task ID"])  # fresh copy


# ------------------------------------------------------------------ status
def missing_items(task_id: str) -> list[str]:
    """Required proof/entry items that are not yet completed."""
    out = []
    for item in task_repo.items_for(task_id):
        if not as_bool(item.get("Required")):
            continue
        if str(item.get("Item Type")) not in constants.PROOF_ITEM_TYPES:
            continue  # attestation items are confirmed in bulk, not "missing"
        if not as_bool(item.get("Completed")):
            out.append(str(item.get("Item Name")))
    return out


def attestation_done(task_id: str) -> bool:
    """True once the staff confirmed all-complete OR reported issues (i.e. the
    attestation block has been answered). We mark all attestation items
    Completed at submit time, so 'any attestation completed' == answered."""
    items = [i for i in task_repo.items_for(task_id)
             if str(i.get("Item Type")) == constants.ITEM_ATTESTATION]
    if not items:
        return True
    return all(as_bool(i.get("Completed")) for i in items)


def recompute_evidence_status(task_id: str) -> str:
    missing = missing_items(task_id)
    if missing:
        status = constants.EV_MISSING
    else:
        # any review/duplicate flag bubbles up
        from app.repositories import evidence_repo
        ev = evidence_repo.for_task(task_id)
        if any(as_bool(e.get("Possible Duplicate")) for e in ev):
            status = constants.EV_DUPLICATE
        elif any(str(e.get("Review Status")).startswith("Review") for e in ev):
            status = constants.EV_REVIEW
        else:
            status = constants.EV_COMPLETE
    task_repo.update(task_id, {"Evidence Status": status})
    return status


# -------------------------------------------------------------- group card
def with_mention(task: dict) -> dict:
    """Attach a tappable assignee mention (@username, else a name link that
    pings the user) so staff get notified in the group card / alerts."""
    import html as _html

    task = dict(task)
    sid = str(task.get("Assigned Staff ID") or "")
    s = staff_repo.get_by_staff_id(sid) if sid else None
    uname = str((s or {}).get("Telegram Username") or "").lstrip("@")
    name = task.get("Assigned Staff Name") or "staff"
    tgid = task.get("Assigned Telegram User ID")
    if uname:
        task["_assignee_mention"] = f"@{uname}"
    elif tgid:
        task["_assignee_mention"] = f'<a href="tg://user?id={tgid}">{_html.escape(str(name))}</a>'
    else:
        task["_assignee_mention"] = _html.escape(str(name))
    return task


def is_openable(task: dict) -> bool:
    """True while the assigned staff can still open + submit the checklist.

    Stays openable through 'Pending' and 'Not Submitted' (so staff can complete
    LATE — spec section 18). Only closes once actually submitted, recovered by
    OIC, resolved by admin, or it's a closed day.
    """
    if task.get("Original Submission Status") in (
        constants.SUB_ON_TIME, constants.SUB_LATE, constants.SUB_CLOSED
    ):
        return False
    if task.get("Resolution Status") in (
        constants.RES_RECOVERED_OIC, constants.RES_RESOLVED_ADMIN,
        constants.RES_CLOSED_NO_RECOVERY,
    ):
        return False
    return True


async def refresh_group_card(task_id: str) -> None:
    task = task_repo.get(task_id)
    if not task or not task.get("Initial Message ID"):
        return
    task = with_mention(task)
    task["_missing_text"] = ", ".join(missing_items(task_id))
    responsible = constants.CHECK_RESPONSIBLE[task["Checklist Type"]]
    role_label = "opener" if responsible == "opener" else "closer"
    # Keep the Open Checklist button while the task can still be completed, so a
    # staff member who closed the Mini App can always get back in.
    markup = keyboards.open_checklist_button(task_id) if is_openable(task) else None
    await notify.edit_message(
        task["Staff Group Chat ID"], int(task["Initial Message ID"]),
        messages.group_card(task, role_label),
        reply_markup=markup,
    )
