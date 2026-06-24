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

    # 4) Daily summary (covers the PREVIOUS operating date) at configured time.
    summary_time = settings_store.get(constants.SETTING_DAILY_SUMMARY_TIME)  # "00:05"
    if _hhmm(now) == summary_time:
        key = f"summary::{yesterday.isoformat()}"
        if not markers.done(key):
            await summary_service.send_daily_summary(yesterday)
            markers.mark(key)

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
