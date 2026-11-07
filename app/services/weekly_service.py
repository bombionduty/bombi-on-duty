"""Weekly accountability checklists (Feature 3).

A weekly task is a single physical paper the DOER photographs when done, and a
different staffer (the next shift, or the OIC/admin) then photographs again after
writing their verification checks on it. Two accountable photos per occurrence.

Flow (all in the staff group, by photo — no Mini App):
  1. Task posts at its time → status Pending.
  2. DOER sends a photo (reply to the card, or just a photo when it's their only
     open item) → status "Doer Done".
  3. A DIFFERENT staffer (or the OIC/admin) sends a verification photo → status
     "Verified". Done.
If it isn't verified by the cutoff, it's flagged Missing and the OIC is alerted.
"""
from __future__ import annotations

import html as _html
import logging
from datetime import date, datetime, time as _time, timedelta

from app import clock, constants
from app.config import get_settings
from app.repositories import staff_repo, weekly_repo as repo
from app.repositories.base import as_bool
from app.telegram import messages, notify

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers
def _mention(staff_id: str, name: str, tg_id) -> str:
    s = staff_repo.get_by_staff_id(staff_id) if staff_id else None
    uname = str((s or {}).get("Telegram Username") or "").lstrip("@")
    name = name or "staff"
    if uname:
        return f"@{uname}"
    if tg_id:
        return f'<a href="tg://user?id={tg_id}">{_html.escape(str(name))}</a>'
    return _html.escape(str(name))


def _doer_mention(inst: dict) -> str:
    return _mention(str(inst.get("Doer Staff ID") or ""),
                    str(inst.get("Doer Name") or ""),
                    inst.get("Doer Telegram User ID"))


def _time12(t: str) -> str:
    try:
        hh, mm = (str(t).split(":") + ["0"])[:2]
        return _time(int(hh), int(mm)).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(t)


def _this_week_occurrence(weekday: str, ref: date) -> date | None:
    """The date of `weekday` (MON..SUN) within the Mon–Sun week containing ref."""
    try:
        idx = constants.WEEKDAYS.index(weekday.upper())
    except ValueError:
        return None
    monday = ref - timedelta(days=ref.weekday())
    return monday + timedelta(days=idx)


def _cutoff_at(occ: date, time_str: str, cutoff_str: str) -> str:
    """ISO cutoff datetime. If the cutoff time is at/earlier than the task time,
    it means after midnight (e.g. a 23:00 task with a 01:00 cutoff)."""
    try:
        start = clock.combine(occ, clock.parse_time(time_str or "23:59"))
        cut = clock.combine(occ, clock.parse_time(cutoff_str or "23:59"))
        if cut <= start:
            cut += timedelta(days=1)
        return clock.iso(cut)
    except Exception:
        return clock.iso(clock.combine(occ, _time(23, 59)))


# ---------------------------------------------------------------- generation
def ensure_instances(ref: date) -> None:
    """Make sure this week's occurrence row exists for every active weekly task,
    so the admin can override its doer any time during the week before it posts."""
    now = clock.now()
    for d in repo.active_defs():
        occ = _this_week_occurrence(str(d.get("Weekday") or ""), ref)
        if not occ:
            continue
        if repo.instance_for(str(d["Weekly ID"]), occ.isoformat()):
            continue
        cutoff_iso = _cutoff_at(occ, str(d.get("Time") or ""), str(d.get("Cutoff Time") or ""))
        # Don't backfill an occurrence whose window ALREADY closed before this task
        # existed (e.g. a task created mid-week for an earlier weekday) — otherwise
        # it would be created and instantly flagged "missed".
        cut = clock.from_iso(cutoff_iso)
        if cut and cut < now:
            continue
        doer = None
        did = str(d.get("Default Doer Staff ID") or "")
        if did:
            doer = staff_repo.get_by_staff_id(did)
        repo.add_instance(
            weekly_id=str(d["Weekly ID"]), title=str(d.get("Title") or ""),
            date_iso=occ.isoformat(), weekday=str(d.get("Weekday") or ""),
            doer=doer, time=str(d.get("Time") or ""), cutoff_at=cutoff_iso,
        )


