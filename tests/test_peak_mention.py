"""The closing group card must @-mention (ping) the peak support, not just show
their name as plain text."""
from app import constants
from app.services import task_service as ts
from app.telegram import messages


def test_with_mention_builds_peak_mention(monkeypatch):
    monkeypatch.setattr(ts.staff_repo, "get_by_staff_id",
                        lambda sid: {"Telegram Username": "miles_u"})
    task = {"Assigned Staff ID": "A", "Assigned Staff Name": "Allyssa",
            "Assigned Telegram User ID": "100", "Peak Staff ID": "P",
            "Peak Staff Name": "Miles", "Peak Telegram User ID": "200"}
    t = ts.with_mention(task)
    assert t["_peak_mention"] == "@miles_u"


def test_card_pings_peak(monkeypatch):
    monkeypatch.setattr(ts.staff_repo, "get_by_staff_id",
                        lambda sid: {"Telegram Username": "miles_u"})
    task = {"Checklist Type": constants.CHECK_CLOSING,
            "Assigned Staff ID": "A", "Assigned Staff Name": "Allyssa",
            "Assigned Telegram User ID": "100", "Peak Staff ID": "P",
            "Peak Staff Name": "Miles", "Peak Telegram User ID": "200",
            "Cutoff At": "", "Original Submission Status": constants.SUB_PENDING}
    card = messages.group_card(ts.with_mention(task), "closer")
    assert "@miles_u" in card and "Peak support" in card


def test_peak_mention_falls_back_to_link(monkeypatch):
    # No username → a tg://user link that still pings.
    monkeypatch.setattr(ts.staff_repo, "get_by_staff_id", lambda sid: {})
    t = ts.with_mention({"Peak Staff ID": "P", "Peak Staff Name": "Miles",
                         "Peak Telegram User ID": "200"})
    assert 'tg://user?id=200' in t["_peak_mention"]
