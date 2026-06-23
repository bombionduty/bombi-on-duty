"""
Telegram command + callback handlers (spec sections 36, 37, 38).

Admin commands mirror the Admin Mini App for power users. Staff get /note,
/issue and announcement acknowledgement. Everything that changes data checks the
caller's role first.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from app import clock, constants
from app.config import get_settings
from app.repositories import schedule_repo, staff_repo, task_repo
from app.repositories.misc_repo import audit, notes, reviews
from app.services import (
    announcement_service,
    evidence_delivery,
    report_service,
    summary_service,
    task_service,
)
from app.telegram import keyboards, notify

log = logging.getLogger(__name__)


def _uid(update: Update) -> int:
    return update.effective_user.id


def esc_name(s) -> str:
    import html
    return html.escape(str(s)) if s is not None else ""


def _is_admin(update: Update) -> bool:
    return staff_repo.is_admin(_uid(update))


async def _deny(update: Update) -> None:
    await update.effective_message.reply_text("This command is for the admin only.")


async def capture_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs on every update: keep a known staff's @username fresh from any
    interaction (button tap, command, group message) — no extra step needed."""
    u = update.effective_user
    if not u or not u.username or staff_repo.is_admin(u.id):
        return
    s = staff_repo.get_by_telegram_id(u.id)
    if s and str(s.get("Telegram Username") or "") != u.username:
        try:
            staff_repo.update_staff(str(s["Staff ID"]), {"Telegram Username": u.username})
        except Exception:
            pass


# ============================================================ basic commands
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    user = update.effective_user
    username = user.username or ""
    full_name = user.full_name or ""
    staff_repo.mark_private_started(uid)

    if staff_repo.is_admin(uid):
        await update.message.reply_html(
            "👋 Welcome, Admin! Tap below to open Admin Controls.\n\n"
            f"🆔 Your Telegram ID: <code>{uid}</code>",
            reply_markup=keyboards.admin_controls_button(),
        )
        return

    who = staff_repo.get_by_telegram_id(uid)
    uname_line = f"\n🔗 Username: @{username}" if username else ""

    if who:
        # Auto-save their username (the admin usually can't see it otherwise).
        if username and str(who.get("Telegram Username") or "") != username:
            staff_repo.update_staff(who["Staff ID"], {"Telegram Username": username})
        await update.message.reply_html(
            f"👋 Hi {esc_name(who.get('Staff Name'))}! You're connected to "
            "Berry Bomb Daily Ops. 📋\n\nYou'll get your checklists in the "
            "staff group. Tap <b>/mytask</b> anytime to reopen your current "
            "checklist, <b>/note</b> to add a note, or <b>/issue</b> to flag a problem.\n\n"
            f"🆔 Your Telegram ID: <code>{uid}</code>"
        )
    else:
        await update.message.reply_html(
            "👋 Hi! To be added to Berry Bomb Daily Ops, your admin will register "
            "you. I've already sent them your details. 🙌\n\n"
            f"🆔 <code>{uid}</code>{uname_line}"
        )

    # Always notify the admin with the person's ID + username automatically.
    settings = get_settings()
    if who:
        note = (
            f"✅ <b>{esc_name(who.get('Staff Name'))}</b> activated the bot.\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"🔗 Username: {('@'+username) if username else '—'} (saved automatically)"
        )
    else:
        note = (
            "👤 <b>Someone activated the bot</b> (not yet in your staff list):\n"
            f"📛 Name: {esc_name(full_name)}\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"🔗 Username: {('@'+username) if username else '—'}\n\n"
            "Add them in <b>Admin → Staff → Add staff</b> (paste the ID + username above)."
        )
    await notify.send_message(settings.admin_telegram_user_id, note)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_admin(update):
        await update.message.reply_text(
            "Admin commands:\n"
            "/schedule, /opener <name> <today|tomorrow|YYYY-MM-DD>,\n"
            "/closer <name> <when>, /closed <when>, /open <when>, /copyweek,\n"
            "/staff, /addstaff <name> <tgid>, /removestaff <name>,\n"
            "/summary <today|YYYY-MM-DD>, /announce <msg>,\n"
            "/additem <opening|handover|closing> <name>, /checklist <type>,\n"
            "/test <opening|handover|closing|summary>"
        )
    else:
        await update.message.reply_text("Use /note <msg> or /issue <msg>.")


