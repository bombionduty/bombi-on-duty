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


async def _safe(name: str, coro) -> None:
    """Run a scheduler step; log + swallow any error so ONE failing step (or one
    bad record) can never abort the rest of the tick."""
    try:
        await coro
    except Exception:
        log.exception("Scheduler step %r failed", name)


def _due_once(now, hhmm: str, key: str, window_min: int = 30) -> bool:
    """True if we're within `window_min` AFTER the target time and this key hasn't
    fired today. The window (vs an exact-minute match) means a bot restart around
    the target minute — e.g. during a deploy — won't skip the job for the day."""
    try:
        target = clock.combine(now.date(), clock.parse_time(str(hhmm)))
    except Exception:
        return False
    return target <= now < target + timedelta(minutes=window_min) and not markers.done(key)


async def _tick_inner() -> None:
    now = clock.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    # 1) Daily pre-check (06:00 Manila).
    if _due_once(now, "06:00", f"precheck::{today.isoformat()}"):
        await _safe("precheck", schedule_service.run_precheck(today))
        markers.mark(f"precheck::{today.isoformat()}")

    # 2) Release due tasks for today.
    await _safe("release", task_service.release_due_tasks(today))

    # 3) Per-task lifecycle for any still-open task (today + yesterday in case a
    #    cutoff crosses midnight). Each task is isolated so one bad row can't stop
    #    the others — or anything later in the tick.
    try:
        open_tasks = [
            t for t in task_repo.all_unresolved()
            if str(t.get("Date")) in (today.isoformat(), yesterday.isoformat())
            and str(t.get("Original Submission Status") or "") in ("", constants.SUB_PENDING)
        ]
    except Exception:
        log.exception("Could not list open tasks")
        open_tasks = []
    for t in open_tasks:
        await _safe(f"ops:{t.get('Task ID')}", _process_task(t))

    # 3b–3d) Ad-hoc assignment reminders, weekly checklists, shift reminders.
    await _safe("assignment_reminders", _assignment_reminders(now))
    await _safe("weekly", _weekly_accountability(now, today))
    await _safe("shift_reminders", _shift_reminders(now))

    # 4) Daily summary (covers the PREVIOUS operating date).
    summary_time = settings_store.get(constants.SETTING_DAILY_SUMMARY_TIME)  # "00:05"
    if _due_once(now, summary_time, f"summary::{yesterday.isoformat()}"):
        await _safe("daily_summary", summary_service.send_daily_summary(yesterday))
        markers.mark(f"summary::{yesterday.isoformat()}")

    # 4b) "Good morning" group recap of the previous day (default 11:00).
    gm_time = settings_store.get(constants.SETTING_GOOD_MORNING_TIME)
    if _due_once(now, gm_time, f"goodmorning::{today.isoformat()}"):
        await _safe("good_morning", summary_service.send_good_morning(yesterday))
        markers.mark(f"goodmorning::{today.isoformat()}")

    # 4c) Daily Owner Brief (Zite inventory).
    await _safe("owner_brief", _owner_brief(now))

    # 4d) Nightly evidence cleanup (03:30).
    if _due_once(now, "03:30", f"evidence_purge::{today.isoformat()}"):
        from app.services import evidence_service
        days = settings_store.get_int(constants.SETTING_EVIDENCE_RETENTION_DAYS)
        await _safe("evidence_purge", _async(evidence_service.purge_old, days))
        markers.mark(f"evidence_purge::{today.isoformat()}")

    # 4e) Daily low-disk warning (07:00).
    if _due_once(now, "07:00", f"diskcheck::{today.isoformat()}"):
        await _safe("diskcheck", _disk_warn())
        markers.mark(f"diskcheck::{today.isoformat()}")

    # 5) Weekly schedule reminder (e.g. "SUN 18:00").
    await _safe("weekly_sched", _maybe_weekly(
        now, settings_store.get(constants.SETTING_WEEKLY_SCHEDULE_REMINDER),
        "weekly_sched", schedule_service.send_weekly_schedule_reminder))

    # 6) Weekly accountability report (e.g. "MON 09:00").
    await _safe("weekly_report", _maybe_weekly(
        now, settings_store.get(constants.SETTING_WEEKLY_REPORT_DAY),
        "weekly_report", report_service.send_weekly_report))

    # 7) Owner Mode tick — runs LAST and in its OWN try/except so any Owner Mode
    #    error can never affect the staff steps above (which already completed).
    try:
        from app.owner import scheduler as owner_scheduler
        await owner_scheduler.owner_tick()
    except Exception:
        log.exception("Owner Mode tick failed (staff scheduler unaffected)")


