"""
Owner Mode Telegram handlers — Phase 0: registration + security only.

Commands (admin-only):
  /setupowner    — register the current group as the Owner Mode group.
  /unsetupowner  — unregister it (so it can be moved/replaced).

There is intentionally NO text/message handler in Phase 0, so Owner Mode cannot
consume or interfere with any staff-group messages. Task capture arrives in
Phase 1 and will be filtered strictly to the owner chat.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.config import get_settings
from app.owner import repo, routing

log = logging.getLogger(__name__)

OWNER_GROUP_NAME = "Bombi On Call"


async def cmd_setupowner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    # Security: only the configured admin may register an Owner group.
    if not user or not routing.is_admin_user(user.id):
        return  # silently ignore everyone else (don't reveal the command)

    if chat.type == "private":
        return await update.effective_message.reply_text(
            "Please create a small private *group* (e.g. \"Bombi On Call\"), add me, "
            "then run /setupowner inside that group.",
            parse_mode="Markdown",
        )
    # Never allow the staff group to become the owner group.
    if routing.is_staff_chat(chat.id):
        return await update.effective_message.reply_text(
            "⚠️ This is your staff group. Please make a SEPARATE private group for "
            "Owner Mode and run /setupowner there."
        )

    repo.set_owner_group_id(chat.id)
    # Try to pin a placeholder; ask the owner to pin manually if we can't.
    msg = await update.effective_message.reply_text(
        f"🍓 <b>{OWNER_GROUP_NAME}</b> is now your Owner Mode HQ.\n\n"
        "✅ This group is registered (Phase 0). Your personal task features arrive "
        "in the next phase. Staff Mode is completely unaffected.",
        parse_mode="HTML",
    )
    try:
        await ctx.bot.pin_chat_message(chat.id, msg.message_id, disable_notification=True)
    except Exception:
        await update.effective_message.reply_text(
            "ℹ️ I couldn't pin automatically (I may need admin rights in this group). "
            "You can pin my dashboard message manually later — totally optional for now."
        )


async def cmd_unsetupowner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not routing.is_admin_user(update.effective_user.id):
        return
    repo.clear_owner_group_id()
    await update.effective_message.reply_text(
        "Owner Mode group unregistered. Run /setupowner in any group to re-register."
    )


def register(application) -> None:
    application.add_handler(CommandHandler("setupowner", cmd_setupowner))
    application.add_handler(CommandHandler("unsetupowner", cmd_unsetupowner))
