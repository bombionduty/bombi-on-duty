"""
Owner Mode Telegram handlers.

Phase 0: /setupowner, /unsetupowner (registration + security).
Phase 1: text task capture, confirm flow, task action buttons (Done/Reschedule/
         Waiting/Skip), /today, /week, /owner dashboard.

Isolation: the text handler only acts in the registered owner chat for the admin;
owner callbacks use the 'own:' prefix and never touch staff callbacks.
"""
from __future__ import annotations

import logging
import uuid

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import get_settings
from app.owner import constants as oc
from app.owner import dashboard, keyboards, messages, parser, repo, routing, service

log = logging.getLogger(__name__)

OWNER_GROUP_NAME = "Bombi On Call"

# Pending capture batches: batch_id -> list of parsed task dicts (in memory).
_pending: dict[str, list] = {}


def _owner_ok(update: Update) -> bool:
    """True only for the admin acting inside the registered owner chat."""
    u, c = update.effective_user, update.effective_chat
    return bool(u and c and routing.is_admin_user(u.id) and routing.is_owner_chat(c.id))


# ============================================================ setup (Phase 0)
async def cmd_setupowner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, chat = update.effective_user, update.effective_chat
    if not user or not routing.is_admin_user(user.id):
        return
    if chat.type == "private":
        return await update.effective_message.reply_text(
            "Please create a small private *group* (e.g. \"Bombi On Call\"), add me, "
            "then run /setupowner inside it.", parse_mode="Markdown")
    if routing.is_staff_chat(chat.id):
        return await update.effective_message.reply_text(
            "⚠️ This is your staff group. Make a SEPARATE private group for Owner Mode "
            "and run /setupowner there.")
    existing = repo.get_owner_group_id()
    force = bool(ctx.args) and str(ctx.args[0]).lower() == "confirm"
    if existing and str(existing) == str(chat.id):
        return await update.effective_message.reply_text(
            "✅ This group is already your Owner Mode group.")
    if existing and str(existing) != str(chat.id) and not force:
        return await update.effective_message.reply_text(
            f"⚠️ An Owner Mode group is already registered (chat <code>{existing}</code>).\n\n"
            "Run /unsetupowner in the current group first, or send "
            "<code>/setupowner confirm</code> here to replace it.", parse_mode="HTML")
    repo.set_owner_group_id(chat.id)
    msg = await update.effective_message.reply_text(
        f"🍓 <b>{OWNER_GROUP_NAME}</b> is now your Owner Mode HQ!\n\n"
        "Just type your tasks here (e.g. <i>\"pay electricity on the 28th and follow up "
        "with Alex tomorrow\"</i>) and I'll organize them. Use /today, /week, or /owner anytime.",
        parse_mode="HTML")
    try:
        await ctx.bot.pin_chat_message(chat.id, msg.message_id, disable_notification=True)
    except Exception:
        pass
    await dashboard.refresh()


async def cmd_unsetupowner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not routing.is_admin_user(update.effective_user.id):
        return
    repo.clear_owner_group_id()
    await update.effective_message.reply_text("Owner Mode unregistered. Run /setupowner to re-register.")


# ============================================================ capture (Phase 1)
async def on_owner_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return  # ignore everything outside the owner chat / non-admin
    text = update.effective_message.text or ""
    parsed = parser.parse(text)
    if not parsed:
        return await update.effective_message.reply_text(
            "🍓 I didn't catch a task there. Try e.g. <i>\"film the Biscoff video tomorrow\"</i>.",
            parse_mode="HTML")
    batch = uuid.uuid4().hex[:8]
    _pending[batch] = parsed
    await update.effective_message.reply_text(
        messages.confirm_card(parsed), parse_mode="HTML",
        reply_markup=keyboards.confirm_kb(batch))


async def _finalize(parsed: list, chat_id) -> None:
    created = service.create_from_parsed(parsed)
    await dashboard.refresh()