async def _process_task(t: dict) -> None:
    """Reminders + escalation + cutoff for one open task."""
    await ops_service.send_due_reminders(t)
    await ops_service.escalate_if_due(t)
    await ops_service.cutoff_if_due(t)


async def _async(fn, *args):
    """Await a synchronous function so it can run under _safe()."""
    fn(*args)


async def _disk_warn() -> None:
    from app.config import get_settings
    from app.services import system_service
    r = system_service.disk_report()
    if r["percent"] >= system_service.WARN_PERCENT:
        await notify.send_message(get_settings().admin_telegram_user_id,
                                  system_service.format_report(r))


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


async def _weekly_accountability(now, today) -> None:
    """Drive the weekly accountability checklists: ensure this week's instances
    exist, post each at its time, send reminders, and flag missed cutoffs.
    Restart-safe + duplicate-safe via the marker ledger."""
    from app.config import get_settings
    from app.repositories import reminder_repo
    from app.services import weekly_service
    from app.telegram import notify

    group_id = get_settings().staff_group_chat_id

    # Generate missing occurrences for the current week every tick (idempotent:
    # it only adds an occurrence that doesn't exist yet). Running it every minute
    # — not once/day — means a weekly task created mid-day still gets its card in
    # time to post, instead of waiting until the next day's generation.
    weekly_service.ensure_instances(today)

    # Heal any 'needs verifying' card for a task that's now single-photo (so an
    # already-posted Step-2 message flips to done instead of confusing staff).
    await weekly_service.reconcile_single_step()

    # Post each occurrence's card at its time.
    for inst in weekly_service.due_to_post(now):
        await weekly_service.post_card(inst)

    # Reminders while still open.
    for ev in weekly_service.reminders_due(now):
        if markers.done(ev["key"]):
            continue
        inst = ev["inst"]
        sent = await notify.send_message(
            group_id, weekly_service.card(inst, header="🔔 <b>WEEKLY CHECKLIST — reminder</b>"))
        if sent:
            reminder_repo.log_reminder(inst["Instance ID"], group_id, sent.message_id)
        markers.mark(ev["key"])

    # Cutoff sweep (marks Missing + alerts the OIC; the status change itself is
    # the idempotency guard — a Missing instance is no longer "open").
    await weekly_service.cutoff_if_due(now)


async def _shift_reminders(now) -> None:
    """Fire any due shift-reminder slots (marker-guarded so each fires once)."""
    from app.services import shift_reminder_service
    for ev in shift_reminder_service.due(now):
        if markers.done(ev["key"]):
            continue
        try:
            await shift_reminder_service.fire(ev["reminder"], ev["slot"], now.date())
        except Exception:
            log.exception("Shift reminder failed: %s", ev.get("key"))
        markers.mark(ev["key"])


async def _owner_brief(now) -> None:
    """Daily Owner Brief trigger (default 09:00 Manila). Mode-driven:
      auto   -> call the Zite endpoint over HTTP (needs owner_brief_configured)
      manual -> post a reminder to tap Zite's in-app button (interim workaround)
      off    -> do nothing
    Isolated + marker-guarded so it never affects the Berry Bomb steps."""
    from app.config import get_settings
    s = get_settings()
    if _hhmm(now) != s.owner_brief_time:
        return
    mode = (s.owner_brief_mode or "auto").lower()
    if mode == "off":
        return
    if mode == "auto" and not s.owner_brief_configured:
        return  # not set up yet
    key = f"owner_brief::{now.date().isoformat()}"
    if markers.done(key):
        return
    try:
        from app.services import owner_brief
        if mode == "manual":
            await owner_brief.post_reminder()
        else:
            await owner_brief.run_brief(send_email=True, deliver_telegram=False)
    except Exception:
        log.exception("Owner Brief tick failed (other steps unaffected)")
    markers.mark(key)  # mark regardless so we don't re-fire every minute


async def _maybe_weekly(now, spec: str, name: str, coro) -> None:
    """spec like 'SUN 18:00'. Window-tolerant (survives a restart near the time)."""
    try:
        day, hhmm = spec.split()
    except (ValueError, AttributeError):
        return
    if now.strftime("%a").upper() != day.upper():
        return
    key = f"{name}::{now.date().isoformat()}"
    if _due_once(now, hhmm, key):
        await coro()
        markers.mark(key)
