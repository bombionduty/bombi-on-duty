"""
The single per-minute processor (spec section 43).

Every minute we:
  1. release any due tasks for today,
  2. for each open task: send due reminders, escalate, apply cutoff,
  3. fire the daily summary, weekly schedule reminder, weekly report,
  4. run the daily schedule pre-check.

Each timed action is guarded by the markers ledger, so running every minute is
safe and nothing fires twice — even after a restart.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from app import clock, constants
from app.repositories import task_repo
from app.repositories.misc_repo import settings_store
from app.services import (
    markers,
    ops_service,
    report_service,
    schedule_service,
    summary_service,
    task_service,
)

log = logging.getLogger(__name__)


def _hhmm(now=None) -> str:
    now = now or clock.now()
    return now.strftime("%H:%M")


async def tick() -> None:
    """Called once per minute by APScheduler."""
    try:
        await _tick_inner()
    except Exception:  # never let the scheduler die
        log.exception("Scheduler tick failed")


async def _tick_inner() -> None:
    now = clock.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    # 1) Daily pre-check (once/day at 06:00 Manila).
    if _hhmm(now) == "06:00":
        key = f"precheck::{today.isoformat()}"
        if not markers.done(key):
            await schedule_service.run_precheck(today)
            markers.mark(key)

    # 2) Release due tasks for today.
    await task_service.release_due_tasks(today)

    # 3) Per-task lifecycle for any still-open task (today + yesterday in case a
    #    cutoff crosses midnight).
    open_tasks = [
        t for t in task_repo.all_unresolved()
        if str(t.get("Date")) in (today.isoformat(), yesterday.isoformat())
        and t.get("Original Submission Status") == constants.SUB_PENDING
    ]
    for t in open_tasks:
        await ops_service.send_due_reminders(t)
        await ops_service.escalate_if_due(t)
        await ops_service.cutoff_if_due(t)

    # 3b) Staff assignment reminders (ad-hoc tasks): due-time + every-2h nudges.
    await _assignment_reminders(now)

    # 4) Daily summary (covers the PREVIOUS operating date) at configured time.
    summary_time = settings_store.get(constants.SETTING_DAILY_SUMMARY_TIME)  # "00:05"
    if _hhmm(now) == summary_time:
        key = f"summary::{yesterday.isoformat()}"
        if not markers.done(key):
            await summary_service.send_daily_summary(yesterday)
            markers.mark(key)

    # 4b) "Good morning" group recap of the previous day (default 11:00).
    gm_time = settings_store.get(constants.SETTING_GOOD_MORNING_TIME)
    if _hhmm(now) == gm_time:
        key = f"goodmorning::{today.isoformat()}"
        if not markers.done(key):
            await summary_service.send_good_morning(yesterday)
            markers.mark(key)

    # 4c) Daily Owner Brief (Zite inventory) — trigger the external report.
    await _owner_brief(now)

    # 5) Weekly schedule reminder (e.g. "SUN 18:00").
    await _maybe_weekly(now, settings_store.get(constants.SETTING_WEEKLY_SCHEDULE_REMINDER),
                        "weekly_sched", schedule_service.send_weekly_schedule_reminder)

    # 6) Weekly accountability report (e.g. "MON 09:00").
    await _maybe_weekly(now, settings_store.get(constants.SETTING_WEEKLY_REPORT_DAY),
                        "weekly_report", report_service.send_weekly_report)

    # 7) Owner Mode tick — runs LAST and in its OWN try/except so any Owner Mode
    #    error can never affect the staff steps above (which already completed).
    try:
        from app.owner import scheduler as owner_scheduler
        await owner_scheduler.owner_tick()
    except Exception:
        log.exception("Owner Mode tick failed (staff scheduler unaffected)")


async def _assignment_reminders(now) -> None:
    """Send due-time + periodic nudges for open staff assignments. Restart-safe
    and duplicate-safe via the marker ledger (keys embed the assignment + slot)."""
    from app.config import get_settings
    from app.services import assignment_service
    from app.telegram import notify

    group_id = get_settings().staff_group_chat_id

    # Post assigned-task cards 15 min before their due time (not at creation).
    for a in assignment_service.due_to_post(now):
        await assignment_service.post_card(a)

    for ev in assignment_service.reminders_due(now):
        if markers.done(ev["key"]):
            continue
        a = ev["a"]
        header = ("⏰ <b>DUE NOW</b>" if ev["kind"] == "due"
                  else "🔔 <b>REMINDER — still open</b>")
        sent = await notify.send_message(
            group_id, assignment_service.card(a, header=header),
            reply_markup=assignment_service.done_markup(a))
        # Track so a photo replying to a reminder also matches this assignment.
        if sent:
            from app.repositories import reminder_repo
            reminder_repo.log_reminder(a["Assignment ID"], group_id, sent.message_id)
        markers.mark(ev["key"])


async def _owner_brief(now) -> None:
    """Trigger the Zite Daily Owner Brief once/day (default 09:00 Manila).
    Isolated + marker-guarded so it never affects the Berry Bomb steps."""
    from app.config import get_settings
    s = get_settings()
    if not s.owner_brief_configured or _hhmm(now) != s.owner_brief_time:
        return
    key = f"owner_brief::{now.date().isoformat()}"
    if markers.done(key):
        return
    try:
        from app.services import owner_brief
        await owner_brief.run_brief(send_email=True, deliver_telegram=False)
    except Exception:
        log.exception("Owner Brief tick failed (other steps unaffected)")
    markers.mark(key)  # mark regardless so we don't re-fire every minute


async def _maybe_weekly(now, spec: str, name: str, coro) -> None:
    """spec like 'SUN 18:00'."""
    try:
        day, hhmm = spec.split()
    except (ValueError, AttributeError):
        return
    if now.strftime("%a").upper() != day.upper() or _hhmm(now) != hhmm:
        return
    key = f"{name}::{now.date().isoformat()}"
    if markers.done(key):
        return
    await coro()
    markers.mark(key)
