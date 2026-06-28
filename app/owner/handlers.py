"""
Owner Mode Telegram handlers.

Phase 0: /setupowner, /unsetupowner (registration + security).
Phase 1: text task capture, confirm + EDIT flow, task action buttons
         (Done/Reschedule/Waiting/Skip), /today, /week, /owner dashboard.

Isolation/security: the text handler only acts for the admin inside the
registered owner chat; owner callbacks use the 'own:' prefix.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from telegram import ForceReply, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app import clock
from app.owner import constants as oc
from app.owner import dashboard, draft, keyboards, messages, parser, repo, routing, service

log = logging.getLogger(__name__)

OWNER_GROUP_NAME = "Bombi On Call"
OWNER_CALLBACK_PATTERN = r"^own:"

# Only this maps a user to a pending typed-input step; drafts live in draft.py.
_await_input: dict[int, dict] = {}    # uid -> {"kind","batch","idx"}


def _owner_ok(update: Update) -> bool:
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
        "with Alex tomorrow\"</i>). Use /today, /week, or /owner anytime.\n\n"
        "ℹ️ Make me an <b>admin</b> in this group so I can read your messages and pin "
        "the dashboard.", parse_mode="HTML")
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
    # Security guards: only a real (non-bot) message, from the admin, in the
    # owner chat. Edited messages / channel posts have update.message == None.
    # Ignore edited messages / channel posts (those have update.message == None).
    msg = update.message
    if msg is None:
        return
    user = msg.from_user
    if not routing.capture_allowed(chat_id=msg.chat.id,
                                   user_id=(user.id if user else 0),
                                   is_bot=bool(user and user.is_bot),
                                   has_text=bool(msg.text)):
        return

    uid = user.id
    text = msg.text or ""

    # Mid-edit typed input takes priority over parsing as new tasks.
    if uid in _await_input:
        return await _handle_await_input(update, ctx, text)

    parsed = parser.parse(text)
    if not parsed:
        return await msg.reply_text(
            "🍓 I didn't catch a task there. Try e.g. <i>\"film the Biscoff video tomorrow\"</i>.",
            parse_mode="HTML")
    batch = draft.create(parsed, capture_chat=msg.chat.id, capture_msg=msg.message_id)
    sent = await msg.reply_text(messages.confirm_card(parsed), parse_mode="HTML",
                                reply_markup=keyboards.confirm_kb(batch))
    if sent:
        draft.set_confirm_msg(batch, sent.message_id)


def _parse_typed_date(text: str):
    due, _, _ = parser._extract_when(text)
    if due:
        return due
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%b %d", "%B %d"):
        try:
            dt = datetime.strptime(text.strip(), fmt).date()
            if "%Y" not in fmt:
                dt = dt.replace(year=clock.today().year)
            return dt
        except ValueError:
            continue
    return None


async def _handle_await_input(update: Update, ctx, text: str) -> None:
    uid = update.effective_user.id
    state = _await_input.pop(uid, None)
    if not state:
        return
    kind = state["kind"]

    # ---- settings edits (no draft involved) ----
    if kind.startswith("setting:"):
        key = kind.split(":", 1)[1]
        val = text.strip()
        keymap = {"daily": oc.SET_DAILY_SUMMARY, "weekly": oc.SET_WEEKLY_SUMMARY,
                  "lead": oc.SET_LEAD_DAYS, "timed": oc.SET_TIMED_LEAD_MIN,
                  "upcoming": oc.SET_UPCOMING_DAYS, "name": oc.SET_GREETING_NAME}
        if key in keymap and val:
            repo.set_setting(keymap[key], val)
            return await update.message.reply_text(f"✅ Saved. ({val})")
        return await update.message.reply_text("Hmm, that didn't look valid — try /setup again.")

    # ---- typed reschedule date for an existing task ----
    if kind.startswith("reschedule:"):
        task_id = kind.split(":", 1)[1]
        d = _parse_typed_date(text)
        if not d:
            return await update.message.reply_text("Couldn't read that date — try again from the card.")
        t = service.reschedule(task_id, d)
        await dashboard.refresh()
        if t:
            await update.message.reply_text(
                messages.task_card(t, header="📅 <b>RESCHEDULED</b>"), parse_mode="HTML",
                reply_markup=keyboards.task_card_kb(task_id, bool(t.get("Recurrence ID"))))
        return

    batch = state["batch"]
    parsed = draft.get(batch)
    if not parsed:
        return await update.message.reply_text("That edit session expired — please resend the task.")

    if kind == "title":
        draft.edit_title(batch, state["idx"], text)
    elif kind == "date_task":
        d = _parse_typed_date(text)
        draft.edit_date(batch, state["idx"], d.isoformat() if d else "")
    elif kind == "date_batch":
        d = _parse_typed_date(text)
        draft.apply_shared_date(batch, d.isoformat() if d else "")
        meta = draft.meta(batch)
        parsed = draft.pop(batch)
        created = service.create_from_parsed(parsed)
        # tidy: the typed-date message, the confirm/nodate card, the capture msg
        await _safe_delete(ctx, update.effective_chat.id, update.message.message_id)
        await _safe_delete(ctx, meta.get("capture_chat"), meta.get("confirm_msg"))
        await _safe_delete(ctx, meta.get("capture_chat"), meta.get("capture_msg"))
        await _send_cards(ctx, update.effective_chat.id, created)
        await dashboard.refresh()
        return

    await update.message.reply_text(messages.confirm_card(parsed), parse_mode="HTML",
                                    reply_markup=keyboards.confirm_kb(batch))


# ============================================================ cleanup helpers
async def _safe_delete(ctx, chat_id, message_id) -> bool:
    """Delete a message; never raise (missing Delete permission / too old / gone)."""
    if not chat_id or not message_id:
        return False
    try:
        await ctx.bot.delete_message(chat_id, int(message_id))
        return True
    except Exception as e:
        log.debug("owner cleanup: could not delete %s: %s", message_id, e)
        return False


async def _close_card(ctx, q, fallback_html: str) -> None:
    """Remove a finished task card: delete it, or (if too old) shrink it to a
    tiny final state with no buttons. Never raises."""
    if await _safe_delete(ctx, q.message.chat_id, q.message.message_id):
        return
    try:
        await q.edit_message_text(fallback_html, parse_mode="HTML")
    except Exception:
        pass


# ============================================================ callbacks
async def _send_cards(ctx, chat_id, created: list) -> None:
    """After Confirm: send one actionable card per saved task and remember each
    card's message id (so Clean Chat can tidy any strays later)."""
    for t in created:
        sent = await ctx.bot.send_message(
            chat_id, messages.task_card(t), parse_mode="HTML",
            reply_markup=keyboards.task_card_kb(t["Task ID"], bool(t.get("Recurrence ID"))))
        if sent:
            repo.update_task(t["Task ID"], {"Source Message ID": str(sent.message_id)})


