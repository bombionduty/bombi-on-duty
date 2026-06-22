"""Announcements + acknowledgement tracking (spec section 38)."""
from __future__ import annotations

from app.config import get_settings
from app.repositories import staff_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import announcements
from app.telegram import keyboards, notify


async def post_announcement(message: str, posted_by: str) -> dict:
    settings = get_settings()
    body = f"📢 <b>Announcement</b>\n\n{message}"
    sent = await notify.send_message(settings.staff_group_chat_id, body)
    ann = announcements.add(message, posted_by, sent.message_id if sent else "")
    # Re-edit to attach the ack button now that we have the announcement id.
    if sent:
        await notify.edit_message(
            settings.staff_group_chat_id, sent.message_id, body,
            reply_markup=keyboards.announcement_ack_button(ann["Announcement ID"]),
        )
    return ann


def ack_status(announcement_id: str) -> dict:
    acked = announcements.ack_user_ids(announcement_id)
    done, pending = [], []
    for s in staff_repo.active_staff():
        entry = {"name": s.get("Staff Name"), "id": s.get("Telegram User ID")}
        (done if str(s.get("Telegram User ID")) in acked else pending).append(entry)
    return {"acknowledged": done, "pending": pending}
