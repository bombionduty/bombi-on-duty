"""
Mini App JSON API — staff checklist, OIC recovery, and admin pages.

All routes require a valid Telegram initData header (see deps.current_caller).
File uploads are validated for type + size (spec section 45).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import clock, constants
from app.config import get_settings
from app.telegram import messages, notify
from app.repositories import (
    checklist_repo,
    evidence_repo,
    schedule_repo,
    staff_repo,
    task_repo,
    timing_repo,
)
from app.repositories.base import as_bool
from app.repositories.misc_repo import recovery, reviews, settings_store
from app.services import (
    announcement_service,
    evidence_service,
    recovery_service,
    report_service,
    submission_service,
    summary_service,
    task_service,
)
from app.web.deps import Caller, current_caller

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_MAX_UPLOAD = 12 * 1024 * 1024  # 12 MB
_ALLOWED_MIME_PREFIX = ("image/",)


async def _read_upload(file: UploadFile) -> bytes:
    if not file.content_type or not file.content_type.startswith(_ALLOWED_MIME_PREFIX):
        raise HTTPException(400, "Only image uploads are allowed.")
    data = await file.read()
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(400, "File too large (max 12 MB).")
    if not data:
        raise HTTPException(400, "Empty file.")
    return data


# ============================================================= STAFF: task
@router.get("/task/by-token/{token}")
async def get_task(token: str, caller: Caller = Depends(current_caller)):
    task = submission_service.task_from_token(token)
    try:
        task = submission_service.authorize_open(task, caller.tg_id)
    except submission_service.AuthError as e:
        raise HTTPException(403, e.message)
    await submission_service.mark_started(task)
    return submission_service.build_payload(task, caller.tg_id)


@router.get("/task/{task_id}")
async def get_task_by_id(task_id: str, caller: Caller = Depends(current_caller)):
    """Open a checklist by Task ID (used by the group button + /mytask).

    Authorised purely by validated initData: only the assignee or admin passes.
    """
    task = task_repo.get(task_id)
    try:
        task = submission_service.authorize_open(task, caller.tg_id)
    except submission_service.AuthError as e:
        raise HTTPException(403, e.message)
    await submission_service.mark_started(task)
    return submission_service.build_payload(task, caller.tg_id)


@router.post("/task/{task_id}/text")
async def save_text(task_id: str, payload: dict, caller: Caller = Depends(current_caller)):
    task = task_repo.get(task_id)
    try:
        submission_service.authorize_open(task, caller.tg_id)
    except submission_service.AuthError as e:
        raise HTTPException(403, e.message)
    item = task_repo.get_item(payload["task_item_id"])
    if not item or item["Task ID"] != task_id:
        raise HTTPException(404, "Item not found.")
    response = str(payload.get("response", "")).strip()
    # Number-entry range alert (spec section 33).
    if item.get("Item Type") == constants.ITEM_NUMBER:
        tmpl = checklist_repo.get(str(item.get("Template Item ID"))) or {}
        _check_range(response, tmpl)
    submission_service.save_text_response(item["Task Item ID"], response)
    return {"ok": True}


def _check_range(value: str, tmpl: dict) -> None:
    try:
        num = float(value)
    except ValueError:
        raise HTTPException(400, "Please enter a number.")
    lo, hi = tmpl.get("Minimum Value"), tmpl.get("Maximum Value")
    if lo not in ("", None) and num < float(lo):
        raise HTTPException(400, f"Value below minimum ({lo}).")
    if hi not in ("", None) and num > float(hi):
        raise HTTPException(400, f"Value above maximum ({hi}).")


@router.post("/task/{task_id}/upload")
async def upload_proof(
    task_id: str,
    task_item_id: str = Form(...),
    capture_source: str = Form(constants.CAP_LIVE),
    file: UploadFile = File(...),
    caller: Caller = Depends(current_caller),
):
    task = task_repo.get(task_id)
    try:
        submission_service.authorize_open(task, caller.tg_id)
    except submission_service.AuthError as e:
        raise HTTPException(403, e.message)
    item = task_repo.get_item(task_item_id)
    if not item or item["Task ID"] != task_id:
        raise HTTPException(404, "Item not found.")

    data = await _read_upload(file)
    submitter = caller.staff or {"Telegram User ID": caller.tg_id}
    try:
        ev = evidence_service.process_and_store(
            task=task, task_item=item, data=data,
            filename=file.filename or "upload.jpg",
            mime_type=file.content_type or "image/jpeg",
            capture_source=capture_source,
            submitted_by=submitter,
            submitted_by_role=caller.role,
        )
    except Exception as e:  # surface a readable error instead of an opaque 500
        log.exception("Evidence upload failed for task %s", task_id)
        raise HTTPException(502, f"Could not save the image: {type(e).__name__}. Please try again.")
    task_repo.update_item(task_item_id, {
        "Completed": True, "Completed At": clock.iso(clock.now()),
        "Response": ev["Evidence ID"],
    })
    return {
        "ok": True,
        "evidence_id": ev["Evidence ID"],
        "metadata_result": ev["Metadata Result"],
        "possible_duplicate": as_bool(ev.get("Possible Duplicate")),
        "thumb_url": f"/api/evidence/{ev['Evidence ID']}/image",
    }


@router.post("/task/{task_id}/submit")
async def submit_task(task_id: str, payload: dict, caller: Caller = Depends(current_caller)):
    task = task_repo.get(task_id)
    try:
        result = await submission_service.submit(
            task, caller.tg_id,
            completion_mode=payload.get("completion_mode", "all_complete"),
            issues=payload.get("issues", []),
        )
    except submission_service.AuthError as e:
        raise HTTPException(400, e.message)
    return {"ok": True, "status": result.get("Original Submission Status"),
            "result": result.get("Checklist Result")}


# ========================================================== OIC RECOVERY
@router.get("/recovery/{task_id}")
async def recovery_view(task_id: str, caller: Caller = Depends(current_caller)):
    task = task_repo.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    ok, msg = recovery_service.can_recover(task, caller.tg_id)
    if not ok:
        raise HTTPException(403, msg)
    return recovery_service.build_recovery_payload(task)


@router.post("/recovery/{task_id}/upload")
async def recovery_upload(
    task_id: str,
    task_item_id: str = Form(...),
    capture_source: str = Form(constants.CAP_GALLERY),
    file: UploadFile = File(...),
    caller: Caller = Depends(current_caller),
):
    task = task_repo.get(task_id)
    ok, msg = recovery_service.can_recover(task, caller.tg_id)
    if not ok:
        raise HTTPException(403, msg)
    item = task_repo.get_item(task_item_id)
    if not item or item["Task ID"] != task_id:
        raise HTTPException(404, "Item not found.")
    data = await _read_upload(file)
    evidence_service.process_and_store(
        task=task, task_item=item, data=data,
        filename=file.filename or "recovery.jpg",
        mime_type=file.content_type or "image/jpeg",
        capture_source=capture_source,
        submitted_by=caller.staff or {"Telegram User ID": caller.tg_id},
        submitted_by_role=caller.role,
        on_behalf_of_staff_id=str(task.get("Assigned Staff ID", "")),
    )
    recovery_service.mark_item_recovered(task_item_id)
    return {"ok": True}


@router.post("/recovery/{task_id}/submit")
async def recovery_submit(task_id: str, payload: dict, caller: Caller = Depends(current_caller)):
    task = task_repo.get(task_id)
    try:
        fresh = await recovery_service.submit_recovery(
            task, caller.tg_id,
            reason=payload.get("reason", ""), notes=payload.get("notes", ""),
        )
    except recovery_service.RecoveryError as e:
        raise HTTPException(400, e.message)
    await summary_service.send_recovery_update(clock.parse_date(str(task["Date"])), fresh)
    return {"ok": True}


# ================================================================= ADMIN
def _admin(caller: Caller) -> Caller:
    if not caller.is_admin:
        raise HTTPException(403, "Admin only.")
    return caller


@router.get("/admin/today")
async def admin_today(date: Optional[str] = None, caller: Caller = Depends(current_caller)):
    _admin(caller)
    d = clock.parse_date(date) if date else clock.today()
    sched = schedule_repo.get(d) or {}
    tasks = []
    for t in task_repo.for_date(d):
        tasks.append({
            "checklist_type": t.get("Checklist Type"),
            "assigned": t.get("Assigned Staff Name"),
            "status": t.get("Original Submission Status"),
            "result": t.get("Checklist Result"),
            "evidence": t.get("Evidence Status"),
            "resolution": t.get("Resolution Status"),
            "missing": task_service.missing_items(t["Task ID"]),
            "task_id": t.get("Task ID"),
        })
    return {
        "date": d.isoformat(),
        "day_status": sched.get("Status"),
        "opener": sched.get("Opener Name"),
        "closer": sched.get("Closer Name"),
        "tasks": tasks,
        "recoveries": recovery.for_date(d),
    }


@router.get("/admin/schedule")
async def admin_schedule(start: Optional[str] = None, caller: Caller = Depends(current_caller)):
    _admin(caller)
    s = clock.parse_date(start) if start else clock.today()
    return {"start": s.isoformat(), "rows": schedule_repo.week_rows(s, 7)}


@router.post("/admin/schedule")
async def admin_schedule_set(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    d = clock.parse_date(payload["date"])

    # Detect assignment changes (before upserting) so we can notify the group.
    old_sched = schedule_repo.get(d) or {}
    old_opener_id = str(old_sched.get("Opener Staff ID") or "")
    old_closer_id = str(old_sched.get("Closer Staff ID") or "")
    new_opener_id = str(payload.get("opener_staff_id") or "")
    new_closer_id = str(payload.get("closer_staff_id") or "")

    # Upsert the schedule.
    schedule_repo.upsert(
        d, status=payload.get("status"),
        opener_staff_id=payload.get("opener_staff_id"),
        closer_staff_id=payload.get("closer_staff_id"),
        notes=payload.get("notes"),
    )

    # Notify group if opener or closer changed.
    from app.services import task_service
    if old_opener_id != new_opener_id:
        await task_service.notify_assignment_change(
            d, "Opening", old_opener_id, new_opener_id)
    if old_closer_id != new_closer_id:
        await task_service.notify_assignment_change(
            d, "Closing", old_closer_id, new_closer_id)

    return {"ok": True}


@router.post("/admin/notify-assignment")
async def admin_notify_assignment(payload: dict, caller: Caller = Depends(current_caller)):
    """Manually send an assignment notification to the staff group.

    Useful if the admin changes the schedule and wants to notify staff
    immediately without waiting for the next automated message.
    """
    _admin(caller)
    d = clock.parse_date(payload["date"])
    sched = schedule_repo.get(d)
    if not sched:
        raise HTTPException(404, "No schedule found for this date.")

    from app.services import task_service
    opener_id = str(sched.get("Opener Staff ID") or "")
    closer_id = str(sched.get("Closer Staff ID") or "")

    opener = staff_repo.get_by_staff_id(opener_id) if opener_id else None
    closer = staff_repo.get_by_staff_id(closer_id) if closer_id else None
    opener_name = opener.get("Staff Name") if opener else "Unassigned"
    closer_name = closer.get("Staff Name") if closer else "Unassigned"

    # Send a schedule summary.
    msg = f"📋 <b>Schedule for {messages.esc(d.strftime('%b %d, %A'))}</b>\n\n"
    msg += f"🌅 <b>Opening</b>: {messages.esc(opener_name)}\n"
    msg += f"🌙 <b>Closing</b>: {messages.esc(closer_name)}"
    await notify.send_message(get_settings().staff_group_chat_id, msg)

    # Repost any already-released checklist for the current assignee, so the new
    # person gets a card with a working Open Checklist button.
    reposted = 0
    for ct in constants.CHECKLIST_TYPES:
        if await task_service.repost_checklist(d, ct):
            reposted += 1

    return {"ok": True, "notified": True, "checklists_reposted": reposted}


@router.get("/admin/assignments")
async def admin_assignments(caller: Caller = Depends(current_caller)):
    _admin(caller)
    from app.repositories import assignment_repo
    rows = [a for a in assignment_repo.all_rows()
            if str(a.get("Status")) != assignment_repo.ST_CANCELLED]
    rows.sort(key=lambda a: (str(a.get("Status")) != assignment_repo.ST_OPEN,
                             str(a.get("Due Date") or "9999")))
    return {"assignments": rows, "staff": staff_repo.active_staff()}


@router.post("/admin/assignments")
async def admin_assignments_save(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    from app.repositories import assignment_repo
    from app.services import assignment_service
    action = payload.get("action")

    if action == "add":
        staff = staff_repo.get_by_staff_id(str(payload.get("staff_id", "")))
        if not staff:
            raise HTTPException(400, "Pick a staff member.")
        title = str(payload.get("title", "")).strip()
        if not title:
            raise HTTPException(400, "Task title is required.")
        a = await assignment_service.create(
            title=title, staff=staff,
            due_date=str(payload.get("due_date", "")),
            due_time=str(payload.get("due_time", "")),
            recurrence_rule=str(payload.get("recurrence_rule", "")),
            created_by=str(caller.tg_id))
        return {"ok": True, "assignment_id": a["Assignment ID"]}

    if action == "cancel":
        assignment_repo.update(str(payload["assignment_id"]),
                               {"Status": assignment_repo.ST_CANCELLED})
        return {"ok": True}

    raise HTTPException(400, "Unknown action.")


@router.post("/admin/copyweek")
async def admin_copyweek(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    res = schedule_repo.copy_week(
        clock.parse_date(payload["source_start"]),
        clock.parse_date(payload["target_start"]),
        overwrite=bool(payload.get("overwrite")),
    )
    return res


@router.get("/admin/staff")
async def admin_staff(caller: Caller = Depends(current_caller)):
    _admin(caller)
    return {"staff": staff_repo.all_staff(),
            "duplicates": staff_repo.duplicate_active_telegram_ids()}


@router.post("/admin/staff")
async def admin_staff_save(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    action = payload.get("action")
    if action == "add":
        staff_repo.add_staff(payload["name"], payload["telegram_user_id"],
                             role=payload.get("role", constants.ROLE_STAFF),
                             username=payload.get("username", ""))
    elif action == "update":
        staff_repo.update_staff(payload["staff_id"], payload.get("changes", {}))
    elif action == "deactivate":
        staff_repo.deactivate(payload["staff_id"])
    elif action == "assign_oic":
        staff_repo.assign_oic(payload["staff_id"])
    else:
        raise HTTPException(400, "Unknown action.")
    return {"ok": True}


@router.get("/admin/checklists")
async def admin_checklists(type: Optional[str] = None, caller: Caller = Depends(current_caller)):
    _admin(caller)
    return {"items": checklist_repo.all_items(type)}


@router.post("/admin/checklists")
async def admin_checklists_save(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    action = payload.get("action")
    if action == "add":
        checklist_repo.add_item(
            payload["checklist_type"], payload["item_name"], payload["item_type"],
            required=bool(payload.get("required", True)),
            instructions=payload.get("instructions", ""),
            effective_from=payload.get("effective_from", clock.today().isoformat()),
            effective_until=payload.get("effective_until", ""),
            days_of_week=payload.get("days_of_week", ""),
            minimum_value=str(payload.get("minimum_value", "")),
            maximum_value=str(payload.get("maximum_value", "")),
            unit=payload.get("unit", ""),
            created_by=str(caller.tg_id),
        )
    elif action == "update":
        checklist_repo.update_item(payload["item_id"], payload.get("changes", {}))
    elif action == "archive":
        checklist_repo.archive_item(payload["item_id"])
    elif action == "delete":
        checklist_repo.delete_item(payload["item_id"])
    else:
        raise HTTPException(400, "Unknown action.")
    return {"ok": True}


@router.get("/admin/timing")
async def admin_timing(caller: Caller = Depends(current_caller)):
    _admin(caller)
    from app.sheets import client, schema
    return {"timing": client.table(schema.CHECKLIST_TIMING).all()}


@router.post("/admin/timing")
async def admin_timing_save(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    timing_repo.upsert_default(
        payload["checklist_type"], payload.get("day_type", "Default"),
        payload["release"], payload["reminders"], payload["escalation"], payload["cutoff"],
    )
    return {"ok": True}


@router.get("/admin/evidence")
async def admin_evidence(date: str, caller: Caller = Depends(current_caller)):
    _admin(caller)
    d = clock.parse_date(date)
    out = []
    for e in evidence_repo.for_date(d):
        task = task_repo.get(str(e.get("Task ID"))) or {}
        uploader = staff_repo.get_by_staff_id(str(e.get("Submitted By Staff ID")))
        out.append({
            "evidence_id": e.get("Evidence ID"),
            "image_url": f"/api/evidence/{e.get('Evidence ID')}/image",
            "checklist_type": task.get("Checklist Type"),
            "original_assignee": task.get("Assigned Staff Name"),
            "uploader": uploader.get("Staff Name") if uploader else e.get("Submitted By Telegram User ID"),
            "uploader_role": e.get("Submitted By Role"),
            "capture_source": e.get("Capture Source"),
            "uploaded_at": e.get("Uploaded At"),
            "metadata_result": e.get("Metadata Result"),
            "review_status": e.get("Review Status"),
            "possible_duplicate": as_bool(e.get("Possible Duplicate")),
            "is_recovery": bool(e.get("Submitted On Behalf Of Staff ID")),
        })
    return {"date": d.isoformat(), "evidence": out}


@router.post("/admin/send-evidence")
async def admin_send_evidence(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    from app.services import evidence_delivery
    n = await evidence_delivery.send_evidence(payload["date"], payload.get("checklist_type"))
    return {"ok": True, "sent": n}


@router.get("/admin/recoveries")
async def admin_recoveries(date: Optional[str] = None, caller: Caller = Depends(current_caller)):
    _admin(caller)
    d = clock.parse_date(date) if date else clock.today()
    return {"recoveries": recovery.for_date(d)}


@router.get("/admin/reviews")
async def admin_reviews(caller: Caller = Depends(current_caller)):
    _admin(caller)
    from app.sheets import client, schema
    rows = client.table(schema.OIC_REVIEWS).all()
    return {"reviews": [r for r in rows if r.get("Review Status") == "Pending"]}


@router.post("/admin/announce")
async def admin_announce(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    ann = await announcement_service.post_announcement(payload["message"], str(caller.tg_id))
    return {"ok": True, "announcement_id": ann["Announcement ID"]}


@router.get("/admin/announcements/{announcement_id}/acks")
async def admin_acks(announcement_id: str, caller: Caller = Depends(current_caller)):
    _admin(caller)
    return announcement_service.ack_status(announcement_id)


@router.get("/admin/report")
async def admin_report(caller: Caller = Depends(current_caller)):
    _admin(caller)
    return {"text": report_service.build_text()}


@router.get("/admin/settings")
async def admin_settings(caller: Caller = Depends(current_caller)):
    _admin(caller)
    return {"settings": {k: settings_store.get(k) for k in constants.SETTING_DEFAULTS}}


@router.post("/admin/settings")
async def admin_settings_save(payload: dict, caller: Caller = Depends(current_caller)):
    _admin(caller)
    for k, v in payload.get("settings", {}).items():
        settings_store.set(k, str(v), updated_by=str(caller.tg_id))
    return {"ok": True}


@router.post("/admin/test/{what}")
async def admin_test(what: str, caller: Caller = Depends(current_caller)):
    _admin(caller)
    if what == "summary":
        await summary_service.send_daily_summary(clock.today())
    elif what == "release":
        await task_service.release_due_tasks(clock.today())
    elif what == "weekly":
        await report_service.send_weekly_report()
    else:
        raise HTTPException(400, "Unknown test action.")
    return {"ok": True}
