"""Owner Mode message builders (cute, concise, emoji-led). Pure functions.

All dates everywhere go through fmt_due() so formatting stays identical across
the dashboard, cards, summaries, /today, /week, reschedule + waiting confirms.
"""
from __future__ import annotations

import html
from datetime import datetime

from app import clock
from app.owner import constants as oc


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def cat_emoji(task: dict) -> str:
    return oc.CATEGORY_EMOJI.get(str(task.get("Category") or oc.CAT_GENERAL), "🍓")


def _time12(t: str) -> str:
    try:
        return datetime.strptime(t.strip(), "%H:%M").strftime("%I:%M %p").lstrip("0")
    except Exception:
        return t


def fmt_due(date_iso: str, time: str = "", today_marker: bool = True) -> str:
    """THE shared date formatter.

    'June 24, Wednesday'  ·  '...· Today' if today  ·  '...· 11:00 AM' if timed
    ·  includes the year when it's not the current year.
    """
    if not date_iso:
        return "no deadline"
    try:
        dt = clock.parse_date(str(date_iso))
    except Exception:
        return str(date_iso)
    today = clock.today()
    if dt.year != today.year:
        base = f"{dt.strftime('%B')} {dt.day}, {dt.year}, {dt.strftime('%A')}"
    else:
        base = f"{dt.strftime('%B')} {dt.day}, {dt.strftime('%A')}"
    if time:
        base += " · " + _time12(time)
    elif dt == today and today_marker:
        base += " · Today"
    return base


def task_line(task: dict) -> str:
    if str(task.get("Status")) == oc.ST_WAITING and task.get("Responsible"):
        return f"• {esc(task.get('Responsible'))} — {esc(task.get('Title'))}"
    due = task.get("Due Date")
    suffix = f" — <b>{esc(fmt_due(str(due), str(task.get('Due Time') or '')))}</b>" if due else ""
    return f"• {esc(task.get('Title'))}{suffix}"


# ---------------------------------------------------------- capture confirm
def confirm_card(tasks: list[dict]) -> str:
    n = len(tasks)
    head = f"🍓 <b>I caught {n} task{'s' if n != 1 else ''}</b>\n"
    lines, has_recur = [], False
    for t in tasks:
        emoji = oc.CATEGORY_EMOJI.get(t.get("category", oc.CAT_GENERAL), "🍓")
        due_str = fmt_due(t.get("due", ""), t.get("due_time", "")) if t.get("due") else "no date yet"
        who = f" · 👤 {esc(t['responsible'])}" if t.get("responsible") else ""
        recur = ""
        if t.get("recurrence"):
            from app.owner import recurrence as _rec
            has_recur = True
            recur = f"  🔁 {esc(_rec.describe(t['recurrence']))}"
        lines.append(f"\n{emoji} <b>{esc(t['title'])}</b>{recur}\nDue: {esc(due_str)}{who}")
    foot = "\n\nLook right? You can ✏️ Edit any task before saving."
    if has_recur:
        foot += "\n\n🔁 <i>Recurring tasks will auto-repeat on schedule.</i>"
    return head + "".join(lines) + foot


def nodate_question(count: int) -> str:
    return (f"🗓 <b>{count} task{'s' if count != 1 else ''} ha"
            f"{'ve' if count != 1 else 's'} no date.</b>\nWhen should I schedule "
            f"{'them' if count != 1 else 'it'}?")


# ---------------------------------------------------------------- task cards
def added_header(n: int) -> str:
    return f"🍓 <b>{n} task{'s' if n != 1 else ''} added</b>"


def task_card(task: dict, *, header: str = "🟠 <b>TASK ADDED</b>") -> str:
    lines = [header, "", f"<b>{esc(task.get('Title'))}</b>", ""]
    due = task.get("Due Date")
    lines.append(f"📅 <b>{esc(fmt_due(str(due or ''), ''))}</b>")
    if task.get("Due Time"):
        lines.append(f"🕚 <b>{esc(_time12(str(task['Due Time'])))}</b>")
    if task.get("Responsible"):
        lines.append(f"👤 {esc(task.get('Responsible'))}")
    return "\n".join(lines)


