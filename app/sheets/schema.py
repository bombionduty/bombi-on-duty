"""
Google Sheets schema (spec section 40).

Single source of truth for every tab name and its column headers. The setup
script (scripts/setup_sheet.py) uses this to create the workbook, and the
repository layer uses it so a column rename only happens in ONE place.

Order matters: the header list defines the column order in the sheet.
"""
from __future__ import annotations

STAFF = "Staff"
SCHEDULE = "Schedule"
CHECKLIST_TEMPLATES = "Checklist Templates"
CHECKLIST_TIMING = "Checklist Timing"
TIMING_OVERRIDES = "Timing Overrides"
TASKS = "Tasks"
TASK_ITEMS = "Task Items"
EVIDENCE = "Evidence"
OIC_RECOVERIES = "OIC Recoveries"
NOTES = "Notes"
ANNOUNCEMENTS = "Announcements"
ACKNOWLEDGEMENTS = "Acknowledgements"
OIC_REVIEWS = "OIC Reviews"
SETTINGS = "Settings"
AUDIT_LOG = "Audit Log"

HEADERS: dict[str, list[str]] = {
    STAFF: [
        "Staff ID", "Staff Name", "Telegram User ID", "Telegram Username",
        "Role", "Active", "Private Bot Started", "Date Added",
        "Date Deactivated", "Notes",
    ],
    SCHEDULE: [
        "Date", "Day", "Status", "Opener Staff ID", "Opener Name",
        "Closer Staff ID", "Closer Name", "Notes", "Created At", "Updated At",
    ],
    CHECKLIST_TEMPLATES: [
        "Item ID", "Checklist Type", "Item Name", "Instructions", "Item Type",
        "Required", "Active", "Sort Order", "Effective From", "Effective Until",
        "Days of Week", "Minimum Value", "Maximum Value", "Unit",
        "Created By", "Created At", "Updated At",
    ],
    CHECKLIST_TIMING: [
        "Checklist Type", "Day Type", "Release Time", "Staff Reminder Times",
        "OIC Escalation Time", "Cutoff Time", "Active", "Updated At",
    ],
    TIMING_OVERRIDES: [
        "Date", "Checklist Type", "Release Time", "Staff Reminder Times",
        "OIC Escalation Time", "Cutoff Time", "Notes",
    ],
    TASKS: [
        "Task ID", "Task Key", "Task Token Hash", "Date", "Checklist Type",
        "Assigned Staff ID", "Assigned Staff Name", "Assigned Telegram User ID",
        "Release At", "Cutoff At", "Initial Message ID", "Staff Group Chat ID",
        "OIC Alert Message ID", "Daily Summary Message ID", "Started At",
        "Submitted At", "Original Submission Status", "Checklist Result",
        "Evidence Status", "Resolution Status", "Not Submitted At",
        "Review Required", "Recovered By Staff ID", "Recovered By Telegram User ID",
        "Recovered At", "Current Version", "Created At", "Updated At",
    ],
    TASK_ITEMS: [
        "Task Item ID", "Task ID", "Template Item ID", "Item Name",
        "Instructions", "Item Type", "Required", "Sort Order", "Response",
        "Issue Reported", "Issue Details", "Completed", "Completed At",
        "Missing At Cutoff", "Recovered", "Recovered At",
    ],
    EVIDENCE: [
        "Evidence ID", "Task ID", "Task Item ID", "Evidence Type",
        "Storage Path", "Drive File ID", "Original Filename", "MIME Type",
        "File Size", "Original Assigned Staff ID", "Submitted By Staff ID",
        "Submitted By Telegram User ID", "Submitted By Role",
        "Submitted On Behalf Of Staff ID", "Uploaded At", "Capture Source",
        "EXIF Date", "Metadata Result", "Exact Hash", "Perceptual Hash",
        "Possible Duplicate", "Matching Evidence ID", "Review Status",
    ],
    OIC_RECOVERIES: [
        "Recovery ID", "Task ID", "Operating Date", "Original Assigned Staff ID",
        "Original Assigned Staff Name", "Original Status", "Missing Items at Cutoff",
        "OIC Staff ID", "OIC Name", "OIC Telegram User ID", "Recovery Reason",
        "Recovery Notes", "Recovery Submitted At", "Resolution Status",
    ],
    NOTES: [
        "Note ID", "Timestamp", "Date", "Reported By Staff ID",
        "Reported By Name", "Reported By Telegram User ID", "Note",
        "Related Task ID", "Follow-Up Status",
    ],
    ANNOUNCEMENTS: [
        "Announcement ID", "Message", "Posted At", "Posted By",
        "Telegram Message ID", "Active",
    ],
    ACKNOWLEDGEMENTS: [
        "Announcement ID", "Staff ID", "Staff Name", "Telegram User ID",
        "Acknowledged At",
    ],
    OIC_REVIEWS: [
        "Review ID", "Task ID", "Evidence ID", "Assigned OIC Staff ID",
        "Review Reason", "Review Status", "Reviewer Telegram User ID",
        "Review Notes", "Requested At", "Reviewed At",
    ],
    SETTINGS: [
        "Setting Key", "Setting Value", "Description", "Updated At", "Updated By",
    ],
    AUDIT_LOG: [
        "Audit ID", "Timestamp", "Actor Telegram User ID", "Actor Name",
        "Actor Role", "Action", "Entity Type", "Entity ID",
        "Original Assigned Staff ID", "Previous Value", "New Value", "Reason",
    ],
}

# Convenient ordered list of all tabs.
ALL_TABS = list(HEADERS.keys())
