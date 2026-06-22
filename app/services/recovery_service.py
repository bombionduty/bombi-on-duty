"""
OIC Recovery Submission (spec section 19).

The Store OIC (or admin) completes missing requirements AFTER the cutoff without
overwriting the original employee's record. The original Not Submitted status is
preserved; only the Resolution Status changes to "Recovered by Store OIC".
"""
from __future__ import annotations

import logging
from datetime import timedelta

from app import clock, constants
from app.config import get_settings
from app.repositories import staff_repo, task_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import audit, recovery, settings_store
from app.services import task_service
from app.telegram import messages, notify

log = logging.getLogger(__name__)


class RecoveryError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def can_recover(task: dict, tg_id: int) -> tuple[bool, str]:
    """Check whether tg_id may run recovery on this task."""
    is_admin = staff_repo.is_admin(tg_id)
    oic = staff_repo.current_oic()
    is_oic = oic and str(oic.get("Telegram User ID")) == str(tg_id)
    if not (is_admin or is_oic):
        return False, "Only the Store OIC or admin can complete a recovery."

    cutoff = clock.from_iso(task.get("Cutoff At"))
    now = clock.now()
    if cutoff and now < cutoff and not settings_store.get_bool(
        constants.SETTING_EMERGENCY_TAKEOVER
    ) and not is_admin:
        return False, "Recovery opens after the final cutoff."

    # Recovery window (spec section 19): N days after operating date.
    op_date = clock.parse_date(str(task["Date"]))
    window_days = settings_store.get_int(constants.SETTING_OIC_RECOVERY_DAYS)
    expiry = clock.combine(op_date, clock.parse_time("23:59")) + timedelta(days=window_days)
    if now > expiry and not is_admin:
        return False, "The OIC recovery period has expired. Only the admin can reopen this task."
    return True, ""


def build_recovery_payload(task: dict) -> dict:
    items = task_repo.items_for(task["Task ID"])
    completed, missing = [], []
    for it in items:
        record = {
            "task_item_id": it.get("Task Item ID"),
            "name": it.get("Item Name"),
            "type": it.get("Item Type"),
            "required": as_bool(it.get("Required")),
        }
        if as_bool(it.get("Completed")):
            completed.append(record)
        elif as_bool(it.get("Required")) and str(it.get("Item Type")) in constants.PROOF_ITEM_TYPES:
            missing.append(record)
    return {
        "task_id": task["Task ID"],
        "checklist_type": task["Checklist Type"],
        "operating_date": task["Date"],
        "original_assignee": task.get("Assigned Staff Name"),
        "original_status": task.get("Original Submission Status"),
        "completed_items": completed,
        "missing_items": missing,
        "confirmation": (
            "I am submitting this recovery evidence as Store OIC on behalf of "
            "the original assigned employee."
        ),
    }


def mark_item_recovered(task_item_id: str) -> None:
    task_repo.update_item(task_item_id, {
        "Completed": True,
        "Recovered": True,
        "Recovered At": clock.iso(clock.now()),
        "Completed At": clock.iso(clock.now()),
    })


async def submit_recovery(task: dict, tg_id: int, reason: str, notes: str = "") -> dict:
    ok, msg = can_recover(task, tg_id)
    if not ok:
        raise RecoveryError(msg)
    if not reason.strip():
        raise RecoveryError("A recovery reason is required.")
    if recovery.for_task(task["Task ID"]):
        raise RecoveryError("This task has already been recovered.")

    task_id = task["Task ID"]
    # Whatever proof items remain missing at this point are what was recovered.
    missing_at_cutoff = task_service.missing_items(task_id)

    actor = staff_repo.get_by_telegram_id(tg_id) or {"Staff Name": "Admin"}
    recovered_at = clock.iso(clock.now())

    recovery.add({
        "Task ID": task_id,
        "Operating Date": task["Date"],
        "Original Assigned Staff ID": task.get("Assigned Staff ID", ""),
        "Original Assigned Staff Name": task.get("Assigned Staff Name", ""),
        "Original Status": task.get("Original Submission Status", ""),
        "Missing Items at Cutoff": ", ".join(missing_at_cutoff),
        "OIC Staff ID": actor.get("Staff ID", ""),
        "OIC Name": actor.get("Staff Name", ""),
        "OIC Telegram User ID": str(tg_id),
        "Recovery Reason": reason,
        "Recovery Notes": notes,
        "Recovery Submitted At": recovered_at,
        "Resolution Status": constants.RES_RECOVERED_OIC,
    })

    # Preserve original status; only set resolution + recovered-by fields.
    task_repo.update(task_id, {
        "Resolution Status": constants.RES_RECOVERED_OIC,
        "Recovered By Staff ID": actor.get("Staff ID", ""),
        "Recovered By Telegram User ID": str(tg_id),
        "Recovered At": recovered_at,
        "Evidence Status": task_service.recompute_evidence_status(task_id),
    })
    audit.log(tg_id, actor.get("Staff Name", ""), constants.ROLE_OIC,
              "oic_recovery", "Task", task_id,
              original_staff_id=task.get("Assigned Staff ID", ""),
              reason=reason)

    fresh = task_repo.get(task_id)
    await task_service.refresh_group_card(task_id)
    await _notify_resolved(fresh, actor.get("Staff Name", ""))
    return fresh


async def _notify_resolved(task: dict, recovered_by_name: str) -> None:
    settings = get_settings()
    # Edit the OIC alert to "Resolved" if we have its message id.
    oic = staff_repo.current_oic()
    if oic and task.get("OIC Alert Message ID"):
        await notify.edit_message(
            oic["Telegram User ID"], int(task["OIC Alert Message ID"]),
            messages.oic_resolved(task_service.with_mention(task), recovered_by_name),
        )
    # Short admin notification (spec section 19 + 28).
    await notify.send_message(
        settings.admin_telegram_user_id,
        f"<b>Recovery recorded</b>\n\n{task['Checklist Type']} "
        f"originally assigned to {task.get('Assigned Staff Name')} was recovered "
        f"by {recovered_by_name} at {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}.",
    )