def card_completed(task: dict) -> str:
    return (f"✅ <b>COMPLETED</b>\n\n<b>{esc(task.get('Title'))}</b>\n\n"
            f"Completed: <b>{esc(fmt_due(clock.today().isoformat(), '', today_marker=False))}</b>")


def card_rescheduled(task: dict) -> str:
    return (f"📅 <b>RESCHEDULED</b>\n\n<b>{esc(task.get('Title'))}</b>\n\n"
            f"New date: <b>{esc(fmt_due(str(task.get('Due Date') or ''), str(task.get('Due Time') or '')))}</b>")


def card_skipped(task: dict) -> str:
    return (f"⏭ <b>Skipped this one</b>\n\n<b>{esc(task.get('Title'))}</b>\n\n"
            f"<i>The recurring schedule continues — next one is set.</i>")


def card_cancelled(task: dict) -> str:
    return f"🗑 <b>CANCELLED</b>\n\n<b>{esc(task.get('Title'))}</b>"


def cancel_confirm(task: dict) -> str:
    return f"🗑 <b>Cancel this task?</b>\n\n<b>{esc(task.get('Title'))}</b>"


# ---------------------------------------------------------------- dashboard
def dashboard_text(buckets: dict) -> str:
    out = ["🍓 <b>BOMBI ADMIN — THIS WEEK</b>"]
    order = [oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING, oc.B_WAITING]
    any_active = any(buckets.get(b) for b in order)
    for b in order:
        items = buckets.get(b, [])
        if not items:
            continue
        out.append(f"\n{oc.STATUS_EMOJI[b]} <b>{b}</b>")
        for t in items:
            out.append(task_line(t))
    done = buckets.get(oc.B_COMPLETED, [])
    if done:
        out.append(f"\n✅ <b>COMPLETED THIS WEEK</b> ({len(done)})")
        for t in done[:6]:
            out.append(f"• {esc(t.get('Title'))}")
    if not any_active:
        out.append("\n🌸 You're all clear — nothing active right now. ")
    return "\n".join(out)


# ----------------------------------------------------------------- summaries
def today_summary(greeting: str, buckets: dict, recurring: list[dict] | None = None) -> str:
    """Live 'good morning' message — edits itself as tasks change. Lists every
    unfinished task by priority then nearest due date, plus what's on repeat."""
    o = buckets.get(oc.B_OVERDUE, [])
    d = buckets.get(oc.B_DUE_TODAY, [])
    u = buckets.get(oc.B_UPCOMING, [])
    w = buckets.get(oc.B_WAITING, [])
    done = buckets.get(oc.B_COMPLETED, [])
    out = [f"🍓 <b>GOOD MORNING, {esc(greeting)}!</b>"]

    if not (o or d or u or w):
        out.append("\n🎉 You're all caught up — nothing pending. Enjoy your day!")
    else:
        out.append("\nHere's what's still on your plate:")
        for bucket, items in ((oc.B_OVERDUE, o), (oc.B_DUE_TODAY, d),
                              (oc.B_UPCOMING, u), (oc.B_WAITING, w)):
            if items:
                out.append(f"\n{oc.STATUS_EMOJI[bucket]} <b>{bucket}</b>")
                out.extend(task_line(t) for t in items)

    if recurring:
        out.append("\n🔁 <b>ON REPEAT</b>")
        for r in recurring[:8]:
            nxt = f" — next {esc(r['next'])}" if r.get("next") else ""
            out.append(f"• {esc(r['title'])} ({esc(r['rule'])}){nxt}")

    if done:
        out.append(f"\n✅ <b>{len(done)} done this week</b>")
    return "\n".join(out)


