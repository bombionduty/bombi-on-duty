"""Owner Mode business logic: create tasks, status changes, bucketing."""
from __future__ import annotations

from datetime import date, timedelta

from app import clock
from app.owner import constants as oc
from app.owner import repo


# ----------------------------------------------------------- date resolving
def _next_weekday(target: int, allow_today: bool = False) -> date:
    d = clock.today()
    delta = (target - d.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return d + timedelta(days=delta)


def resolve_when(key: str) -> date | None:
    today = clock.today()
    return {
        "today": today,
        "tom": today + timedelta(days=1),
        "2d": today + timedelta(days=2),
        "wknd": _next_weekday(5, allow_today=True),   # Saturday
        "week": _next_weekday(6, allow_today=True),   # end of this week (Sun)
        "next": _next_weekday(0, allow_today=False),  # next Monday
        "none": None,
    }.get(key, None)


# ------------------------------------------------------------------ create
def create_from_parsed(parsed: list[dict], source_msg_id: str = "") -> list[dict]:
    created = []
    for p in parsed:
        # Phase 1 has no recurrence engine: save a ONE-TIME task and just note the
        # intent (no functional recurrence is stored, so nothing silently dies).
        note = ""
        if p.get("recurrence"):
            note = f"(said '{p['recurrence']}' — auto-repeat lands in Phase 2)"
        created.append(repo.add_task(
            p["title"],
            due_date=p.get("due", ""),
            due_time=p.get("due_time", ""),
            category=p.get("category", oc.CAT_GENERAL),
            responsible=p.get("responsible", ""),
            status=oc.ST_OPEN,
            note=note,
            source_message_id=source_msg_id,
        ))
    return created


# ----------------------------------------------------------------- actions
def complete(task_id: str) -> dict | None:
    t = repo.get_task(task_id)
    if not t or str(t.get("Status")) == oc.ST_COMPLETED:
        return None  # idempotent: already done
    repo.update_task(task_id, {"Status": oc.ST_COMPLETED, "Completed At": repo._now()})
    repo.log_history(task_id, "completed")
    return repo.get_task(task_id)


def reschedule(task_id: str, new_date: date) -> dict | None:
    t = repo.get_task(task_id)
    if not t:
        return None
    repo.update_task(task_id, {"Due Date": new_date.isoformat(), "Status": oc.ST_OPEN})
    repo.log_history(task_id, "rescheduled", new_date.isoformat())
    return repo.get_task(task_id)


def set_waiting(task_id: str, followup: date | None) -> dict | None:
    t = repo.get_task(task_id)
    if not t:
        return None
    changes = {"Status": oc.ST_WAITING}
    if followup:
        changes["Due Date"] = followup.isoformat()
    repo.update_task(task_id, changes)
    repo.log_history(task_id, "waiting", str(followup or ""))
    return repo.get_task(task_id)


def skip(task_id: str) -> dict | None:
    t = repo.get_task(task_id)
    if not t or str(t.get("Status")) in (oc.ST_SKIPPED, oc.ST_COMPLETED):
        return None
    repo.update_task(task_id, {"Status": oc.ST_SKIPPED})
    repo.log_history(task_id, "skipped")
    return repo.get_task(task_id)


# --------------------------------------------------------------- bucketing
def bucket_for(task: dict) -> str | None:
    st = str(task.get("Status"))
    if st == oc.ST_COMPLETED:
        return oc.B_COMPLETED
    if st == oc.ST_WAITING:
        return oc.B_WAITING
    if st == oc.ST_SKIPPED:
        return None
    d = task.get("Due Date")
    if not d:
        return oc.B_UPCOMING
    try:
        dt = clock.parse_date(str(d))
    except Exception:
        return oc.B_UPCOMING
    today = clock.today()
    if dt < today:
        return oc.B_OVERDUE
    if dt == today:
        return oc.B_DUE_TODAY
    return oc.B_UPCOMING


def build_buckets() -> dict:
    buckets = {b: [] for b in (oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING,
                               oc.B_WAITING, oc.B_COMPLETED)}
    today = clock.today()
    week_start = today - timedelta(days=today.weekday())
    for t in repo.all_tasks():
        st = str(t.get("Status"))
        if st == oc.ST_COMPLETED:
            ca = t.get("Completed At")
            cd = None
            try:
                cd = clock.from_iso(ca).date() if ca else None
            except Exception:
                cd = None
            if cd and cd >= week_start:
                buckets[oc.B_COMPLETED].append(t)
            continue
        b = bucket_for(t)
        if b:
            buckets[b].append(t)
    for b in (oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING, oc.B_WAITING):
        buckets[b].sort(key=lambda t: str(t.get("Due Date") or "9999-99-99"))
    return buckets


def weekly_stats(buckets: dict) -> dict:
    return {
        "completed": len(buckets.get(oc.B_COMPLETED, [])),
        "pending": len(buckets.get(oc.B_DUE_TODAY, [])) + len(buckets.get(oc.B_UPCOMING, [])),
        "overdue": len(buckets.get(oc.B_OVERDUE, [])),
        "waiting": len(buckets.get(oc.B_WAITING, [])),
    }
