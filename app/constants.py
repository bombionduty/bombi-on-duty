"""
Shared constants and status vocabularies.

These mirror exactly the status model in the specification (section 17). Keeping
them as plain string constants makes them safe to store in Google Sheets and
easy to compare. We DO NOT use Python enums in the sheet so the values stay
human-readable for the admin.
"""
from __future__ import annotations

# ---- Roles ----
ROLE_ADMIN = "Admin"
ROLE_OIC = "Store OIC"
ROLE_STAFF = "Staff"

# ---- Checklist (checkpoint) types ----
CHECK_OPENING = "Opening Check"
CHECK_HANDOVER = "Opener Handover"
CHECK_CLOSING = "Closing Check"
CHECKLIST_TYPES = [CHECK_OPENING, CHECK_HANDOVER, CHECK_CLOSING]

# Which schedule role is responsible for each checkpoint.
CHECK_RESPONSIBLE = {
    CHECK_OPENING: "opener",
    CHECK_HANDOVER: "opener",
    CHECK_CLOSING: "closer",
}

# ---- Checklist item types (section 33) ----
ITEM_ATTESTATION = "Attestation"
ITEM_LIVE_PHOTO = "Live Camera Photo"
ITEM_SCREENSHOT = "Gallery Screenshot"
ITEM_NUMBER = "Number Entry"
ITEM_TEXT = "Short Text Entry"
ITEM_YESNO = "Yes or No"
PROOF_ITEM_TYPES = {ITEM_LIVE_PHOTO, ITEM_SCREENSHOT, ITEM_NUMBER, ITEM_TEXT}

# ---- Original staff submission status ----
SUB_PENDING = "Pending"
SUB_ON_TIME = "Submitted On Time"
SUB_LATE = "Submitted Late"
SUB_NOT_SUBMITTED = "Not Submitted"
SUB_CLOSED = "Closed Day"

# ---- Checklist result ----
RESULT_ALL_COMPLETE = "All Complete"
RESULT_ISSUE = "Issue Reported"

# ---- Evidence status ----
EV_COMPLETE = "Complete"
EV_MISSING = "Missing Proof"
EV_REVIEW = "Review Recommended"
EV_DUPLICATE = "Possible Duplicate"

# ---- Resolution status ----
RES_NONE = "No Resolution Needed"
RES_STILL_INCOMPLETE = "Still Incomplete"
RES_LATE_BY_STAFF = "Completed Late by Assigned Staff"
RES_RECOVERED_OIC = "Recovered by Store OIC"
RES_RESOLVED_ADMIN = "Resolved by Admin"
RES_CLOSED_NO_RECOVERY = "Closed Without Recovery"

# ---- Capture sources ----
CAP_LIVE = "Live Camera"
CAP_GALLERY = "Gallery Fallback"

# ---- Metadata results (section 13) ----
META_LIVE = "Live Camera Capture"
META_MATCHED = "Metadata Matched"
META_UNAVAILABLE = "Metadata Unavailable"
META_MISMATCH = "Metadata Mismatch"
META_REVIEW = "Review Recommended"
META_DUPLICATE = "Possible Duplicate"

# ---- Schedule status ----
DAY_OPEN = "OPEN"
DAY_CLOSED = "CLOSED"

# ---- Settings keys (Settings tab) ----
SETTING_OIC_RECOVERY_DAYS = "oic_recovery_days"
SETTING_DAILY_SUMMARY_TIME = "daily_summary_time"
SETTING_WEEKLY_SCHEDULE_REMINDER = "weekly_schedule_reminder"   # "SUN 18:00"
SETTING_WEEKLY_REPORT_DAY = "weekly_report_day"                 # e.g. "MON 09:00"
SETTING_EVIDENCE_RETENTION_DAYS = "evidence_retention_days"
SETTING_RANDOM_SPOT_CHECKS = "random_spot_checks_enabled"
SETTING_EMERGENCY_TAKEOVER = "emergency_takeover_enabled"
# When true, the admin gets an instant summary + the evidence photos the moment
# a checklist is submitted (not just the midnight daily summary).
SETTING_AUTO_SEND_ON_SUBMIT = "auto_send_evidence_on_submit"

SETTING_DEFAULTS = {
    SETTING_OIC_RECOVERY_DAYS: "7",
    SETTING_DAILY_SUMMARY_TIME: "00:05",
    SETTING_WEEKLY_SCHEDULE_REMINDER: "SUN 18:00",
    SETTING_WEEKLY_REPORT_DAY: "MON 09:00",
    SETTING_EVIDENCE_RETENTION_DAYS: "90",
    SETTING_RANDOM_SPOT_CHECKS: "false",
    SETTING_EMERGENCY_TAKEOVER: "false",
    SETTING_AUTO_SEND_ON_SUBMIT: "true",
}

# Days-of-week helpers
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
