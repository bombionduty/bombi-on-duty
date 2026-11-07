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
    # The assigned closer OR the closing peak-support staffer may open the SAME
    # closing checklist and continue where the other left off (spec Feature 2).
    peak_tg = str(task.get("Peak Telegram User ID") or "")
    allowed = str(task.get("Assigned Telegram User ID")) == str(tg_id) or (
        peak_tg and peak_tg == str(tg_id))
    if not allowed:
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
        "peak_staff": task.get("Peak Staff Name") or "",
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


def _effective_cutoff(task: dict):
    """The task's cutoff datetime. Falls back to the timing config (keyed by
    checklist type + date, which live in un-corruptible early columns) so a task
    row written before the column-alignment fix still classifies late correctly."""
    cutoff = clock.from_iso(task.get("Cutoff At"))
    if cutoff:
        return cutoff
    try:
        from app.repositories import timing_repo
        d = clock.parse_date(str(task.get("Date")))
        tm = timing_repo.get_timing(str(task.get("Checklist Type")), d)
        return tm.cutoff_at if tm else None
    except Exception:
        return None


def _is_late(task: dict) -> bool:
    cutoff = _effective_cutoff(task)
    return bool(cutoff and clock.now() > cutoff)


async def _announce_admin_completion(task: dict, not_submitted: list[str], late: bool) -> None:
    """Post a clear completion card to the staff group (used on an admin
    completion, and on-demand via re-announce)."""
    from app.telegram import messages
    ct = task.get("Checklist Type")
    on_behalf = str(task.get("Assigned Staff Name") or "staff")
    by = str(task.get("Submitted By Name") or "Admin")
    submitted = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
    when_tag = "LATE" if late else "on time"
    complete = not not_submitted
    header = ("✅ <b>%s — Submitted (Complete)</b>" % messages.esc(ct) if complete
              else "⚠️ <b>%s — Submitted (Incomplete)</b>" % messages.esc(ct))
    # "Completed by X on behalf of Y" when someone other than the assignee did it
    # (admin/peer); otherwise just "Submitted by X".
    if by and by.strip().lower() != on_behalf.strip().lower():
        who_line = f"👤 Completed by <b>{messages.esc(by)}</b> on behalf of {messages.esc(on_behalf)}"
    else:
        who_line = f"👤 Submitted by <b>{messages.esc(by or on_behalf)}</b>"
    lines = [
        header, "",
        who_line,
        f"🕐 Submitted: {messages.esc(submitted)} ({when_tag})",
    ]
    if not complete:
        items = "\n".join(f"   🚫 {messages.esc(n)}" for n in not_submitted)
        lines.append(f"\n<b>Not submitted ({len(not_submitted)}):</b>\n{items}")
    await notify.send_message(get_settings().staff_group_chat_id, "\n".join(lines))


def _was_late(task: dict) -> bool:
    """Whether the task was submitted AFTER its cutoff (uses the recorded submit
    time, not 'now' — for re-announcing an already-submitted checklist)."""
    cutoff = _effective_cutoff(task)
    sub = clock.from_iso(task.get("Submitted At"))
    return bool(cutoff and sub and sub > cutoff)


async def reannounce(task_id: str) -> tuple[bool, str]:
    """Re-post the completion message for an already-submitted task to the staff
    group (e.g. for a submission made before the auto-announce existed)."""
    task = task_repo.get(task_id)
    if not task:
        return False, "That checklist no longer exists."
    if not task.get("Submitted At"):
        return False, "This checklist hasn't been submitted yet — nothing to announce."
    not_submitted = task_service.missing_items(task_id)
    await _announce_admin_completion(task, not_submitted, _was_late(task))
    return True, "Posted the completion message to the staff group. ✅"