# ============================================================ callbacks
async def on_owner_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    if not routing.is_admin_user(q.from_user.id):
        return await q.answer("Owner only.", show_alert=True)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    # ---- capture confirm flow ----
    if action == "cf":  # confirm
        batch = parts[2]
        parsed = _pending.get(batch)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        undated = [p for p in parsed if not p.get("due")]
        if undated:
            await q.answer()
            return await q.edit_message_text(
                messages.nodate_question(len(undated)), parse_mode="HTML",
                reply_markup=keyboards.nodate_kb(batch))
        _pending.pop(batch, None)
        await _finalize(parsed, q.message.chat_id)
        await q.answer("Added ✅")
        return await q.edit_message_text(f"✅ Added {len(parsed)} task(s). See the dashboard 👇")

    if action == "cx":  # cancel
        _pending.pop(parts[2], None)
        await q.answer("Cancelled")
        return await q.edit_message_text("🗑 Cancelled — nothing was saved.")

    if action == "nd":  # no-date choice applies to all undated
        batch, key = parts[2], parts[3]
        parsed = _pending.pop(batch, None)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        when = service.resolve_when(key)
        for p in parsed:
            if not p.get("due"):
                p["due"] = when.isoformat() if when else ""
        await _finalize(parsed, q.message.chat_id)
        await q.answer("Added ✅")
        return await q.edit_message_text(f"✅ Added {len(parsed)} task(s). See the dashboard 👇")

    # ---- dashboard helpers ----
    if action == "dash":
        await dashboard.refresh()
        return await q.answer("Refreshed 🍓")
    if action == "hint":
        return await q.answer("Just type your task(s) here and I'll catch them!", show_alert=True)

    # ---- task actions ----
    if action in ("dn", "rs", "rx", "wt", "wx", "sk"):
        task_id = parts[2]
        task = repo.get_task(task_id)
        if not task:
            return await q.answer("Task not found.", show_alert=True)

        if action == "dn":  # done
            res = service.complete(task_id)
            await q.answer("Done ✅" if res else "Already done")
            await dashboard.refresh()
            return await q.edit_message_text(f"✅ <b>{messages.esc(task.get('Title'))}</b> — done!",
                                             parse_mode="HTML")
        if action == "rs":  # show reschedule options
            await q.answer()
            return await q.edit_message_reply_markup(reply_markup=keyboards.reschedule_kb(task_id))
        if action == "rx":  # apply reschedule
            when = service.resolve_when(parts[3])
            if when:
                service.reschedule(task_id, when)
            await dashboard.refresh()
            await q.answer("Rescheduled 📅")
            return await q.edit_message_text(
                f"📅 <b>{messages.esc(task.get('Title'))}</b> moved to "
                f"{messages.esc(when.strftime('%b %d').replace(' 0', ' ')) if when else 'later'}.",
                parse_mode="HTML")
        if action == "wt":  # show waiting follow-up options
            await q.answer()
            return await q.edit_message_reply_markup(reply_markup=keyboards.waiting_kb(task_id))
        if action == "wx":  # apply waiting
            when = service.resolve_when(parts[3])
            service.set_waiting(task_id, when)
            await dashboard.refresh()
            await q.answer("Marked waiting 🔵")
            return await q.edit_message_text(
                f"🔵 Waiting — <b>{messages.esc(task.get('Title'))}</b>. "
                f"I'll resurface it {messages.esc(parts[3])}.", parse_mode="HTML")
        if action == "sk":  # skip
            service.skip(task_id)
            await dashboard.refresh()
            await q.answer("Skipped 🗑")
            return await q.edit_message_text(
                f"🗑 Skipped <b>{messages.esc(task.get('Title'))}</b>.", parse_mode="HTML")

    await q.answer()


# ============================================================ commands
async def _send_task_list(chat_id, tasks, ctx, empty_msg="🌸 Nothing here — you're clear!"):
    if not tasks:
        return await ctx.bot.send_message(chat_id, empty_msg)
    for t in tasks:
        line = f"{messages.cat_emoji(t)} <b>{messages.esc(t.get('Title'))}</b>"
        due = t.get("Due Date")
        if due:
            line += f"\n🕐 {messages.esc(t.get('Due Date'))}"
        await ctx.bot.send_message(chat_id, line, parse_mode="HTML",
                                   reply_markup=keyboards.task_kb(t["Task ID"]))


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    b = service.build_buckets()
    tasks = b[oc.B_OVERDUE] + b[oc.B_DUE_TODAY]
    await _send_task_list(update.effective_chat.id, tasks, ctx,
                          "🌸 Nothing overdue or due today!")


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    b = service.build_buckets()
    tasks = b[oc.B_OVERDUE] + b[oc.B_DUE_TODAY] + b[oc.B_UPCOMING] + b[oc.B_WAITING]
    await _send_task_list(update.effective_chat.id, tasks, ctx)


async def cmd_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    await dashboard.refresh()
    await update.effective_message.reply_text("🍓 Dashboard refreshed above ⬆️")


def register(application) -> None:
    application.add_handler(CommandHandler("setupowner", cmd_setupowner))
    application.add_handler(CommandHandler("unsetupowner", cmd_unsetupowner))
    application.add_handler(CommandHandler(["owner", "dashboard"], cmd_owner))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("week", cmd_week))
    application.add_handler(CallbackQueryHandler(on_owner_callback, pattern=r"^own:"))
    # Owner text capture — only group text; the handler itself checks owner chat.
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, on_owner_text))
