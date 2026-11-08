"""
Message text builders (spec sections 5, 20, 23, 28).

Pure functions: they take data and return HTML strings, so they're easy to test.
Friendly, emoji-driven wording so staff can tell at a glance whether a task is
done, pending, or needs action. Reminders / escalations / resolutions each use a
distinct emoji so they're instantly recognisable.
"""
from __future__ import annotations

import html

from app import clock, constants

# Status -> emoji, used consistently everywhere.
STATUS_EMOJI = {
    constants.SUB_PENDING: "🟡",
    constants.SUB_ON_TIME: "✅",
    constants.SUB_LATE: "🟠",
    constants.SUB_NOT_SUBMITTED: "🔴",
    constants.SUB_CLOSED: "🏠",
}
CHECK_EMOJI = {
    constants.CHECK_OPENING: "🌅",
    constants.CHECK_HANDOVER: "🔁",
    constants.CHECK_CLOSING: "🌙",
}


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _title(ct: str) -> str:
    return f"{CHECK_EMOJI.get(ct, '📋')} <b>{esc(ct)}</b>"


def _who(task: dict, role_label: str) -> str:
    """Assignee mention. Prefers a tappable mention set by the caller.
    For a closing checklist with peak support, show the peak staffer too."""
    mention = task.get("_assignee_mention") or esc(task.get("Assigned Staff Name"))
    line = f"Assigned {role_label}: {mention}"
    peak = task.get("_peak_mention") or (esc(task.get("Peak Staff Name"))
                                         if task.get("Peak Staff Name") else "")
    if peak:
        line += f"\n🤝 Peak support: {peak} (either can complete)"
    return line


# ----------------------------------------------------- Group checkpoint card
def group_card(task: dict, role_label: str) -> str:
    ct = task["Checklist Type"]
    cutoff = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    status = task.get("Original Submission Status", constants.SUB_PENDING)
    head = f"{_title(ct)}\n\n{_who(task, role_label)}\n🕐 Due by: {cutoff}"

    # Admin completed it on the staff's behalf — show complete/incomplete clearly,
    # naming exactly which items were not submitted.
    if task.get("Resolution Status") == constants.RES_RESOLVED_ADMIN and task.get("Submitted At"):
        submitted = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
        by = task.get("Submitted By Name") or "Admin"
        missing = task.get("_missing_text", "")
        if missing:
            return (
                f"{_title(ct)}\n\n{_who(task, role_label)}\n"
                f"⚠️ <b>Submitted by {esc(by)} — Incomplete</b>\n"
                f"🚫 Not submitted: {esc(missing)}\n"
                f"📎 Evidence: {esc(task.get('Evidence Status'))}\n"
                f"🕐 Submitted: {submitted}"
            )
        return (
            f"{_title(ct)}\n\n{_who(task, role_label)}\n"
            f"✅ <b>Submitted by {esc(by)} — Complete</b>\n"
            f"📎 Evidence: {esc(task.get('Evidence Status'))}\n"
            f"🕐 Submitted: {submitted}"
        )

    if status == constants.SUB_PENDING and not task.get("Started At"):
        return head + "\n🟡 Status: Pending\n\n👉 Tap below to complete this checklist."
    if status == constants.SUB_PENDING and task.get("Started At"):
        return head + "\n🔵 Status: In Progress…\n\n👉 Tap below to finish and submit."
    if status in (constants.SUB_ON_TIME, constants.SUB_LATE):
        submitted = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
        emoji = STATUS_EMOJI[status]
        result = task.get("Checklist Result")
        result_line = ("🎉 Result: All Complete" if result == constants.RESULT_ALL_COMPLETE
                       else "📝 Result: Issue Reported")
        # Name who actually submitted (closer or peak support), when recorded.
        by = task.get("Submitted By Name")
        by_line = f"\n✍️ Submitted by: {esc(by)}" if by else ""
        return (
            f"{_title(ct)}\n\n{_who(task, role_label)}\n"
            f"{emoji} Status: {esc(status)}\n"
            f"{result_line}\n"
            f"📎 Evidence: {esc(task.get('Evidence Status'))}\n"
            f"🕐 Submitted: {submitted}{by_line}"
        )
    if status == constants.SUB_NOT_SUBMITTED:
        if task.get("Resolution Status") == constants.RES_RECOVERED_OIC:
            return (
                f"{_title(ct)}\n\n{_who(task, role_label)}\n"
                f"🔴 Original Status: Not Submitted\n"
                f"🟢 Resolution: Recovered by Store OIC\n"
                f"🕐 Recovered: {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}"
            )
        # Completed LATE (by staff, peak support, or the admin on their behalf):
        # flip the card to a submitted state and name who finished it.
        if task.get("Submitted At"):
            submitted = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
            result = task.get("Checklist Result")
            result_line = ("🎉 Result: All Complete" if result == constants.RESULT_ALL_COMPLETE
                           else "📝 Result: Issue Reported")
            by = task.get("Submitted By Name")
            by_line = f"\n✍️ Submitted by: {esc(by)}" if by else ""
            return (
                f"{_title(ct)}\n\n{_who(task, role_label)}\n"
                f"🟠 Status: Completed late\n"
                f"{result_line}\n"
                f"📎 Evidence: {esc(task.get('Evidence Status'))}\n"
                f"🕐 Submitted: {submitted}{by_line}"
            )
        missing = task.get("_missing_text", "")
        cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
        return (
            f"{_title(ct)}\n\n{_who(task, role_label)}\n"
            f"🔴 Status: Not Submitted\n"
            f"⚠️ Missing: {esc(missing) or '—'}\n"
            f"🕐 Cutoff: {cut}\n\n"
            f"👉 You can still submit — it will be marked completed late."
        )
    return head


