"""The single live Owner dashboard message (edited in place, pinned)."""
from __future__ import annotations

import logging

from app.owner import constants as oc
from app.owner import keyboards, messages, repo, service
from app.telegram import notify

log = logging.getLogger(__name__)


async def refresh() -> None:
    gid = repo.get_owner_group_id()
    if not gid:
        return
    text = messages.dashboard_text(service.build_buckets())
    msg_id = repo.get_setting(oc.SET_DASHBOARD_MSG_ID)

    if msg_id:
        res = await notify.edit_message(gid, int(msg_id), text,
                                        reply_markup=keyboards.dashboard_kb())
        if res:  # edited successfully
            return
        # else: message was deleted/unavailable -> fall through and recreate

    sent = await notify.send_message(gid, text, reply_markup=keyboards.dashboard_kb())
    if sent:
        repo.set_setting(oc.SET_DASHBOARD_MSG_ID, str(sent.message_id))
        try:
            await notify.bot().pin_chat_message(gid, sent.message_id,
                                                disable_notification=True)
        except Exception:
            pass  # no pin permission — harmless