# ------------------------------------------------------------------- card
def card(inst: dict, header: str | None = None) -> str:
    status = str(inst.get("Status"))
    title = messages.esc(inst.get("Title"))
    when = _time12(inst.get("Time"))
    doer = _doer_mention(inst)
    if status == repo.ST_PENDING:
        head = header or "🧾 <b>WEEKLY CHECKLIST — due today</b>"
        return (f"{head}\n\n<b>{title}</b>\n⏰ {messages.esc(when)}\n"
                f"👤 Doer: {doer}\n\n"
                f"📸 <b>Step 1 of 2:</b> {doer}, reply to this message with a photo of "
                f"the completed paper checklist.")
    if status == repo.ST_DOER_DONE:
        return (f"🧾 <b>WEEKLY CHECKLIST — needs verifying</b>\n\n<b>{title}</b>\n"
                f"✅ Done by: {messages.esc(inst.get('Doer Name'))}\n\n"
                f"📸 <b>Step 2 of 2:</b> a <b>different</b> staffer (next shift) or the "
                f"OIC — write your checks on the paper, then reply here with a photo to "
                f"verify it.")
    if status == repo.ST_VERIFIED:
        return (f"✅ <b>Weekly checklist verified — {title}</b>\n"
                f"👤 Done by: {messages.esc(inst.get('Doer Name'))}\n"
                f"🔎 Verified by: {messages.esc(inst.get('Checker Name'))}")
    if status == repo.ST_MISSING:
        done = inst.get("Doer Name")
        state = (f"done by {messages.esc(done)}, not yet verified" if done
                 else "not done")
        return (f"🔴 <b>Weekly checklist MISSING — {title}</b>\n"
                f"Cutoff passed — {state}.")
    return f"<b>{title}</b>"


async def post_card(inst: dict, header: str | None = None) -> None:
    sent = await notify.send_message(get_settings().staff_group_chat_id,
                                     card(inst, header))
    if sent:
        repo.update_instance(inst["Instance ID"], {"Group Message ID": str(sent.message_id)})


async def _refresh_card(instance_id: str) -> None:
    inst = repo.get_instance(instance_id)
    gid = inst and inst.get("Group Message ID")
    if not gid:
        return
    try:
        await notify.edit_message(get_settings().staff_group_chat_id, int(gid), card(inst))
    except Exception:
        pass


# ------------------------------------------------------------- scheduling
def due_to_post(now: datetime) -> list[dict]:
    """Pending instances whose window is OPEN (start time reached, cutoff not yet)
    and that haven't been posted. Window-based so a task that runs past midnight
    (start Sat 23:00, cutoff Sun 01:30) still posts after midnight."""
    out = []
    for inst in repo.open_instances():
        if str(inst.get("Status")) != repo.ST_PENDING:
            continue
        if str(inst.get("Group Message ID")):
            continue
        try:
            start = clock.combine(clock.parse_date(str(inst.get("Date"))),
                                  clock.parse_time(str(inst.get("Time") or "00:00")))
        except Exception:
            continue
        cutoff = clock.from_iso(str(inst.get("Cutoff At") or ""))
        if now >= start and (cutoff is None or now < cutoff):
            out.append(inst)
    return out


def reminders_due(now: datetime) -> list[dict]:
    """Reminder events for posted-but-unfinished instances, one marker key each."""
    out: list[dict] = []
    defs = {str(d["Weekly ID"]): d for d in repo.all_defs()}
    for inst in repo.open_instances():
        if not str(inst.get("Group Message ID")):
            continue  # not posted yet
        d = defs.get(str(inst.get("Weekly ID")), {})
        times = [t.strip() for t in str(d.get("Reminder Times") or "").split(",") if t.strip()]
        iid = str(inst.get("Instance ID"))
        for t in times:
            try:
                target = clock.combine(now.date(), clock.parse_time(t))
            except Exception:
                continue
            if target <= now < target + timedelta(minutes=2):
                out.append({"inst": inst, "key": f"wk_rem::{iid}::{now.date().isoformat()}::{t}"})
    return out


async def cutoff_if_due(now: datetime) -> list[dict]:
    """Flag any open instance whose cutoff has passed as Missing + alert the OIC."""
    flagged = []
    for inst in repo.open_instances():
        cut = clock.from_iso(str(inst.get("Cutoff At") or ""))
        if not cut or now < cut:
            continue
        repo.update_instance(inst["Instance ID"],
                             {"Status": repo.ST_MISSING, "Missing At Cutoff": True})
        await _refresh_card(inst["Instance ID"])
        # State of the miss (done-but-unverified vs not done at all).
        done = inst.get("Doer Name")
        state = (f"done by {messages.esc(done)} but NOT verified" if done
                 else "not done")
        # Announce to the staff GROUP so everyone sees it.
        await notify.send_message(
            get_settings().staff_group_chat_id,
            f"🔴 <b>Weekly checklist missed</b>\n\n<b>{messages.esc(inst.get('Title'))}</b> "
            f"({messages.esc(inst.get('Date'))}) was {state} by cutoff.")
        # Also alert the OIC/admin privately.
        target, _, _ = staff_repo.oversight_target(inst.get("Doer Telegram User ID"))
        await notify.send_message(
            target,
            f"🔴 <b>Weekly checklist missed</b>\n\n<b>{messages.esc(inst.get('Title'))}</b> "
            f"({messages.esc(inst.get('Date'))}) was {state} by cutoff.")
        flagged.append(inst)
    return flagged


