"""
Deterministic, zero-cost natural-language task parser for Owner Mode.

No paid AI. It splits a brain dump into separate tasks and extracts common date,
weekday, and recurrence phrases. When unsure it simply returns no date (the
confirm card lets the owner fix it with buttons), so it never invents deadlines.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app import clock
from app.owner import constants as oc

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_LEAD_IN = re.compile(
    r"(?i)^\s*(this week i (also )?need to|today i need to|i (also )?need to|"
    r"remind me to|don'?t forget to|make sure to|bombi,?\s*|please|also)\s+"
)


def parse(text: str) -> list[dict]:
    """Return a list of {title, due, due_time, category, responsible, recurrence}."""
    tasks = []
    for frag in _split_fragments(text or ""):
        frag = frag.strip(" .,")
        if len(frag) < 3:
            continue
        due, recurrence, cleaned = _extract_when(frag)
        responsible = _extract_person(cleaned)
        category = _detect_category(frag, responsible)
        title = _clean_title(cleaned, responsible)
        if not title:
            continue
        tasks.append({
            "title": title,
            "due": due.isoformat() if due else "",
            "due_time": "",
            "category": category,
            "responsible": responsible,
            "recurrence": recurrence,
        })
    return tasks


def _split_fragments(text: str) -> list[str]:
    text = _LEAD_IN.sub("", text.strip())
    parts = re.split(r"[\n;]+", text)
    out: list[str] = []
    for p in parts:
        p = _LEAD_IN.sub("", p.strip())
        out.extend(re.split(r",\s+|\s+and\s+|\s+then\s+", p))
    return [s for s in out if s.strip()]


def _next_weekday(target: int, *, allow_today: bool = True) -> date:
    d = clock.today()
    delta = (target - d.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return d + timedelta(days=delta)


def _nth_of_month(n: int) -> date:
    d = clock.today()
    import calendar
    last = calendar.monthrange(d.year, d.month)[1]
    if n < 1 or n > 31:
        return d
    if n < 1:
        n = 1
    # if the day already passed this month, use next month
    if n >= d.day and n <= last:
        return date(d.year, d.month, n)
    # next month (clamp to its last day)
    ny, nm = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    last_next = calendar.monthrange(ny, nm)[1]
    return date(ny, nm, min(n, last_next))


def _extract_when(frag: str):
    """Return (date|None, recurrence_str, cleaned_fragment)."""
    t = " " + frag.lower() + " "
    recurrence = ""
    due = None

    def strip(pat):
        nonlocal t
        t = re.sub(pat, " ", t, flags=re.I)

    # --- recurrence ---
    m = re.search(r"\bevery\s+(\d+)\s+days?\b", t)
    if m:
        recurrence = f"days:{int(m.group(1))}"
        due = clock.today() + timedelta(days=int(m.group(1)))
        strip(r"\bevery\s+\d+\s+days?\b")
    m = re.search(r"\bevery\s+(" + "|".join(WEEKDAYS) + r")\b", t)
    if m:
        wd = WEEKDAYS[m.group(1)]
        recurrence = f"weekly:{wd}"
        due = _next_weekday(wd, allow_today=True)
        strip(r"\bevery\s+\w+\b")
    if re.search(r"\bmonthly\b|\bevery month\b", t):
        recurrence = recurrence or "monthly"
        strip(r"\bmonthly\b|\bevery month\b")
    if re.search(r"\bweekly\b|\bevery week\b", t):
        recurrence = recurrence or "weekly"
        strip(r"\bweekly\b|\bevery week\b")

    # --- explicit one-off dates (only if no recurrence date set) ---
    if due is None:
        if re.search(r"\btomorrow\b", t):
            due = clock.today() + timedelta(days=1); strip(r"\btomorrow\b")
        elif re.search(r"\b(later )?today\b|\btonight\b", t):
            due = clock.today(); strip(r"\b(later )?today\b|\btonight\b")
        elif re.search(r"\bthis weekend\b", t):
            due = _next_weekday(5, allow_today=True); strip(r"\bthis weekend\b")
        elif re.search(r"\bnext week\b", t):
            due = _next_weekday(0, allow_today=False); strip(r"\bnext week\b")
        else:
            m = re.search(r"\bin\s+(\d+)\s+days?\b", t)
            if m:
                due = clock.today() + timedelta(days=int(m.group(1)))
                strip(r"\bin\s+\d+\s+days?\b")
            else:
                m = re.search(r"\bon\s+the\s+(\d{1,2})(st|nd|rd|th)?\b|\bthe\s+(\d{1,2})(st|nd|rd|th)\b|\bon\s+(\d{1,2})\b", t)
                if m:
                    n = next((int(g) for g in m.groups() if g and g.isdigit()), 0)
                    if n:
                        due = _nth_of_month(n)
                        strip(r"\bon\s+the\s+\d{1,2}(st|nd|rd|th)?\b|\bthe\s+\d{1,2}(st|nd|rd|th)\b|\bon\s+\d{1,2}\b")
                else:
                    m = re.search(r"\b(before|by|on|this|next)?\s*(" + "|".join(WEEKDAYS) + r")\b", t)
                    if m:
                        wd = WEEKDAYS[m.group(2)]
                        allow_today = (m.group(1) or "") != "next"
                        due = _next_weekday(wd, allow_today=allow_today)
                        strip(r"\b(before|by|on|this|next)?\s*(" + "|".join(WEEKDAYS) + r")\b")

    cleaned = re.sub(r"\s+", " ", t).strip(" .,")
    return due, recurrence, cleaned


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


def _clean_title(frag: str, responsible: str) -> str:
    t = frag.strip(" .,")
    t = re.sub(r"(?i)^\s*(and|also|or|then)\s+", "", t).strip()
    t = _LEAD_IN.sub("", t)
    t = re.sub(r"(?i)^\s*(to|about|the)\s+", "", t).strip()
    if not t:
        return ""
    return t[0].upper() + t[1:]
