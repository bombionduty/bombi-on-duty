"""
Telegram commands for the Daily Owner Brief (Zite inventory) — isolated module.

  /ownerbrief            -> today's report shown in Telegram (no email)
  /ownerbrief yesterday  -> yesterday's report
  /testownerbrief        -> trigger the endpoint now (emails too) to verify setup

Admin-only. Registered from bot.py alongside (but separate from) the staff and
owner-mode handlers, so it can't affect any existing behaviour.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app import clock
from app.config import get_settings
from app.services import owner_brief

log = logging.getLogger(__name__)


def _is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.id == get_settings().admin_telegram_user_id)


async def cmd_ownerbrief(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    s = get_settings()
    if not s.owner_brief_configured:
        return await update.effective_message.reply_text(
            "Daily Owner Brief isn't configured yet. Set ZITE_OWNER_BRIEF_URL and "
            "ZITE_OWNER_BRIEF_TOKEN in the bot's environment.")
    arg = (ctx.args[0].lower() if ctx.args else "")
    day = (clock.today() - timedelta(days=1)).isoformat() if arg == "yesterday" else None
    await update.effective_message.reply_text("📊 Fetching the Daily Owner Brief…")
    res = await owner_brief.run_brief(send_email=False, day=day, alert_on_failure=False)
    if res.ok:
        await update.effective_message.reply_text(
            res.text or f"✅ Brief generated (status {res.status}). No text returned.")
    else:
        await update.effective_message.reply_text(
            f"⚠️ Couldn't get the brief: {res.error}")


async def cmd_testownerbrief(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    s = get_settings()
    if not s.owner_brief_configured:
        return await update.effective_message.reply_text(
            "Not configured — set ZITE_OWNER_BRIEF_URL and ZITE_OWNER_BRIEF_TOKEN first.")
    await update.effective_message.reply_text("🧪 Triggering the Daily Owner Brief now…")
    # No separate failure alert here — this handler already reports the outcome,
    # so a manual test won't double-message you.
    res = await owner_brief.run_brief(send_email=True, alert_on_failure=False)
    if res.ok:
        note = f"✅ Done (status {res.status}, {res.duration_s:.1f}s). Email sent to: " \
               f"{', '.join(s.owner_email_list) or '—'}"
        await update.effective_message.reply_text(note)
        if res.text:
            await update.effective_message.reply_text(res.text)
    else:
        await update.effective_message.reply_text(
            f"⚠️ Failed after retry: {res.error}")


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the current chat's numeric ID — run it inside the group you want
    the inventory brief delivered to, then set OWNER_TELEGRAM_CHAT_ID to that value."""
    if not _is_admin(update):
        return
    chat = update.effective_chat
    await update.effective_message.reply_text(
        f"🆔 This chat's ID is: <code>{chat.id}</code>\n\n"
        "Set <b>OWNER_TELEGRAM_CHAT_ID</b> to this value in the bot's .env to send "
        "the Daily Owner Brief (and its alerts) here.", parse_mode="HTML")


def register(application) -> None:
    application.add_handler(CommandHandler("ownerbrief", cmd_ownerbrief))
    application.add_handler(CommandHandler("testownerbrief", cmd_testownerbrief))
    application.add_handler(CommandHandler("chatid", cmd_chatid))
