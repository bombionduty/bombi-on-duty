"""
"Send Evidence Here" (spec section 27).

Fetches evidence images from Drive and sends them privately to the admin as
Telegram media groups (max 10 per group), grouped by checkpoint, with captions
that show the uploader + role + recovery status.
"""
from __future__ import annotations

import logging
from datetime import date

from telegram import InputMediaPhoto

from app import clock, constants
from app.config import get_settings
from app.repositories import evidence_repo, staff_repo
from app.repositories.base import as_bool
from app.services import storage_service
from app.telegram import notify

log = logging.getLogger(__name__)

_TG_MEDIA_GROUP_LIMIT = 10


def _caption(ev: dict) -> str:
    from app.repositories import task_repo

    task = task_repo.get(str(ev.get("Task ID"))) or {}
    # Primary name is the ASSIGNED person for that shift (who's accountable).
    assignee = task.get("Assigned Staff Name") or "—"
    checkpoint = task.get("Checklist Type") or ""
    when = clock.fmt_time(clock.from_iso(ev.get("Uploaded At")))
    label = f"{checkpoint} • {ev.get('Evidence Type')}".strip(" •")
    base = f"{label} — {assignee}"

    # Only show a different uploader when it's a genuine OIC recovery.
    is_recovery = as_bool(ev.get("Submitted On Behalf Of Staff ID")) or \
        ev.get("Submitted By Role") == constants.ROLE_OIC
    if is_recovery:
        uploader = staff_repo.get_by_staff_id(str(ev.get("Submitted By Staff ID")))
        uname = uploader.get("Staff Name") if uploader else "OIC"
        base = f"{label} — {assignee} (recovered by {uname} as OIC)"

    if as_bool(ev.get("Possible Duplicate")):
        base += " ⚠️ possible duplicate"
    return f"{base} — {when}"


async def send_evidence(date_iso: str, checklist_type=None, to_chat_id=None) -> int:
    """Send images for an operating date (optionally one checkpoint).

    Sends to `to_chat_id` if given (e.g. the OIC who tapped View Evidence),
    otherwise to the admin. Returns the number of images sent.
    """
    d = clock.parse_date(date_iso)
    target = to_chat_id or get_settings().admin_telegram_user_id
    evidence = evidence_repo.for_date(d)
    if checklist_type:
        from app.repositories import task_repo
        ids = {t["Task ID"] for t in task_repo.for_date(d)
               if t.get("Checklist Type") == checklist_type}
        evidence = [e for e in evidence if e.get("Task ID") in ids]

    # De-dupe: keep only the LATEST evidence per checklist item (re-uploads).
    by_item: dict = {}
    for e in evidence:
        key = e.get("Task Item ID") or e.get("Evidence ID")
        cur = by_item.get(key)
        if not cur or str(e.get("Uploaded At")) > str(cur.get("Uploaded At")):
            by_item[key] = e
    evidence = list(by_item.values())

    if not evidence:
        await notify.send_message(target, "No evidence found for that selection.")
        return 0

    media: list[InputMediaPhoto] = []
    sent = 0
    for ev in evidence:
        file_id = ev.get("Drive File ID")
        if not file_id:
            continue
        try:
            data = storage_service.read_bytes(file_id)
        except Exception as e:
            log.warning("Drive download failed for %s: %s", ev.get("Evidence ID"), e)
            continue
        media.append(InputMediaPhoto(media=data, caption=_caption(ev)))
        if len(media) == _TG_MEDIA_GROUP_LIMIT:
            await notify.send_media_group(target, media)
            sent += len(media)
            media = []
    if media:
        await notify.send_media_group(target, media)
        sent += len(media)
    return sent
