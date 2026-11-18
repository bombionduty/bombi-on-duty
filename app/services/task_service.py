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
    # Use the EFFECTIVE schedule (explicit dated override, else the official
    # weekday template) so checklists keep firing every week WITHOUT needing a
    # dated row per day — the official template is the standing source of truth.
    eff = schedule_repo.resolve(d)
    if str(eff.get("status")) == constants.DAY_CLOSED:
        _ensure_closed_tasks(d)
        return []

    from app.repositories import skip_repo
    now = clock.now()
    released = []
    for checklist_type in constants.CHECKLIST_TYPES:
        if task_repo.get_by_key(d, checklist_type):
            continue  # already created — idempotent
        if skip_repo.is_skipped(d, "checklist", checklist_type):
            continue  # admin turned this one OFF for the day (Feed toggle)
        timing = timing_repo.get_timing(checklist_type, d)
        if not timing or now < timing.release_at:
            continue
        task = await _create_and_post(d, checklist_type, timing, eff)
        if task:
            released.append(task)
    return released


def _ensure_closed_tasks(d: date) -> None:
    for checklist_type in constants.CHECKLIST_TYPES:
        if not task_repo.get_by_key(d, checklist_type):
            task_repo.create_closed_task(d, checklist_type)


async def _create_and_post(d, checklist_type, timing, eff) -> dict | None:
    responsible = constants.CHECK_RESPONSIBLE[checklist_type]
    shift_b = str((eff or {}).get("shift_mode")) == constants.SHIFT_B

    if checklist_type == constants.CHECK_CLOSING and shift_b:
        # Half day: the opener also closes. Use an explicit closer override for the
        # day if one was set, otherwise fall back to the opener (NOT the official
        # template's closer, who isn't on duty on a Shift B day).
        staff_id = str((eff or {}).get("explicit_closer_id") or "") \
            or str((eff or {}).get("opener_id") or "")
    else:
        staff_id = schedule_repo.assigned_staff_id(d, responsible)
    staff = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    if not staff or not as_bool(staff.get("Active")):
        log.warning("No active %s assigned for %s on %s", responsible, checklist_type, d)
        return None

    # Closing peak support (closer-side only): a second staffer who may open and
    # continue the SAME closing checklist (spec Feature 2). On a Shift B day the
    # peak comes only from an explicit override (the template's peak isn't on duty).
    peak = None
    if responsible == "closer":
        peak_id = str((eff or {}).get("explicit_peak_id") or "") if shift_b \
            else schedule_repo.peak_staff_id(d)
        if peak_id and peak_id != staff_id:
            cand = staff_repo.get_by_staff_id(peak_id)
            if cand and as_bool(cand.get("Active")):
                peak = cand

    token = new_task_token()
    task = task_repo.create_task(
        d, checklist_type,
        token_hash=hash_token(token),
        staff=staff,
        release_at=timing.release_at,
        cutoff_at=timing.cutoff_at,
        group_chat_id=get_settings().staff_group_chat_id,
        peak=peak,
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


def compute_evidence_status(task_id: str) -> str:
    """Derive evidence status WITHOUT writing (so callers can fold it into a
    single task update)."""
    if missing_items(task_id):
        return constants.EV_MISSING
    from app.repositories import evidence_repo
    ev = evidence_repo.for_task(task_id)
    if any(as_bool(e.get("Possible Duplicate")) for e in ev):
        return constants.EV_DUPLICATE
    if any(str(e.get("Review Status")).startswith("Review") for e in ev):
        return constants.EV_REVIEW
    return constants.EV_COMPLETE


def recompute_evidence_status(task_id: str) -> str:
    status = compute_evidence_status(task_id)
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

    # Also build a tappable mention for the closing peak support, so they get
    # PINGED on the card (not just shown by name).
    psid = str(task.get("Peak Staff ID") or "")
    pname = task.get("Peak Staff Name")
    if psid or pname:
        ps = staff_repo.get_by_staff_id(psid) if psid else None
        puname = str((ps or {}).get("Telegram Username") or "").lstrip("@")
        ptgid = task.get("Peak Telegram User ID")
        if puname:
            task["_peak_mention"] = f"@{puname}"
        elif ptgid:
            task["_peak_mention"] = f'<a href="tg://user?id={ptgid}">{_html.escape(str(pname or "peak"))}</a>'
        elif pname:
            task["_peak_mention"] = _html.escape(str(pname))
    return task


def is_openable(task: dict) -> bool:
    """True while the assigned staff can still open + submit the checklist.

    Stays openable through 'Pending' and 'Not Submitted' (so staff can complete
    LATE — spec section 18). Only closes once actually submitted, recovered by
    OIC, resolved by admin, or it's a closed day.
    """
    if task.get("Submitted At"):
        return False  # already submitted (on time or late) — no button
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
    # Use the configured staff group (the task's stored chat id can be corrupted
    # on an older mis-stored row).
    await notify.edit_message(
        get_settings().staff_group_chat_id, int(task["Initial Message ID"]),
        messages.group_card(task, role_label),
        reply_markup=markup,
    )


async def repost_checklist(d: date, checklist_type: str) -> dict | None:
    """Re-sync an already-released checklist's assignee from the current schedule
    and post a FRESH group card (with a working Open Checklist button) tagging the
    current assignee. The old card is retired so there's no stale button or a card
    tagging the wrong person. Returns the task, or None if there's nothing to
    repost (not released yet, already submitted, or no active assignee).
    """
    task = task_repo.get_by_key(d, checklist_type)
    if not task or task.get("Submitted At"):
        return None  # not released yet (auto-release will tag the right person) or done

    responsible = constants.CHECK_RESPONSIBLE[checklist_type]
    try:
        eff = schedule_repo.resolve(d)
    except Exception:
        eff = {}
    shift_b = str(eff.get("shift_mode")) == constants.SHIFT_B
    if checklist_type == constants.CHECK_CLOSING and shift_b:
        # Half day: the opener closes unless an explicit closer override is set.
        staff_id = str(eff.get("explicit_closer_id") or "") or str(eff.get("opener_id") or "")
    else:
        staff_id = schedule_repo.assigned_staff_id(d, responsible)
    staff = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    if not staff or not as_bool(staff.get("Active")):
        return None

    task_id = str(task["Task ID"])
    # Re-sync assignment (Staff ID + Name + Telegram User ID — the last is what
    # authorization actually checks).
    changes = {
        "Assigned Staff ID": staff.get("Staff ID", ""),
        "Assigned Staff Name": staff.get("Staff Name", ""),
        "Assigned Telegram User ID": str(staff.get("Telegram User ID", "")),
    }
    # Closing peak support may also have changed — re-sync it too. On a Shift B
    # day the peak is tentative and comes only from the explicit override (the
    # official template's peak isn't on duty).
    if responsible == "closer":
        peak_id = str(eff.get("explicit_peak_id") or "") if shift_b \
            else schedule_repo.peak_staff_id(d)
        peak = staff_repo.get_by_staff_id(peak_id) if peak_id else None
        if peak and as_bool(peak.get("Active")) and peak_id != str(staff.get("Staff ID", "")):
            changes.update({
                "Peak Staff ID": peak.get("Staff ID", ""),
                "Peak Staff Name": peak.get("Staff Name", ""),
                "Peak Telegram User ID": str(peak.get("Telegram User ID", "")),
            })
        else:
            changes.update({"Peak Staff ID": "", "Peak Staff Name": "",
                            "Peak Telegram User ID": ""})
    task_repo.update(task_id, changes)
    task = task_repo.get(task_id)

    # Retire the old group card (drop its button + mark it reassigned).
    old_msg_id = task.get("Initial Message ID")
    if old_msg_id:
        try:
            await notify.edit_message(
                get_settings().staff_group_chat_id, int(old_msg_id),
                "↪️ <i>This checklist was reassigned — see the new card below.</i>",
                reply_markup=None)
        except Exception:
            pass

    # Post a fresh card tagging the new assignee.
    role_label = "opener" if responsible == "opener" else "closer"
    sent = await notify.send_message(
        get_settings().staff_group_chat_id,
        messages.group_card(with_mention(task), role_label),
        reply_markup=keyboards.open_checklist_button(task_id))
    if sent:
        task_repo.update(task_id, {"Initial Message ID": sent.message_id})
    audit.log("system", "Admin", constants.ROLE_ADMIN, "reassigned",
              "Task", task_id, new_value=staff.get("Staff Name", ""))
    return task_repo.get(task_id)


async def request_reupload_in_group(task: dict) -> None:
    """Ask the assigned staffer, in the group, to re-post a clear photo for a
    flagged/invalid submission. The admin then places it into the checklist via
    'Complete as admin' and verifies it — so a re-upload never silently counts as
    original on-time proof."""
    mention = with_mention(task).get("_assignee_mention") \
        or messages.esc(task.get("Assigned Staff Name") or "staff")
    await notify.send_message(
        get_settings().staff_group_chat_id,
        f"📸 <b>Photo needs re-uploading</b>\n\n{mention}, the "
        f"{messages.esc(task.get('Checklist Type'))} photo was flagged "
        f"(unclear / blank / duplicate). Please <b>send a clear photo here in the "
        f"group</b> so it can be verified. 🙏")
    if task.get("Task ID"):
        task_repo.update(str(task["Task ID"]), {"Review Required": True})


async def notify_assignment_change(d: date, role: str, old_staff_id: str,
                                   new_staff_id: str) -> None:
    """On a schedule save where the assignee changed: announce it to the group and
    repost the live checklist (if any) for the new assignee."""
    old_staff = staff_repo.get_by_staff_id(old_staff_id) if old_staff_id else None
    new_staff = staff_repo.get_by_staff_id(new_staff_id) if new_staff_id else None
    old_name = old_staff.get("Staff Name") if old_staff else "Unassigned"
    new_name = new_staff.get("Staff Name") if new_staff else "Unassigned"

    # Every checklist this role is responsible for (opener covers Opening + Handover).
    types = [ct for ct, resp in constants.CHECK_RESPONSIBLE.items() if resp == role.lower()]
    if not types:
        return

    label = "Opening/Handover" if role.lower() == "opener" else "Closing"
    await notify.send_message(
        get_settings().staff_group_chat_id,
        f"📝 <b>Shift reassignment</b>\n\n"
        f"<b>{label}</b> for <b>{messages.esc(d.strftime('%b %d, %A'))}</b>\n\n"
        f"Was assigned to: <b>{messages.esc(old_name)}</b>\n"
        f"Now assigned to: <b>{messages.esc(new_name)}</b>")

    if new_staff and as_bool(new_staff.get("Active")):
        for ct in types:
            await repost_checklist(d, ct)
