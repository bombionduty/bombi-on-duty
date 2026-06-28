"""
Deterministic, zero-cost natural-language task parser for Owner Mode.

No paid AI. Splits a brain dump into separate tasks and extracts common date,
weekday, and recurrence phrases. Key behaviors:
  * A trailing shared date phrase ("...this week.") applies to every task in that
    sentence that has no date of its own; explicit per-task dates win.
  * "before <day>" = the day BEFORE; "on"/"by <day>" = that day.
  * A one-off date that has already passed is dropped (due="") so the bot asks
    instead of scheduling in the past.
  * Original capitalization is preserved (Biscoff, Alex, ORs, P&L).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from app import clock
from app.owner import constants as oc

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_WD = "|".join(WEEKDAYS)
_LEAD_IN = re.compile(
    r"(?i)^\s*(this week i (also )?need to|today i need to|i (also )?need to|"
    r"remind me to|don'?t forget to|make sure to|bombi,?\s*|please|also)\s+"
)


def parse(text: str) -> list[dict]:
    out: list[dict] = []
    for sentence in re.split(r"[\n;]+", (text or "").strip()):
        sentence = _LEAD_IN.sub("", sentence.strip())
        if not sentence:
            continue
        frags = [f for f in _split_tasks(sentence) if f.strip()]
        items = []
        shared_due: date | None = None
        for f in frags:
            f = re.sub(r"(?i)^\s*(and|also|or|then)\s+", "", f).strip()
            due, recurrence, cleaned, _past = _extract_when(f)
            responsible = _extract_person(cleaned)
            category = _detect_category(f, responsible)
            title = _clean_title(cleaned)
            if not title:
                continue
            items.append({"title": title, "due": due, "category": category,
                          "responsible": responsible, "recurrence": recurrence,
                          "past": _past})
            if due is not None:
                shared_due = due  # last explicit date in the sentence
        # Propagate the shared trailing date to dateless (non-past) tasks.
        for it in items:
            if it["due"] is None and not it["past"] and shared_due is not None:
                it["due"] = shared_due
        for it in items:
            out.append({
                "title": it["title"],
                "due": it["due"].isoformat() if it["due"] else "",
                "due_time": "",
                "category": it["category"],
                "responsible": it["responsible"],
                "recurrence": it["recurrence"],
            })
    return out


def _has_when_cue(text: str) -> bool:
    """True if a fragment carries its own date/time/recurrence — used to decide
    whether ' and ' joins two tasks or just two words (names/objects)."""
    due, recurrence, _cleaned, past = _extract_when(text)
    return due is not None or bool(recurrence) or past


def _split_tasks(sentence: str) -> list[str]:
    """Split a sentence into task fragments. Commas / 'then' always separate;
    ' and ' only separates when the part after it has its own date/recurrence
    (so "tell angel and allyssa to clean toppings" stays ONE task, but
    "pay rent on the 30th and film a video tomorrow" is two)."""
    out: list[str] = []
    for part in re.split(r",\s+|\s+then\s+", sentence):
        pieces = re.split(r"\s+and\s+", part)
        if len(pieces) == 1:
            out.append(part)
            continue
        merged = [pieces[0]]
        for p in pieces[1:]:
            if _has_when_cue(p):
                merged.append(p)              # its own dated task
            else:
                merged[-1] = f"{merged[-1]} and {p}"  # 'and' just joins words
        out.extend(merged)
    return out


def _next_weekday(target: int, allow_today: bool = True) -> date:
    d = clock.today()
    delta = (target - d.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return d + timedelta(days=delta)


def _nth_of_month(n: int) -> date | None:
    if n < 1 or n > 31:
        return None
    d = clock.today()
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day <= n <= last:
        return date(d.year, d.month, n)
    ny, nm = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    last_next = calendar.monthrange(ny, nm)[1]
    return date(ny, nm, min(n, last_next))


def _extract_when(frag: str):
    """(date|None, recurrence, cleaned_text_with_original_case, past_flag)."""
    t = " " + frag + " "
    recurrence = ""
    due: date | None = None
    today = clock.today()

    def strip(pat):
        nonlocal t
        t = re.sub(pat, " ", t, flags=re.I)

    # recurrence
    m = re.search(r"\bevery\s+(\d+)\s+days?\b", t, re.I)
    if m:
        recurrence = f"days:{int(m.group(1))}"
        due = today + timedelta(days=int(m.group(1)))
        strip(r"\bevery\s+\d+\s+days?\b")
    m = re.search(r"\bevery\s+(" + _WD + r")\b", t, re.I)
    if m:
        wd = WEEKDAYS[m.group(1).lower()]
        recurrence = f"weekly:{wd}"
        due = _next_weekday(wd, allow_today=True)
        strip(r"\bevery\s+\w+\b")
    if re.search(r"\bmonthly\b|\bevery month\b", t, re.I):
        recurrence = recurrence or "monthly"
        strip(r"\bmonthly\b|\bevery month\b")
    if re.search(r"\bweekly\b|\bevery week\b", t, re.I):
        recurrence = recurrence or "weekly"
        strip(r"\bweekly\b|\bevery week\b")

    if due is None:
        if re.search(r"\btomorrow\b", t, re.I):
            due = today + timedelta(days=1); strip(r"\btomorrow\b")
        elif re.search(r"\b(later )?today\b|\btonight\b", t, re.I):
            due = today; strip(r"\b(later )?today\b|\btonight\b")
        elif re.search(r"\bthis weekend\b", t, re.I):
            due = _next_weekday(5, allow_today=True); strip(r"\bthis weekend\b")
        elif re.search(r"\bnext week\b", t, re.I):
            due = _next_weekday(0, allow_today=False); strip(r"\bnext week\b")
        elif re.search(r"\bthis week\b", t, re.I):
            due = _next_weekday(6, allow_today=True); strip(r"\bthis week\b")  # upcoming Sun (today if Sun)
        else:
            m = re.search(r"\bin\s+(\d+)\s+days?\b", t, re.I)
            if m:
                due = today + timedelta(days=int(m.group(1)))
                strip(r"\bin\s+\d+\s+days?\b")
            else:
                m = re.search(r"\bon\s+the\s+(\d{1,2})(st|nd|rd|th)?\b|\bthe\s+(\d{1,2})(st|nd|rd|th)\b|\bon\s+(\d{1,2})\b", t, re.I)
                if m:
                    n = next((int(g) for g in m.groups() if g and g.isdigit()), 0)
                    due = _nth_of_month(n) if n else None
                    strip(r"\bon\s+the\s+\d{1,2}(st|nd|rd|th)?\b|\bthe\s+\d{1,2}(st|nd|rd|th)\b|\bon\s+\d{1,2}\b")
                else:
                    m = re.search(r"\b(before|by|on|this|next)?\s*(" + _WD + r")\b", t, re.I)
                    if m:
                        prefix = (m.group(1) or "").lower()
                        wd = WEEKDAYS[m.group(2).lower()]
                        base = _next_weekday(wd, allow_today=(prefix != "next"))
                        due = base - timedelta(days=1) if prefix == "before" else base
                        strip(r"\b(before|by|on|this|next)?\s*(" + _WD + r")\b")

    # A one-off (non-recurring) date in the past -> drop so the bot asks.
    past = False
    if due is not None and not recurrence and due < today:
        past = True
        due = None

    cleaned = re.sub(r"\s+", " ", t).strip(" .,")
    return due, recurrence, cleaned, past


def _extract_person(frag: str) -> str:
    low = frag.lower()
    for p in oc.KNOWN_PEOPLE:
        if re.search(r"\b" + re.escape(p) + r"\b", low):
            return p.capitalize()
    return ""


def _detect_category(frag: str, responsible: str) -> str:
    low = " " + frag.lower() + " "
    for cat, kws in oc.CATEGORY_KEYWORDS.items():
        if any(k in low for k in kws):
            return cat
    if responsible.lower() == "alex":
        return "poster"
    return oc.CAT_GENERAL


def _clean_title(frag: str) -> str:
    t = frag.strip(" .,")
    t = re.sub(r"(?i)^\s*(and|also|or|then)\s+", "", t).strip()
    t = _LEAD_IN.sub("", t)
    t = re.sub(r"(?i)^\s*(to|about|the)\s+", "", t).strip()
    if not t:
        return ""
    return t[0].upper() + t[1:]