# --------------------------------------------------------------- OIC alerts
def oic_alert(task: dict, missing: list[str], *, after_cutoff: bool = False) -> str:
    """Private OIC follow-up. Clearly flagged as an OIC action item."""
    ct = task["Checklist Type"]
    cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    who = task.get("_assignee_mention") or esc(task.get("Assigned Staff Name"))
    lines = "\n".join(f"   ⚠️ {esc(m)}" for m in missing) or "   ⚠️ (proof not yet received)"
    banner = "🚨 <b>OIC ACTION — Cutoff Passed</b>" if after_cutoff else "🟠 <b>OIC Follow-Up Needed</b>"
    tail = ("\n\n👉 Tap <b>Complete Missing Entry</b> to recover this on behalf of the staff."
            if after_cutoff else "")
    return (
        f"{banner}\n\n"
        f"{CHECK_EMOJI.get(ct, '📋')} {esc(ct)} assigned to {who} is incomplete.\n\n"
        f"Missing:\n{lines}\n\n"
        f"🕐 Final cutoff: {cut}{tail}"
    )


def oic_resolved(task: dict, recovered_by_name: str) -> str:
    ct = task["Checklist Type"]
    who = task.get("_assignee_mention") or esc(task.get("Assigned Staff Name"))
    return (
        f"✅ <b>Resolved</b>\n\n"
        f"{CHECK_EMOJI.get(ct, '📋')} {esc(ct)} originally assigned to {who}.\n\n"
        f"🔴 Original status: Not Submitted\n"
        f"🟢 Recovered by: {esc(recovered_by_name)}\n"
        f"🕐 Recovered at: {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}"
    )


# ------------------------------------------------------------- Reminder text
def staff_reminder(task: dict, missing: list[str]) -> str:
    ct = task["Checklist Type"]
    cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    if missing:
        body = "Still to do:\n" + "\n".join(f"   📌 {esc(m)}" for m in missing)
    elif task.get("Started At"):
        # Everything filled in — they just haven't pressed Submit.
        body = "Everything looks filled in — <b>tap Submit to finish.</b>"
    else:
        body = "You haven't started it yet — please open it and complete it."
    return (
        f"🔔 <b>Friendly reminder</b> — your {CHECK_EMOJI.get(ct, '📋')} "
        f"<b>{esc(ct)}</b> is still pending.\n\n"
        f"{body}\n\n"
        f"🕐 Due by {cut}. Tap <b>/mytask</b> if you closed the form."
    )