# ================================================================ staff notes
async def cmd_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /note <your message>")
        return
    sender = staff_repo.get_by_telegram_id(_uid(update)) or {
        "Staff Name": update.effective_user.full_name,
        "Telegram User ID": _uid(update),
    }
    notes.add(sender, text)
    await update.message.reply_text("Noted. Added to today's ops notes.")


async def cmd_mytask(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-open the staff member's current checklist(s) if they closed the app."""
    uid = _uid(update)
    found = False
    for t in task_repo.for_date(clock.today()):
        if str(t.get("Assigned Telegram User ID")) != str(uid):
            continue
        if not task_service.is_openable(t):
            continue
        found = True
        await update.effective_message.reply_text(
            f"{t['Checklist Type']} — tap to open:",
            reply_markup=keyboards.open_checklist_button(t["Task ID"]),
        )
    if not found:
        await update.effective_message.reply_text(
            "You have no open checklists right now."
        )


# ============================================================== admin: schedule
def _parse_when(token: str):
    token = token.lower()
    if token == "today":
        return clock.today()
    if token == "tomorrow":
        return clock.today().fromordinal(clock.today().toordinal() + 1)
    return clock.parse_date(token)


async def _assign(update, role: str) -> None:
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    if len(parts) < 3:
        return await update.message.reply_text(f"Usage: /{role} <name> <today|tomorrow|YYYY-MM-DD>")
    name, when = parts[1], parts[2]
    staff = staff_repo.find_active_by_name(name)
    if not staff:
        return await update.message.reply_text(f"No active staff named '{name}'.")
    d = _parse_when(when)
    if role == "opener":
        schedule_repo.upsert(d, opener_staff_id=staff["Staff ID"])
    else:
        schedule_repo.upsert(d, closer_staff_id=staff["Staff ID"])
    audit.log(_uid(update), "Admin", constants.ROLE_ADMIN, f"set_{role}",
              "Schedule", d.isoformat(), new_value=staff["Staff ID"])
    await update.message.reply_text(f"{role.title()} for {d.isoformat()} set to {staff['Staff Name']}.")


async def cmd_opener(update, ctx): await _assign(update, "opener")
async def cmd_closer(update, ctx): await _assign(update, "closer")


async def cmd_closed(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    d = _parse_when(parts[1]) if len(parts) > 1 else clock.today()
    schedule_repo.set_closed(d, True)
    await update.message.reply_text(f"{d.isoformat()} marked CLOSED.")


async def cmd_open(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    d = _parse_when(parts[1]) if len(parts) > 1 else clock.today()
    schedule_repo.set_closed(d, False)
    await update.message.reply_text(f"{d.isoformat()} marked OPEN.")


async def cmd_schedule(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    rows = schedule_repo.week_rows(clock.today(), 7)
    lines = ["<b>This week</b>"]
    for r in rows:
        lines.append(f"{r['Date']} ({r.get('Day')}): {r.get('Status') or '—'} | "
                     f"O: {r.get('Opener Name') or '—'} | C: {r.get('Closer Name') or '—'}")
    await update.message.reply_html("\n".join(lines))


async def cmd_copyweek(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    today = clock.today()
    res = schedule_repo.copy_week(today, today.fromordinal(today.toordinal() + 7))
    await update.message.reply_text(
        f"Copied: {len(res['copied'])} day(s). Skipped (already had data): "
        f"{len(res['skipped'])}.\nUse the Admin Mini App to overwrite specific days."
    )


# =============================================================== admin: staff
async def cmd_staff(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    from app.repositories.base import as_bool
    lines = ["👥 <b>Staff directory</b>\n"]
    for s in staff_repo.all_staff():
        active = "✅" if as_bool(s.get("Active")) else "💤"
        uname = s.get("Telegram Username")
        uname_str = f"@{uname}" if uname else "—"
        started = "✅" if as_bool(s.get("Private Bot Started")) else "⚠️ not started"
        lines.append(
            f"{active} <b>{esc_name(s.get('Staff Name'))}</b> · {esc_name(s.get('Role'))}\n"
            f"   🆔 <code>{s.get('Telegram User ID') or '—'}</code>\n"
            f"   🔗 {uname_str}   ·   bot: {started}"
        )
    dupes = staff_repo.duplicate_active_telegram_ids()
    if dupes and not get_settings().test_mode:
        lines.append(f"\n⚠️ Duplicate active Telegram IDs: {', '.join(dupes)}")
    lines.append("\n<i>Staff get their own ID/username by tapping Start in the bot.</i>")
    await update.message.reply_html("\n".join(lines))


async def cmd_addstaff(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    if len(parts) < 3:
        return await update.message.reply_text("Usage: /addstaff <name> <telegram_user_id>")
    name, tgid = parts[1], parts[2]
    staff_repo.add_staff(name, tgid)
    await update.message.reply_text(f"Added staff {name} ({tgid}).")


async def cmd_removestaff(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    name = update.message.text.partition(" ")[2].strip()
    s = staff_repo.find_active_by_name(name)
    if not s:
        return await update.message.reply_text(f"No active staff named '{name}'.")
    staff_repo.deactivate(s["Staff ID"])
    await update.message.reply_text(f"{name} set inactive (record preserved).")


# ============================================================= admin: content
async def cmd_summary(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    d = clock.today() if (len(parts) < 2 or parts[1] == "today") else clock.parse_date(parts[1])
    await summary_service.send_daily_summary(d)


async def cmd_announce(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        return await update.message.reply_text("Usage: /announce <message>")
    await announcement_service.post_announcement(msg, posted_by=str(_uid(update)))
    await update.message.reply_text("Announcement posted to the staff group.")


async def cmd_additem(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await update.message.reply_text("Usage: /additem <opening|handover|closing> <item name>")
    mapping = {"opening": constants.CHECK_OPENING, "handover": constants.CHECK_HANDOVER,
               "closing": constants.CHECK_CLOSING}
    ct = mapping.get(parts[1].lower())
    if not ct:
        return await update.message.reply_text("Type must be opening, handover, or closing.")
    from app.repositories import checklist_repo
    checklist_repo.add_item(ct, parts[2], constants.ITEM_ATTESTATION,
                            effective_from=clock.today().isoformat(), created_by=str(_uid(update)))
    await update.message.reply_text(
        f"Added attestation item to {ct} (effective today). "
        "Use the Admin Mini App to set a proof type/required flag."
    )


async def cmd_checklist(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    mapping = {"opening": constants.CHECK_OPENING, "handover": constants.CHECK_HANDOVER,
               "closing": constants.CHECK_CLOSING}
    ct = mapping.get(parts[1].lower()) if len(parts) > 1 else None
    if not ct:
        return await update.message.reply_text("Usage: /checklist <opening|handover|closing>")
    from app.repositories import checklist_repo
    items = checklist_repo.all_items(ct)
    lines = [f"<b>{ct}</b>"]
    for it in items:
        flag = "" if str(it.get("Active")).lower() in ("true", "1", "yes") else " (inactive)"
        lines.append(f"• {it.get('Item Name')} [{it.get('Item Type')}]{flag}")
    await update.message.reply_html("\n".join(lines))


# ================================================================ admin: test
async def cmd_test(update, ctx):
    if not _is_admin(update):
        return await _deny(update)
    parts = update.message.text.split()
    what = parts[1].lower() if len(parts) > 1 else ""
    if what == "summary":
        await summary_service.send_daily_summary(clock.today())
        return await update.message.reply_text("Test summary sent.")
    if what in ("opening", "handover", "closing"):
        # Force-release today's tasks (timing permitting) and report.
        released = await task_service.release_due_tasks(clock.today())
        await update.message.reply_text(
            f"Released {len(released)} task(s) for today. "
            "If nothing released, the release time has not arrived or staff are unassigned."
        )
        return
    await update.message.reply_text("Usage: /test <opening|handover|closing|summary>")


# ============================================================ callback queries
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id

    if data.startswith("ack:"):
        ann_id = data.split(":", 1)[1]
        from app.repositories.misc_repo import announcements
        staff = staff_repo.get_by_telegram_id(uid) or {
            "Staff Name": q.from_user.full_name, "Telegram User ID": uid}
        announcements.acknowledge(ann_id, staff)
        return await q.answer("Noted ✅")

    if data.startswith("sendev:"):
        if not staff_repo.is_admin(uid):
            return await q.answer("Admin only.", show_alert=True)
        _, scope, date_iso = data.split(":", 2)
        await q.answer("Sending evidence…")
        ct = None if scope == "all" else scope
        n = await evidence_delivery.send_evidence(date_iso, ct)
        return await notify.send_message(uid, f"Sent {n} evidence file(s).")

    if data.startswith("rev:"):
        _, action, review_id = data.split(":", 2)
        if action == "ok":
            reviews.resolve(review_id, uid, "Looks Complete")
            return await q.answer("Marked reviewed ✅")
        if action == "follow":
            reviews.resolve(review_id, uid, "Follow-Up Needed")
            return await q.answer("Flagged for follow-up")
        if action == "view":
            rv = reviews.get(review_id)
            if rv:
                await evidence_delivery.send_evidence(
                    str(task_repo.get(rv["Task ID"]).get("Date")),
                    task_repo.get(rv["Task ID"]).get("Checklist Type"))
            return await q.answer("Sending evidence…")

    if data.startswith("oic:"):
        _, action, task_id = data.split(":", 2)
        task = task_repo.get(task_id)
        if not task:
            return await q.answer("Task not found.", show_alert=True)
        if action == "view":
            return await q.answer(
                f"{task['Checklist Type']} — {task.get('Assigned Staff Name')} — "
                f"{task.get('Original Submission Status')}", show_alert=True)
        if action == "msg":
            await notify.send_message(
                task.get("Assigned Telegram User ID"),
                f"Reminder from the Store OIC: please complete your "
                f"{task['Checklist Type']}.")
            return await q.answer("Message sent to staff.")
    await q.answer()


def register(application) -> None:
    h = application.add_handler
    # Group 1 runs alongside the main handlers; passively refreshes usernames.
    h(TypeHandler(Update, capture_user), group=1)
    h(CommandHandler("start", cmd_start))
    h(CommandHandler("help", cmd_help))
    h(CommandHandler(["note", "issue"], cmd_note))
    h(CommandHandler(["mytask", "checklist_open"], cmd_mytask))
    h(CommandHandler("schedule", cmd_schedule))
    h(CommandHandler("opener", cmd_opener))
    h(CommandHandler("closer", cmd_closer))
    h(CommandHandler("closed", cmd_closed))
    h(CommandHandler("open", cmd_open))
    h(CommandHandler("copyweek", cmd_copyweek))
    h(CommandHandler(["staff", "ids", "staffids"], cmd_staff))
    h(CommandHandler("addstaff", cmd_addstaff))
    h(CommandHandler("removestaff", cmd_removestaff))
    h(CommandHandler("summary", cmd_summary))
    h(CommandHandler("announce", cmd_announce))
    h(CommandHandler("additem", cmd_additem))
    h(CommandHandler("checklist", cmd_checklist))
    h(CommandHandler("test", cmd_test))
    h(CallbackQueryHandler(on_callback))