def daily_summary(greeting: str, buckets: dict) -> str:
    o = len(buckets.get(oc.B_OVERDUE, []))
    d = len(buckets.get(oc.B_DUE_TODAY, []))
    u = len(buckets.get(oc.B_UPCOMING, []))
    w = len(buckets.get(oc.B_WAITING, []))
    if o == 0 and d == 0:
        nxt = ""
        up = buckets.get(oc.B_UPCOMING, [])
        if up:
            nxt = (f"\n\nYour next task is <b>{esc(up[0].get('Title'))}</b> "
                   f"({fmt_due(str(up[0].get('Due Date') or ''), str(up[0].get('Due Time') or ''))}).")
        return f"🌸 <b>YOU'RE CLEAR TODAY, {esc(greeting)}!</b>\n\nNothing overdue or due today.{nxt}"
    lines = [f"🍓 <b>GOOD MORNING, {esc(greeting)}!</b>\n", "Here's what needs you today:\n",
             f"🔴 <b>{o} overdue</b>", f"🟠 <b>{d} due today</b>",
             f"🟡 <b>{u} coming up</b>", f"🔵 <b>{w} waiting on someone</b>"]
    top = (buckets.get(oc.B_OVERDUE, []) + buckets.get(oc.B_DUE_TODAY, []))[:3]
    if top:
        lines.append("\n<b>Top priorities</b>")
        for i, t in enumerate(top, 1):
            lines.append(f"{i}. {esc(t.get('Title'))}")
    return "\n".join(lines)


def weekly_summary(stats: dict, upcoming: list[dict]) -> str:
    lines = [
        "🍓 <b>YOUR WEEKLY ADMIN RESET</b>\n",
        f"✅ <b>Completed:</b> {stats.get('completed', 0)}",
        f"🟠 <b>Still pending:</b> {stats.get('pending', 0)}",
        f"🔴 <b>Overdue:</b> {stats.get('overdue', 0)}",
        f"🔵 <b>Waiting on others:</b> {stats.get('waiting', 0)}",
    ]
    if upcoming:
        lines.append("\n<b>Next week's key dates</b>")
        for t in upcoming[:6]:
            lines.append(f"• {esc(t.get('Title'))} — {fmt_due(str(t.get('Due Date') or ''), str(t.get('Due Time') or ''))}")
    return "\n".join(lines)


def settings_text(s: dict) -> str:
    paused = "ON ⏸" if str(s.get(oc.SET_PAUSED)) == "true" else "off"
    return (
        "⚙️ <b>Owner Settings</b>\n\n"
        f"🌅 Daily summary: <b>{esc(s.get(oc.SET_DAILY_SUMMARY))}</b>\n"
        f"🗓 Weekly summary: <b>{esc(s.get(oc.SET_WEEKLY_SUMMARY))}</b>\n"
        f"🕒 Timed-task advance: <b>{esc(s.get(oc.SET_TIMED_LEAD_MIN))} min</b>\n"
        f"🟡 Upcoming window: <b>{esc(s.get(oc.SET_UPCOMING_DAYS))} day(s)</b>\n"
        f"⏰ Bill advance reminder: <b>{esc(s.get(oc.SET_LEAD_DAYS))} day(s)</b>\n"
        f"🍓 Greeting name: <b>{esc(s.get(oc.SET_GREETING_NAME))}</b>\n"
        f"🔕 Reminders paused: <b>{paused}</b>\n\nTap a setting to change it."
    )


def nudge(task: dict) -> str:
    return (f"🍓 <b>Quick check-in</b>\n\n{oc.STATUS_EMOJI[oc.B_OVERDUE]} "
            f"<b>{esc(task.get('Title'))}</b> is now overdue.\n\n"
            "Finish it, give it a realistic new date, or park it as waiting.")


def _humanize_lead(minutes: int) -> str:
    if minutes % 60 == 0:
        h = minutes // 60
        return "IN 1 HOUR" if h == 1 else f"IN {h} HOURS"
    return f"IN {minutes} MIN"


def reminder_card(task: dict, kind: str, lead_min: int = 60) -> str:
    """Timed-task reminder. kind 'soon' = advance warning, 'due' = at due time."""
    label = _humanize_lead(lead_min) if kind == "soon" else "DUE NOW"
    return task_card(task, header=f"{cat_emoji(task)} <b>COMING UP {label}</b>"
                     if kind == "soon" else f"{cat_emoji(task)} <b>{label}</b>")


def bill_due_soon(task: dict) -> str:
    return (f"💡 <b>{esc(task.get('Title'))} — DUE SOON</b>\n\n"
            f"Due: <b>{fmt_due(str(task.get('Due Date') or ''), str(task.get('Due Time') or ''))}</b>")
