"""Admin-completes-a-missed-checklist: the group card flips from 'Not Submitted'
to a completed-late state naming who finished it (Feature: admin override)."""
from app import constants
from app.telegram import messages


def _base(**over):
    t = {
        "Checklist Type": constants.CHECK_CLOSING,
        "Assigned Staff Name": "Carol", "Cutoff At": "2026-06-22T23:00:00",
        "Checklist Result": constants.RESULT_ALL_COMPLETE,
        "Evidence Status": constants.EV_COMPLETE,
    }
    t.update(over)
    return t


def test_not_submitted_then_completed_late_by_admin():
    t = _base(**{
        "Original Submission Status": constants.SUB_NOT_SUBMITTED,
        "Resolution Status": constants.RES_LATE_BY_STAFF,
        "Submitted At": "2026-06-23T01:15:00",
        "Submitted By Name": "Admin",
    })
    card = messages.group_card(t, "closer")
    assert "Completed late" in card
    assert "Submitted by: Admin" in card
    assert "Not Submitted" not in card  # no longer shown as missing


def test_still_missing_card_unchanged_when_not_completed():
    t = _base(**{
        "Original Submission Status": constants.SUB_NOT_SUBMITTED,
        "Resolution Status": constants.RES_STILL_INCOMPLETE,
        "_missing_text": "Trash out",
    })
    card = messages.group_card(t, "closer")
    assert "Not Submitted" in card
    assert "Trash out" in card


def test_admin_complete_card():
    t = _base(**{
        "Original Submission Status": constants.SUB_ON_TIME,
        "Resolution Status": constants.RES_RESOLVED_ADMIN,
        "Submitted At": "2026-06-23T01:15:00",
        "Submitted By Name": "Admin",
    })
    card = messages.group_card(t, "closer")
    assert "Submitted by Admin — Complete" in card
    assert "✅" in card


def test_admin_incomplete_card_lists_not_submitted_items():
    t = _base(**{
        "Original Submission Status": constants.SUB_NOT_SUBMITTED,
        "Resolution Status": constants.RES_RESOLVED_ADMIN,
        "Submitted At": "2026-06-23T01:15:00",
        "Submitted By Name": "Admin",
        "_missing_text": "Photo of sales, Mop water emptied",
    })
    card = messages.group_card(t, "closer")
    assert "Submitted by Admin — Incomplete" in card
    assert "Not submitted: Photo of sales, Mop water emptied" in card
    assert "⚠️" in card


def test_on_time_card_names_submitter():
    t = _base(**{
        "Original Submission Status": constants.SUB_ON_TIME,
        "Submitted At": "2026-06-22T22:40:00",
        "Submitted By Name": "Pia",
    })
    card = messages.group_card(t, "closer")
    assert "Submitted by: Pia" in card