def _task_detail(p: dict) -> str:
    due = p.get("due") or "no date"
    who = p.get("responsible") or "me"
    return (f"Editing: <b>{messages.esc(p.get('title'))}</b>\n"
            f"📅 {messages.esc(due)} · 👤 {messages.esc(who)}\n\nWhat do you want to change?")


async def on_owner_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not routing.is_admin_user(q.from_user.id):
        return await q.answer("Owner only.", show_alert=True)
    parts = (q.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    # ---------- capture confirm ----------
    if action == "cf":
        batch = parts[2]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        undated = [p for p in parsed if not p.get("due")]
        if undated:
            await q.answer()
            return await q.edit_message_text(messages.nodate_question(len(undated)),
                                             parse_mode="HTML", reply_markup=keyboards.nodate_kb(batch))
        meta = draft.meta(batch)
        draft.pop(batch, None)
        created = service.create_from_parsed(parsed)  # SAVE before any cleanup
        await q.answer("Added ✅")
        # Clean up: remove the draft card + my original capture message.
        await _safe_delete(ctx, q.message.chat_id, q.message.message_id)
        await _safe_delete(ctx, meta.get("capture_chat"), meta.get("capture_msg"))
        await _send_cards(ctx, q.message.chat_id, created)
        await dashboard.refresh()
        return

    if action == "cx":
        draft.pop(parts[2], None)
        await q.answer("Cancelled — nothing saved")
        return await _safe_delete(ctx, q.message.chat_id, q.message.message_id)

    if action == "nd":
        batch, key = parts[2], parts[3]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        if key == "choose":
            _await_input[q.from_user.id] = {"kind": "date_batch", "batch": batch}
            await q.answer()
            return await ctx.bot.send_message(
                q.message.chat_id, "📅 Type a date (e.g. <code>2026-07-15</code> or "
                "<code>next friday</code>):", parse_mode="HTML",
                reply_markup=ForceReply(input_field_placeholder="e.g. 2026-07-15"))
        meta = draft.meta(batch)
        draft.pop(batch, None)
        when = service.resolve_when(key)
        for p in parsed:
            if not p.get("due"):
                p["due"] = when.isoformat() if when else ""
        created = service.create_from_parsed(parsed)
        await q.answer("Added ✅")
        await _safe_delete(ctx, q.message.chat_id, q.message.message_id)
        await _safe_delete(ctx, meta.get("capture_chat"), meta.get("capture_msg"))
        await _send_cards(ctx, q.message.chat_id, created)
        await dashboard.refresh()
        return

    # ---------- edit flow ----------
    if action == "ed":
        batch = parts[2]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        await q.answer()
        return await q.edit_message_text("✏️ Which task do you want to edit?",
                                         reply_markup=keyboards.edit_list_kb(batch, parsed))
    if action == "ebk":
        batch = parts[2]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("This batch expired — please resend.", show_alert=True)
        await q.answer()
        return await q.edit_message_text(messages.confirm_card(parsed), parse_mode="HTML",
                                         reply_markup=keyboards.confirm_kb(batch))
    if action == "ei":
        batch, idx = parts[2], int(parts[3])
        parsed = draft.get(batch)
        if not parsed or idx >= len(parsed):
            return await q.answer("Expired — please resend.", show_alert=True)
        await q.answer()
        return await q.edit_message_text(_task_detail(parsed[idx]), parse_mode="HTML",
                                         reply_markup=keyboards.edit_task_kb(batch, idx))
    if action == "et":  # edit title -> ask for typed input
        batch, idx = parts[2], int(parts[3])
        _await_input[q.from_user.id] = {"kind": "title", "batch": batch, "idx": idx}
        await q.answer()
        return await ctx.bot.send_message(q.message.chat_id, "✏️ Type the new title:",
                                          reply_markup=ForceReply(input_field_placeholder="New title"))
    if action == "edt":  # show date options
        batch, idx = parts[2], int(parts[3])
        await q.answer()
        return await q.edit_message_reply_markup(reply_markup=keyboards.edit_date_kb(batch, idx))
    if action == "eds":  # apply date choice
        batch, idx, key = parts[2], int(parts[3]), parts[4]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("Expired — please resend.", show_alert=True)
        if key == "choose":
            _await_input[q.from_user.id] = {"kind": "date_task", "batch": batch, "idx": idx}
            await q.answer()
            return await ctx.bot.send_message(
                q.message.chat_id, "📅 Type a date (e.g. <code>2026-07-15</code>):",
                parse_mode="HTML", reply_markup=ForceReply(input_field_placeholder="e.g. 2026-07-15"))
        when = service.resolve_when(key)
        parsed[idx]["due"] = when.isoformat() if when else ""
        await q.answer("Updated")
        return await q.edit_message_text(messages.confirm_card(parsed), parse_mode="HTML",
                                         reply_markup=keyboards.confirm_kb(batch))
    if action == "ewho":
        batch, idx = parts[2], int(parts[3])
        await q.answer()
        return await q.edit_message_reply_markup(reply_markup=keyboards.edit_who_kb(batch, idx))
    if action == "ews":
        batch, idx, who = parts[2], int(parts[3], ), parts[4]
        parsed = draft.get(batch)
        if not parsed:
            return await q.answer("Expired — please resend.", show_alert=True)
        parsed[idx]["responsible"] = "" if who == "me" else who
        await q.answer("Updated")
        return await q.edit_message_text(messages.confirm_card(parsed), parse_mode="HTML",
                                         reply_markup=keyboards.confirm_kb(batch))

    # ---------- dashboard helpers ----------
    if action == "dash":
        await dashboard.refresh()
        return await q.answer("Refreshed 🍓")
    if action == "hint":
        return await q.answer("Just type your task(s) here and I'll catch them!", show_alert=True)
    if action == "dd":  # one-tap Done from the dashboard (refresh in place)
        res = service.complete(parts[2])
        await dashboard.refresh()
        return await q.answer("Done ✅" if res else "Already done")

    # ---------- settings / setup ----------
    if action == "setup":
        s = {k: repo.setting_or_default(k) for k in (
            oc.SET_DAILY_SUMMARY, oc.SET_WEEKLY_SUMMARY, oc.SET_LEAD_DAYS,
            oc.SET_TIMED_LEAD_MIN, oc.SET_UPCOMING_DAYS,
            oc.SET_GREETING_NAME, oc.SET_PAUSED)}
        await q.answer()
        return await q.message.reply_text(
            messages.settings_text(s), parse_mode="HTML",
            reply_markup=keyboards.settings_kb(s[oc.SET_PAUSED] == "true"))
    if action == "set":
        key = parts[2]
        if key == "pause":
            cur = repo.setting_or_default(oc.SET_PAUSED) == "true"
            repo.set_setting(oc.SET_PAUSED, "false" if cur else "true")
            return await q.answer("Reminders resumed ▶️" if cur else "Reminders paused ⏸")
        prompts = {"daily": "🌅 Type the daily summary time (HH:MM, 24h), e.g. 09:00",
                   "weekly": "🗓 Type weekly summary as DAY HH:MM, e.g. SUN 19:00",
                   "lead": "⏰ Type bill advance-reminder days, e.g. 3",
                   "timed": "🕒 Type timed-task advance reminder in minutes, e.g. 60",
                   "upcoming": "🟡 Type the upcoming window in days, e.g. 3",
                   "name": "🍓 Type the greeting name, e.g. Lesha"}
        if key not in prompts:
            return await q.answer()
        _await_input[q.from_user.id] = {"kind": f"setting:{key}", "batch": ""}
        await q.answer()
        return await ctx.bot.send_message(q.message.chat_id, prompts[key],
                                          reply_markup=ForceReply())

    if action == "mt":  # Manage Today -> actionable cards (no /today needed)
        b = service.build_buckets()
        await q.answer()
        await _send_task_cards(ctx, q.message.chat_id,
                               b[oc.B_OVERDUE] + b[oc.B_DUE_TODAY],
                               "🌸 Nothing overdue or due today!")
        return

    # ---------- Clean Chat ----------
    if action == "clean":
        n = 0
        gid = routing.owner_group_id()
        for t in repo.all_tasks():
            if str(t.get("Status")) in (oc.ST_COMPLETED, oc.ST_CANCELLED, oc.ST_SKIPPED):
                mid = t.get("Source Message ID")
                if mid and await _safe_delete(ctx, gid, mid):
                    repo.update_task(str(t.get("Task ID")), {"Source Message ID": ""})
                    n += 1
        return await q.answer(f"🧹 Cleaned {n} card(s)." if n else "✨ Already tidy!")

    # ---------- task-card actions ----------
    if action in ("dn", "rs", "rx", "sk", "cxt", "cxy", "cxk", "more", "back", "hide", "wt"):
        task_id = parts[2]
        task = repo.get_task(task_id)
        if not task:
            return await q.answer("Task not found.", show_alert=True)
        rec = bool(task.get("Recurrence ID"))
        title = messages.esc(task.get("Title"))
        # Stale-button guard: a finished task can't be changed.
        if str(task.get("Status")) in (oc.ST_COMPLETED, oc.ST_CANCELLED, oc.ST_SKIPPED) and action != "cxk":
            return await q.answer(f"Already {str(task.get('Status')).lower()}.", show_alert=True)

        if action == "more":
            await q.answer()
            return await q.edit_message_reply_markup(reply_markup=keyboards.task_more_kb(task_id, rec))
        if action == "back":
            await q.answer()
            return await q.edit_message_reply_markup(reply_markup=keyboards.task_card_kb(task_id, rec))
        if action == "hide":
            repo.update_task(task_id, {"Source Message ID": ""})
            await q.answer("🫥 Hidden — still on your dashboard.")
            return await _safe_delete(ctx, q.message.chat_id, q.message.message_id)
        if action == "wt":  # park as waiting on someone (from an overdue check-in)
            service.set_waiting(task_id, None)
            repo.update_task(task_id, {"Source Message ID": ""})
            await q.answer("🔵 Parked as waiting.")
            await _close_card(ctx, q, f"🔵 <b>Waiting — {title}</b>")
            await dashboard.refresh()
            return
        if action == "dn":
            res = service.complete(task_id)
            repo.update_task(task_id, {"Source Message ID": ""})
            await q.answer("✅ Done! Dashboard updated." if res else "Already done")
            await _close_card(ctx, q, f"✅ <b>Done — {title}</b>")
            await dashboard.refresh()
            return
        if action == "rs":
            await q.answer()
            return await q.edit_message_reply_markup(reply_markup=keyboards.reschedule_kb(task_id))
        if action == "rx":
            key = parts[3]
            if key == "choose":
                _await_input[q.from_user.id] = {"kind": f"reschedule:{task_id}", "batch": ""}
                await q.answer()
                return await ctx.bot.send_message(
                    q.message.chat_id, "📅 Type the new date (e.g. <code>2026-07-15</code>):",
                    parse_mode="HTML", reply_markup=ForceReply())
            when = service.resolve_when(key)
            if when:
                service.reschedule(task_id, when)
            fresh = repo.get_task(task_id) or task
            await q.answer("📅 Rescheduled to " + messages.fmt_due(
                str(fresh.get("Due Date") or ""), str(fresh.get("Due Time") or "")))
            await q.edit_message_text(
                messages.task_card(fresh, header=f"{messages.cat_emoji(fresh)} <b>RESCHEDULED</b>"),
                parse_mode="HTML", reply_markup=keyboards.task_card_kb(task_id, rec))
            await dashboard.refresh()
            return
        if action == "sk":
            service.skip(task_id)
            repo.update_task(task_id, {"Source Message ID": ""})
            await q.answer("⏭ Skipped. The schedule will continue.")
            await _close_card(ctx, q, f"⏭ <b>Skipped — {title}</b>")
            await dashboard.refresh()
            return
        if action == "cxt":  # ask for confirmation
            await q.answer()
            return await q.edit_message_text(messages.cancel_confirm(task), parse_mode="HTML",
                                             reply_markup=keyboards.cancel_confirm_kb(task_id))
        if action == "cxy":  # confirmed cancel -> card disappears
            service.cancel(task_id)
            repo.update_task(task_id, {"Source Message ID": ""})
            await q.answer("🗑 Task cancelled.")
            await _close_card(ctx, q, f"🗑 <b>Cancelled — {title}</b>")
            await dashboard.refresh()
            return
        if action == "cxk":  # keep -> restore the compact card
            await q.answer("Kept ↩️")
            return await q.edit_message_text(messages.task_card(task), parse_mode="HTML",
                                             reply_markup=keyboards.task_card_kb(task_id, rec))

    await q.answer()


# ============================================================ commands
async def _send_task_cards(ctx, chat_id, tasks, empty_msg="🌸 Nothing here — you're clear!"):
    """Send one actionable card per task (used by Manage Today, /today, /week)."""
    if not tasks:
        return await ctx.bot.send_message(chat_id, empty_msg)
    for t in tasks:
        header = f"{messages.cat_emoji(t)} <b>TO DO</b>"
        await ctx.bot.send_message(
            chat_id, messages.task_card(t, header=header), parse_mode="HTML",
            reply_markup=keyboards.task_card_kb(t["Task ID"], bool(t.get("Recurrence ID"))))


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    b = service.build_buckets()
    await _send_task_cards(ctx, update.effective_chat.id,
                           b[oc.B_OVERDUE] + b[oc.B_DUE_TODAY],
                           "🌸 Nothing overdue or due today!")
    await _safe_delete(ctx, update.effective_chat.id, update.effective_message.message_id)


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    b = service.build_buckets()
    tasks = b[oc.B_OVERDUE] + b[oc.B_DUE_TODAY] + b[oc.B_UPCOMING] + b[oc.B_WAITING]
    await _send_task_cards(ctx, update.effective_chat.id, tasks)
    await _safe_delete(ctx, update.effective_chat.id, update.effective_message.message_id)


async def cmd_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    await dashboard.refresh()
    await _safe_delete(ctx, update.effective_chat.id, update.effective_message.message_id)


async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_ok(update):
        return
    s = {k: repo.setting_or_default(k) for k in (
        oc.SET_DAILY_SUMMARY, oc.SET_WEEKLY_SUMMARY, oc.SET_LEAD_DAYS,
        oc.SET_GREETING_NAME, oc.SET_PAUSED)}
    await update.effective_message.reply_text(
        messages.settings_text(s), parse_mode="HTML",
        reply_markup=keyboards.settings_kb(s[oc.SET_PAUSED] == "true"))
    await _safe_delete(ctx, update.effective_chat.id, update.effective_message.message_id)


def register(application) -> None:
    application.add_handler(CommandHandler("setupowner", cmd_setupowner))
    application.add_handler(CommandHandler("unsetupowner", cmd_unsetupowner))
    application.add_handler(CommandHandler(["owner", "dashboard"], cmd_owner))
    application.add_handler(CommandHandler(["setup", "settings"], cmd_setup))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("week", cmd_week))
    application.add_handler(CallbackQueryHandler(on_owner_callback, pattern=OWNER_CALLBACK_PATTERN))
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, on_owner_text))
