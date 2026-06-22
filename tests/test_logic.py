"""Pure business-logic tests (status model, messages, summary)."""
from app import constants
from app.telegram import messages
from app.services.summary_service import _overall


def _task(**kw):
    base = {
        "Checklist Type": constants.CHECK_CLOSING,
        "Assigned Staff Name": "Allyssa",
        "Cutoff At": "2026-06-22T23:55:00+08:00",
        "Original Submission Status": constants.SUB_PENDING,
        "Resolution Status": constants.RES_NONE,
    }
    base.update(kw)
    return base


def test_group_card_pending():
    text = messages.group_card(_task(), "closer")
    assert "Closing Check" in text
    assert "Pending" in text
    assert "Allyssa" in text


def test_group_card_not_submitted_shows_missing():
    t = _task(Original_Submission_Status=constants.SUB_NOT_SUBMITTED)
    t["Original Submission Status"] = constants.SUB_NOT_SUBMITTED
    t["_missing_text"] = "Final sales log screenshot"
    text = messages.group_card(t, "closer")
    assert "Not Submitted" in text
    assert "Final sales log screenshot" in text


def test_group_card_recovered():
    t = _task()
    t["Original Submission Status"] = constants.SUB_NOT_SUBMITTED
    t["Resolution Status"] = constants.RES_RECOVERED_OIC
    t["Recovered At"] = "2026-06-23T09:15:00+08:00"
    text = messages.group_card(t, "closer")
    assert "Recovered by Store OIC" in text
    assert "Original Status: Not Submitted" in text


def test_overall_status_variants():
    on_time = [{"Original Submission Status": constants.SUB_ON_TIME,
                "Resolution Status": constants.RES_NONE,
                "Checklist Result": constants.RESULT_ALL_COMPLETE}]
    assert _overall(on_time) == "Complete"

    with_issue = [{"Original Submission Status": constants.SUB_ON_TIME,
                   "Resolution Status": constants.RES_NONE,
                   "Checklist Result": constants.RESULT_ISSUE}]
    assert _overall(with_issue) == "Complete with Issues"

    not_sub = [{"Original Submission Status": constants.SUB_NOT_SUBMITTED,
                "Resolution Status": constants.RES_STILL_INCOMPLETE,
                "Checklist Result": ""}]
    assert _overall(not_sub) == "Incomplete"

    recovered = [{"Original Submission Status": constants.SUB_NOT_SUBMITTED,
                  "Resolution Status": constants.RES_RECOVERED_OIC,
                  "Checklist Result": ""}]
    assert _overall(recovered) == "Incomplete but Recovered"

    closed = [{"Original Submission Status": constants.SUB_CLOSED,
               "Resolution Status": constants.RES_NONE, "Checklist Result": ""}]
    assert _overall(closed) == "Closed Day"
