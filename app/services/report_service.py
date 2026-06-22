"""
Weekly accountability report (spec section 29).

Counts per employee distinguish on-time / late / not-submitted / recovered, and
NEVER credit an employee with on-time when the OIC recovered the task.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import clock, constants
from app.config import get_settings
from app.repositories import staff_repo, task_repo
from app.repositories.base import as_bool
from app.repositories.misc_repo import recovery
from app.telegram import messages, notify


def _week_bounds(ref: date) -> tuple[date, date]:
    start = ref - timedelta(days=ref.weekday() + 7)   # previous Monday
    return start, start + timedelta(days=6)


def build_text(ref: date | None = None) -> str:
    ref = ref or clock.today()
    start, end = _week_bounds(ref)

    per_staff: dict[str, dict] = {}

    def bucket(staff_id: str, name: str) -> dict:
        return per_staff.setdefault(staff_id or name, {
            "name": name, "assigned": 0, "on_time": 0, "late": 0,
            "not_submitted": 0, "issues": 0, "missing_evidence": 0,
            "recovered": 0, "unresolved": 0,
        })

    d = start
    while d <= end:
        for t in task_repo.for_date(d):
            if t.get("Original Submission Status") == constants.SUB_CLOSED:
                continue
            b = bucket(str(t.get("Assigned Staff ID")), str(t.get("Assigned Staff Name")))
            b["assigned"] += 1
            status = t.get("Original Submission Status")
            res = t.get("Resolution Status")
            if status == constants.SUB_ON_TIME:
                b["on_time"] += 1
            elif status == constants.SUB_LATE:
                b["late"] += 1
            elif status == constants.SUB_NOT_SUBMITTED:
                b["not_submitted"] += 1
                if res == constants.RES_RECOVERED_OIC:
                    b["recovered"] += 1
                elif res == constants.RES_LATE_BY_STAFF:
                    b["late"] += 1
                elif res in (constants.RES_STILL_INCOMPLETE, constants.RES_NONE):
                    b["unresolved"] += 1
            if t.get("Checklist Result") == constants.RESULT_ISSUE:
                b["issues"] += 1
            if t.get("Evidence Status") == constants.EV_MISSING:
                b["missing_evidence"] += 1
        d += timedelta(days=1)

    e = messages.esc
    lines = [f"<b>Weekly Accountability — {clock.fmt_date(start)} to {clock.fmt_date(end)}</b>", ""]
    if not per_staff:
        lines.append("No tasks recorded for this week.")
    for b in per_staff.values():
        lines.append(
            f"<b>{e(b['name'])}</b>\n"
            f"Assigned: {b['assigned']} | On time: {b['on_time']} | "
            f"Late: {b['late']} | Not submitted: {b['not_submitted']}\n"
            f"Missing evidence: {b['missing_evidence']} | Issues: {b['issues']} | "
            f"Recovered by OIC: {b['recovered']} | Still unresolved: {b['unresolved']}"
        )
        lines.append("")

    # OIC recovery activity (spec section 29).
    recs = recovery.between(start, end)
    lines.append("<b>Store OIC Recovery Activity</b>")
    if not recs:
        lines.append("No recoveries this week.")
    else:
        by_oic: dict[str, list] = {}
        for r in recs:
            by_oic.setdefault(str(r.get("OIC Name")), []).append(r)
        for oic_name, items in by_oic.items():
            lines.append(f"{e(oic_name)}: {len(items)} recovery submission(s)")
            for r in items:
                lines.append(f"  • {e(r.get('Original Assigned Staff Name'))} — "
                             f"{e(r.get('Missing Items at Cutoff'))} "
                             f"at {clock.fmt_dt(clock.from_iso(r.get('Recovery Submitted At')))}")
    lines.append("\nFor coaching and follow-up — not punishment.")
    return "\n".join(lines)


async def send_weekly_report(ref: date | None = None) -> None:
    await notify.send_message(get_settings().admin_telegram_user_id, build_text(ref))
