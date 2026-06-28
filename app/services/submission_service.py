"""
Staff submission flow (spec sections 7, 8, 9, 16, 17).

Authorisation, building the Mini App payload, saving item responses, and the
final submit that locks the task and computes the on-time / late status.
"""
from __future__ import annotations

import logging
from datetime import date

from app import clock, constants
from app.config import get_settings
from app.repositories import evidence_repo, staff_repo, task_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import audit, reviews
from app.security import hash_token
from app.services import task_service
from app.telegram import keyboards, notify

log = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def task_from_token(token: str) -> dict | None:
    return task_repo.get_by_token_hash(hash_token(token))


def authorize_open(task: dict | None, tg_id: int) -> dict:
    """Validate access (spec section 7). Returns the task or raises AuthError.

    The admin may open any task for testing/review. Always re-fetches the task
    from the sheet to check the current assignment (so schedule updates take
    effect immediately without a redeploy).
    """
    if not task:
        raise AuthError("This checklist link is no longer valid.")

    # Re-fetch task from the sheet to get the current assignment (in case the
    # admin changed it in the schedule after the checklist was created).
    task_id = task.get("Task ID")
    fresh_task = task_repo.get(task_id) if task_id else None
    if fresh_task:
        task = fresh_task

    if staff_repo.is_admin(tg_id):
        return task

    assignee = staff_repo.get_by_telegram_id(tg_id)
    if not assignee or not as_bool(assignee.get("Active")):
        raise AuthError("Your account is not active. Please contact the admin.")
    if str(task.get("Assigned Telegram User ID")) != str(tg_id):
        raise AuthError(
            f"This checklist is assigned to {task.get('Assigned Staff Name')}. "
            "Please ask the assigned staff member or the admin to complete it."
        )
    # Already submitted? (covers on-time AND late completions — a late submit
    # keeps the original 'Not Submitted' status but sets Submitted At.)
    if task.get("Submitted At") or task.get("Original Submission Status") in (
        constants.SUB_ON_TIME, constants.SUB_LATE
    ):
        raise AuthError("This checklist has already been submitted. ✅")
    if task.get("Resolution Status") == constants.RES_RECOVERED_OIC:
        raise AuthError("This task was completed through an OIC recovery.")
    return task


def build_payload(task: dict, tg_id: int) -> dict:
    """The JSON the staff Mini App renders."""
    items = []
    ev_by_item: dict[str, list] = {}
    for e in evidence_repo.for_task(task["Task ID"]):
        ev_by_item.setdefault(str(e.get("Task Item ID")), []).append({
            "evidence_id": e.get("Evidence ID"),
            "capture_source": e.get("Capture Source"),
            "uploaded_at": e.get("Uploaded At"),
            "thumb_url": f"/api/evidence/{e.get('Evidence ID')}/image",
        })
    for it in task_repo.items_for(task["Task ID"]):
        items.append({
            "task_item_id": it.get("Task Item ID"),
            "name": it.get("Item Name"),
            "instructions": it.get("Instructions"),
            "type": it.get("Item Type"),
            "required": as_bool(it.get("Required")),
            "completed": as_bool(it.get("Completed")),
            "response": it.get("Response"),
            "evidence": ev_by_item.get(str(it.get("Task Item ID")), []),
        })
    return {
        "task_id": task["Task ID"],
        "checklist_type": task["Checklist Type"],
        "operating_date": task["Date"],
        "assigned_staff": task.get("Assigned Staff Name"),
        "deadline": clock.fmt_time(clock.from_iso(task.get("Cutoff At"))),
        "deadline_iso": task.get("Cutoff At"),
        "status": task.get("Original Submission Status"),
        "is_admin": staff_repo.is_admin(tg_id),
        "items": items,
        "final_acknowledgement": (
            "By submitting this checklist, you confirm that you personally "
            "checked the listed requirements and that the uploaded proof is "
            "from today's assigned shift."
        ),
    }


async def mark_started(task: dict) -> None:
    if not task.get("Started At"):
        task_repo.update(task["Task ID"], {"Started At": clock.iso(clock.now())})
        await task_service.refresh_group_card(task["Task ID"])


def save_text_response(task_item_id: str, response: str) -> None:
    task_repo.update_item(task_item_id, {
        "Response": response,
        "Completed": True,
        "Completed At": clock.iso(clock.now()),
    })


def _is_late(task: dict) -> bool:
    cutoff = clock.from_iso(task.get("Cutoff At"))
    return bool(cutoff and clock.now() > cutoff)


async def submit(
    task: dict,
    tg_id: int,
    *,
    completion_mode: str,            # "all_complete" | "issue"
    issues: list[dict] | None = None,  # [{task_item_id, details}]
) -> dict:
    """Final submit (spec section 16). Validates required proof is present."""
    task = authorize_open(task, tg_id)
    task_id = task["Task ID"]

    # 1) Required proof / entry must be complete.
    missing = task_service.missing_items(task_id)
    if missing:
        raise AuthError("Missing required proof: " + ", ".join(missing))

    # 2) Resolve attestation outcome — batched into ONE Sheets write (fast).
    issues = issues or []
    issue_map = {str(i["task_item_id"]): i.get("details", "") for i in issues}
    now_iso = clock.iso(clock.now())
    item_changes: dict[str, dict] = {}
    for it in task_repo.items_for(task_id):
        if str(it.get("Item Type")) != constants.ITEM_ATTESTATION:
            continue
        tiid = str(it.get("Task Item ID"))
        item_changes[tiid] = {
            "Completed": True,
            "Completed At": now_iso,
            "Issue Reported": tiid in issue_map,
            "Issue Details": issue_map.get(tiid, ""),
        }
    if item_changes:
        task_repo.update_items(item_changes)

    result = constants.RESULT_ISSUE if (completion_mode == "issue" and issues) \
        else constants.RESULT_ALL_COMPLETE

    late = _is_late(task)
    sub_status = constants.SUB_LATE if late else constants.SUB_ON_TIME
    # Compute (don't write) — folded into the single task update below.
    ev_status = task_service.compute_evidence_status(task_id)

    changes = {
        "Submitted At": clock.iso(clock.now()),
        "Original Submission Status": sub_status,
        "Checklist Result": result,
        "Evidence Status": ev_status,
        "Resolution Status": (constants.RES_LATE_BY_STAFF if late
                              else constants.RES_NONE),
    }
    # If this task had already passed cutoff (Not Submitted recorded), preserve
    # that event and mark resolution as completed-late (spec section 18).
    if task.get("Original Submission Status") == constants.SUB_NOT_SUBMITTED:
        changes["Resolution Status"] = constants.RES_LATE_BY_STAFF
        changes.pop("Original Submission Status")  # keep Not Submitted on record

    task_repo.update(task_id, changes)
    audit.log(tg_id, task.get("Assigned Staff Name", ""), constants.ROLE_STAFF,
              "submit", "Task", task_id, original_staff_id=task.get("Assigned Staff ID", ""))

    await task_service.refresh_group_card(task_id)
    fresh = task_repo.get(task_id)

    # Instant notifications: admin summary + OIC review package (evidence + buttons).
    from app.repositories.misc_repo import settings_store
    from app.services import summary_service
    if settings_store.get_bool(constants.SETTING_AUTO_SEND_ON_SUBMIT):
        try:
            await summary_service.notify_submission(fresh, ev_status)
        except Exception:
            log.exception("Submission notify failed for %s", task_id)
    return fresh
