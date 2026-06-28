"""The live 'good morning' summary message — posted once each morning and then
edited in place as tasks are completed/rescheduled/etc., so it always shows the
current unfinished list (by priority + due date) and what's on repeat.
"""
from __future__ import annotations

import logging

from telegram.constants import ParseMode
from telegram.error import BadRequest

from app.owner import constants as oc
from app.owner import messages, repo, service
from app.telegram import notify

log = logging.getLogger(__name__)


def _text() -> str:
    buckets = service.build_buckets()
    greeting = repo.setting_or_default(oc.SET_GREETING_NAME)
    return messages.today_summary(greeting, buckets, service.recurring_overview())


async def post() -> None:
    """Send a fresh morning summary (start of day) and remember its id."""
    gid = repo.get_owner_group_id()
    if not gid:
        return
    sent = await notify.send_message(gid, _text())
    if sent:
        repo.set_setting(oc.SET_TODAY_MSG_ID, str(sent.message_id))


async def refresh() -> None:
    """Edit today's summary in place after a task changes. No-op if it hasn't
    been posted yet (don't create a new one mid-action)."""
    gid = repo.get_owner_group_id()
    msg_id = repo.get_setting(oc.SET_TODAY_MSG_ID)
    if not gid or not msg_id:
        return
    try:
        await notify.bot().edit_message_text(
            chat_id=gid, message_id=int(msg_id), text=_text(),
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return  # already current
        log.debug("summary edit failed (message gone?): %s", e)
    except Exception as e:
        log.debug("summary edit transient error: %s", e)
