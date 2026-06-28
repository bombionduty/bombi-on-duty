"""Owner Mode vocabulary: statuses, categories, emoji, default settings."""
from __future__ import annotations

# Stored task status (in the sheet).
ST_OPEN = "Open"
ST_WAITING = "Waiting"
ST_COMPLETED = "Completed"
ST_SKIPPED = "Skipped"
ST_CANCELLED = "Cancelled"

# Derived buckets (computed from due date for Open tasks) — for display only.
B_OVERDUE = "OVERDUE"
B_DUE_TODAY = "DUE TODAY"
B_UPCOMING = "UPCOMING"
B_WAITING = "WAITING ON SOMEONE"
B_COMPLETED = "COMPLETED"

STATUS_EMOJI = {
    B_OVERDUE: "🔴", B_DUE_TODAY: "🟠", B_UPCOMING: "🟡",
    B_WAITING: "🔵", B_COMPLETED: "✅",
}

# Category -> emoji (spec section 9).
CAT_GENERAL = "general"
CATEGORY_EMOJI = {
    CAT_GENERAL: "🍓",
    "envelope": "💌",
    "or": "🧾",
    "deposit": "🏦",
    "payroll": "💸",
    "pnl": "📊",
    "content": "🎥",
    "poster": "🎨",
    "bills": "💡",
    "accountant": "📤",
}

# Keyword -> category for the parser.
CATEGORY_KEYWORDS = {
    "envelope": ["envelope", "envelopes"],
    "or": ["or ", "ors", "official receipt", "sales or"],
    "deposit": ["deposit", "bank"],
    "payroll": ["payroll", "payday", "salary", "gross pay"],
    "pnl": ["p&l", "pnl", "profit and loss", "income statement"],
    "content": ["film", "edit", "video", "footage", "shoot", "record", "reel"],
    "poster": ["poster", "design", "alex", "graphic", "artwork"],
    "bills": ["electric", "water", "rent", "credit card", "internet", "wifi", "bill"],
    "accountant": ["accountant", "gross payroll to"],
}

# Known responsible people (delegated tasks become "Waiting on someone").
KNOWN_PEOPLE = ["alex", "accountant", "finance"]

# Default owner settings (editable later via the Phase 2 wizard).
SET_DAILY_SUMMARY = "owner_daily_summary_time"        # HH:MM
SET_WEEKLY_SUMMARY = "owner_weekly_summary"           # "SUN 19:00"
SET_DASHBOARD_MSG_ID = "owner_dashboard_message_id"
SET_GREETING_NAME = "owner_greeting_name"
SET_PAUSED = "owner_reminders_paused"                 # "true"/"false"
SET_LEAD_DAYS = "owner_bill_lead_days"                # bill advance reminder days
SET_TIMED_LEAD_MIN = "owner_timed_lead_min"           # timed-task advance (minutes)
SET_UPCOMING_DAYS = "owner_upcoming_days"             # "coming up" window (days)

DEFAULTS = {
    SET_DAILY_SUMMARY: "09:00",
    SET_WEEKLY_SUMMARY: "SUN 19:00",
    SET_GREETING_NAME: "Lesha",
    SET_PAUSED: "false",
    SET_LEAD_DAYS: "3",
    SET_TIMED_LEAD_MIN: "60",
    SET_UPCOMING_DAYS: "3",
}