async def submit(
    task: dict,
    tg_id: int,
    *,
    completion_mode: str,            # "all_complete" | "issue"
    issues: list[dict] | None = None,  # [{task_item_id, details}]
    skipped_items: list | None = None,  # admin: item ids explicitly NOT submitted
) -> dict:
    """Final submit (spec section 16). Validates required proof is present.

    The admin may complete a MISSED checklist on a staff member's behalf: they can
    mark specific proof items as "not submitted" (e.g. the staff couldn't send a
    photo) and still submit. Such a submission is recorded as resolved by admin,
    and the group card names exactly which items were not submitted.
    """
    task = authorize_open(task, tg_id)
    task_id = task["Task ID"]
    is_admin = staff_repo.is_admin(tg_id)
    skipped = {str(s) for s in (skipped_items or [])}

    # Admin: record explicitly-skipped proof items as NOT submitted, so a missed
    # checklist can be closed out with a clear record of what's missing.
    if is_admin and skipped:
        sk: dict[str, dict] = {}
        for it in task_repo.items_for(task_id):
            tiid = str(it.get("Task Item ID"))
            if tiid in skipped:
                sk[tiid] = {"Completed": False, "Response": "NOT SUBMITTED",
                            "Missing At Cutoff": True}
        if sk:
            task_repo.update_items(sk)

    # 1) Required proof must be complete — EXCEPT the admin may leave items that
    #    were explicitly marked not-submitted.
    missing = task_service.missing_items(task_id)
    if missing and not is_admin:
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

    # Any required proof still missing after the above = items not submitted.
    not_submitted = task_service.missing_items(task_id)
    if is_admin:
        result = (constants.RESULT_ALL_COMPLETE if not not_submitted
                  else constants.RESULT_ISSUE)
    else:
        result = constants.RESULT_ISSUE if (completion_mode == "issue" and issues) \
            else constants.RESULT_ALL_COMPLETE

    late = _is_late(task)
    sub_status = constants.SUB_LATE if late else constants.SUB_ON_TIME
    # Compute (don't write) — folded into the single task update below.
    ev_status = task_service.compute_evidence_status(task_id)

    # Record WHO submitted (the assigned closer, the peak-support staffer, or the
    # admin completing it on behalf) so the group/summary shows the real submitter.
    submitter = staff_repo.get_by_telegram_id(tg_id)
    if submitter and not is_admin:
        submitter_name = str(submitter.get("Staff Name") or "")
    elif is_admin:
        submitter_name = str((submitter or {}).get("Staff Name") or "Admin")
    else:
        submitter_name = str(task.get("Assigned Staff Name", ""))

    changes = {
        "Submitted At": clock.iso(clock.now()),
        "Original Submission Status": sub_status,
        "Checklist Result": result,
        "Evidence Status": ev_status,
        "Submitted By Name": submitter_name,
        # An admin completion is always recorded as resolved-by-admin (so the group
        # card shows "Submitted by Admin — Complete/Incomplete").
        "Resolution Status": (constants.RES_RESOLVED_ADMIN if is_admin else
                              (constants.RES_LATE_BY_STAFF if late
                               else constants.RES_NONE)),
    }
    # If this task had already passed cutoff (Not Submitted recorded), preserve
    # that event and mark resolution accordingly (spec section 18).
    if task.get("Original Submission Status") == constants.SUB_NOT_SUBMITTED:
        changes["Resolution Status"] = (constants.RES_RESOLVED_ADMIN if is_admin
                                        else constants.RES_LATE_BY_STAFF)
        changes.pop("Original Submission Status")  # keep Not Submitted on record

    task_repo.update(task_id, changes)
    actor_role = constants.ROLE_ADMIN if is_admin else constants.ROLE_STAFF
    audit.log(tg_id, submitter_name, actor_role,
              "submit", "Task", task_id, original_staff_id=task.get("Assigned Staff ID", ""))

    await task_service.refresh_group_card(task_id)
    # Tidy the group: remove the "still pending" reminder messages now it's done.
    try:
        from app.services import ops_service
        await ops_service.clear_reminders(task_id)
    except Exception:
        log.exception("Could not clear reminders for %s", task_id)
    fresh = task_repo.get(task_id)

    # Admin completed it on a staff member's behalf: ALWAYS post a fresh, explicit
    # message to the staff group (editing the old card isn't enough — and may be
    # impossible if the card id was lost), naming who did it, complete/incomplete,
    # late/on-time, and exactly which items were not submitted.
    if is_admin:
        try:
            await _announce_admin_completion(fresh, not_submitted, late)
        except Exception:
            log.exception("Admin-completion group announcement failed for %s", task_id)

    # Instant notifications: admin summary + OIC review package (evidence + buttons).
    from app.repositories.misc_repo import settings_store
    from app.services import summary_service
    if settings_store.get_bool(constants.SETTING_AUTO_SEND_ON_SUBMIT):
        try:
            await summary_service.notify_submission(fresh, ev_status)
        except Exception:
            log.exception("Submission notify failed for %s", task_id)
    return fresh