# ------------------------------------------------------ photo matching + flow
def pending_for_staff(tg_id: int | str) -> list[dict]:
    """Posted instances this staffer can act on right now:
      * Pending   — they are the assigned doer.
      * Doer Done — they are NOT the doer (so they can verify)."""
    tg = str(tg_id)
    out = []
    for inst in repo.open_instances():
        if not str(inst.get("Group Message ID")):
            continue
        status = str(inst.get("Status"))
        if status == repo.ST_PENDING and str(inst.get("Doer Telegram User ID")) == tg:
            out.append(inst)
        elif status == repo.ST_DOER_DONE and str(inst.get("Doer Telegram User ID")) != tg:
            out.append(inst)
    return out


def find_by_message(message_id: int | str) -> dict | None:
    """Match a replied-to message to an open instance — its card or a reminder."""
    mid = str(message_id)
    for inst in repo.open_instances():
        if str(inst.get("Group Message ID")) == mid:
            return inst
    from app.repositories import reminder_repo
    iid = reminder_repo.task_for_message(message_id)
    if iid:
        inst = repo.get_instance(iid)
        if inst and str(inst.get("Status")) in repo.OPEN_STATES:
            return inst
    return None


async def attach_photo(instance_id: str, by_tg_id: int, file_id: str) -> tuple[bool, str]:
    """Advance the two-step flow with a group photo. Returns (handled, reply)."""
    inst = repo.get_instance(instance_id)
    if not inst or str(inst.get("Status")) not in repo.OPEN_STATES:
        return False, ""
    is_admin = staff_repo.is_admin(by_tg_id)
    sender = staff_repo.get_by_telegram_id(by_tg_id)
    sender_name = str((sender or {}).get("Staff Name") or "")
    status = str(inst.get("Status"))

    if status == repo.ST_PENDING:
        # Only the assigned doer (or admin) provides the completion photo.
        if not is_admin and str(inst.get("Doer Telegram User ID")) != str(by_tg_id):
            return False, ""
        repo.update_instance(instance_id, {
            "Doer Photo File ID": file_id,
            "Doer Submitted At": clock.iso(clock.now()),
            "Status": repo.ST_DOER_DONE,
        })
        await _refresh_card(instance_id)
        return True, ("📸 Step 1 done — logged as completed. Now a <b>different</b> staffer "
                      "(or the OIC) must verify it with a photo of their checks.")

    # status == ST_DOER_DONE → verification step.
    # The verifier must be someone OTHER than the doer (that's the accountability).
    if str(inst.get("Doer Telegram User ID")) == str(by_tg_id) and not is_admin:
        return True, ("🙅 You completed this one — someone else (the next shift or the OIC) "
                      "needs to verify it.")
    repo.update_instance(instance_id, {
        "Checker Staff ID": str((sender or {}).get("Staff ID", "")),
        "Checker Name": sender_name or "OIC/Admin",
        "Checker Telegram User ID": str(by_tg_id),
        "Checker Photo File ID": file_id,
        "Checker Verified At": clock.iso(clock.now()),
        "Status": repo.ST_VERIFIED,
    })
    await _refresh_card(instance_id)
    return True, "✅ Verified — this weekly checklist is now fully accountable. Thank you!"


# --------------------------------------------------------- weekly report
def week_summary_lines(start: date, end: date) -> list[str]:
    """Accountability lines for the weekly report, covering start..end inclusive."""
    e = messages.esc
    rows = []
    d = start
    while d <= end:
        rows += repo.instances_for_date(d.isoformat())
        d += timedelta(days=1)
    lines = ["<b>Weekly Checklists</b>"]
    if not rows:
        lines.append("No weekly checklists scheduled this week.")
        return lines
    for r in sorted(rows, key=lambda r: (str(r.get("Date")), str(r.get("Time")))):
        status = str(r.get("Status"))
        icon = {"Verified": "✅", "Doer Done": "🟠", "Pending": "🟡",
                "Missing": "🔴"}.get(status, "•")
        when = clock.fmt_date(clock.parse_date(str(r.get("Date"))))
        detail = ""
        if status == repo.ST_VERIFIED:
            detail = f" — done by {e(r.get('Doer Name'))}, verified by {e(r.get('Checker Name'))}"
        elif status == repo.ST_DOER_DONE:
            detail = f" — done by {e(r.get('Doer Name'))}, NOT verified"
        elif status == repo.ST_MISSING:
            detail = (f" — done by {e(r.get('Doer Name'))}, not verified"
                      if r.get("Doer Name") else " — not done")
        lines.append(f"{icon} {e(r.get('Title'))} ({e(when)}){detail}")
    return lines
