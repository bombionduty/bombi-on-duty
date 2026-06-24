"""The single live Owner dashboard message (edited in place, pinned).

Recovery rules:
  * If the saved message was deleted / its id is invalid -> recreate + save new id.
  * If the text is unchanged ("not modified") -> treat as success, no duplicate.
  * Transient errors -> skip this round (next tick/action retries).
Unpinning doesn't matter — the message stays editable; we re-pin on recreate.
"""
from __future__ import annotations

import logging

from telegram.constants import ParseMode
from telegram.error import BadRequest

from app.owner import constants as oc
from app.owner import keyboards, messages, repo, service
from app.telegram import notify

log = logging.getLogger(__name__)


async def refresh() -> None:
    gid = repo.get_owner_group_id()
    if not gid:
        return
    text = messages.dashboard_text(service.build_buckets())
    kb = keyboards.dashboard_kb()
    msg_id = repo.get_setting(oc.SET_DASHBOARD_MSG_ID)

    if msg_id:
        try:
            await notify.bot().edit_message_text(
                chat_id=gid, message_id=int(msg_id), text=text,
                parse_mode=ParseMode.HTML, reply_markup=kb,
                disable_web_page_preview=True)
            return  # edited OK
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return  # already current — nothing to do
            # message deleted / invalid id -> fall through and recreate
        except Exception as e:
            log.debug("dashboard edit transient error: %s", e)
            return  # try again next time

    sent = await notify.send_message(gid, text, reply_markup=kb)
    if sent:
        repo.set_setting(oc.SET_DASHBOARD_MSG_ID, str(sent.message_id))
        try:
            await notify.bot().pin_chat_message(gid, sent.message_id, disable_notification=True)
        except Exception:
            pass
