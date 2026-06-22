"""
Message text builders (spec sections 5, 20, 23, 28).

Pure functions: they take data and return HTML strings. No side effects, so they
are easy to unit-test.
"""
from __future__ import annotations

import html

from app import clock, constants


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


# ----------------------------------------------------- Group checkpoint card
def group_card(task: dict, role_label: str) -> str:
    ct = task["Checklist Type"]
    name = esc(task.get("Assigned Staff Name"))
    cutoff = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    status = task.get("Original Submission Status", constants.SUB_PENDING)

    head = f"<b>{esc(ct)}</b>\n\nAssigned {role_label}: {name}\nDue by: {cutoff}"

    if status == constants.SUB_PENDING and not task.get("Started At"):
        return head + "\nStatus: Pending\n\nPlease complete this checklist."
    if status == constants.SUB_PENDING and task.get("Started At"):
        return head + "\nStatus: In Progress"
    if status in (constants.SUB_ON_TIME, constants.SUB_LATE):
        submitted = clock.fmt_time(clock.from_iso(task.get("Submitted At")))
        return (
            f"<b>{esc(ct)}</b>\n\nAssigned {role_label}: {name}\n"
            f"Status: {esc(status)}\n"
            f"Result: {esc(task.get('Checklist Result'))}\n"
            f"Evidence: {esc(task.get('Evidence Status'))}\n"
            f"Submitted: {submitted}"
        )
    if status == constants.SUB_NOT_SUBMITTED:
        # Recovery overrides display if present.
        if task.get("Resolution Status") == constants.RES_RECOVERED_OIC:
            return (
                f"<b>{esc(ct)}</b>\n\nAssigned {role_label}: {name}\n"
                f"Original Status: Not Submitted\n"
                f"Resolution: Recovered by Store OIC\n"
                f"Recovered: {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}"
            )
        missing = task.get("_missing_text", "")
        cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
        return (
            f"<b>{esc(ct)}</b>\n\nAssigned {role_label}: {name}\n"
            f"Status: Not Submitted\n"
            f"Missing: {esc(missing) or '—'}\n"
            f"Cutoff: {cut}"
        )
    return head


# --------------------------------------------------------------- OIC alert
def oic_alert(task: dict, missing: list[str]) -> str:
    ct = esc(task["Checklist Type"])
    name = esc(task.get("Assigned Staff Name"))
    cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    lines = "\n".join(f"• {esc(m)}" for m in missing) or "• (proof not yet received)"
    return (
        f"<b>OIC Follow-Up Needed</b>\n\n"
        f"{ct} assigned to {name} is incomplete.\n\n"
        f"Missing:\n{lines}\n\n"
        f"Final cutoff: {cut}"
    )


def oic_resolved(task: dict, recovered_by_name: str) -> str:
    ct = esc(task["Checklist Type"])
    name = esc(task.get("Assigned Staff Name"))
    return (
        f"<b>Resolved</b>\n\n"
        f"{ct} originally assigned to {name}.\n\n"
        f"Original status: Not Submitted\n"
        f"Recovered by: {esc(recovered_by_name)}\n"
        f"Recovered at: {clock.fmt_dt(clock.from_iso(task.get('Recovered At')))}"
    )


# ------------------------------------------------------------- Reminder text
def staff_reminder(task: dict, missing: list[str]) -> str:
    ct = esc(task["Checklist Type"])
    cut = clock.fmt_time(clock.from_iso(task.get("Cutoff At")))
    lines = "\n".join(f"• {esc(m)}" for m in missing) or "• (not started yet)"
    return (
        f"<b>{ct} is still pending.</b>\n\n"
        f"Remaining:\n{lines}\n\n"
        f"Due by {cut}."
    )
