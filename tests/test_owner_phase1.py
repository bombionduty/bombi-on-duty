"""Phase 1 Owner Mode tests — pure logic (parser, bucketing, messages)."""
from datetime import timedelta

from app import clock
from app.owner import constants as oc
from app.owner import messages, parser, service


def test_parser_splits_multiple_tasks():
    tasks = parser.parse("film the biscoff video tomorrow and pay electricity on the 28th")
    assert len(tasks) == 2
    titles = " ".join(t["title"].lower() for t in tasks)
    assert "biscoff" in titles and "electricity" in titles


def test_parser_tomorrow_date():
    t = parser.parse("count the envelopes tomorrow")[0]
    assert t["due"] == (clock.today() + timedelta(days=1)).isoformat()


def test_parser_no_date_is_blank():
    t = parser.parse("organize the storage room")[0]
    assert t["due"] == ""


def test_parser_recurrence_every_sunday():
    t = parser.parse("every sunday submit the weekly OR")[0]
    assert t["recurrence"].startswith("weekly")


def test_resolve_when():
    today = clock.today()
    assert service.resolve_when("today") == today
    assert service.resolve_when("tom") == today + timedelta(days=1)
    assert service.resolve_when("2d") == today + timedelta(days=2)
    assert service.resolve_when("none") is None


def test_bucket_for():
    today = clock.today()
    assert service.bucket_for({"Status": oc.ST_OPEN, "Due Date": (today - timedelta(days=1)).isoformat()}) == oc.B_OVERDUE
    assert service.bucket_for({"Status": oc.ST_OPEN, "Due Date": today.isoformat()}) == oc.B_DUE_TODAY
    assert service.bucket_for({"Status": oc.ST_OPEN, "Due Date": (today + timedelta(days=3)).isoformat()}) == oc.B_UPCOMING
    assert service.bucket_for({"Status": oc.ST_OPEN, "Due Date": ""}) == oc.B_UPCOMING
    assert service.bucket_for({"Status": oc.ST_WAITING}) == oc.B_WAITING
    assert service.bucket_for({"Status": oc.ST_COMPLETED}) == oc.B_COMPLETED
    assert service.bucket_for({"Status": oc.ST_SKIPPED}) is None


def test_messages_build_without_error():
    parsed = parser.parse("pay rent on the 30th and film a video tomorrow")
    assert "task" in messages.confirm_card(parsed).lower()
    buckets = {b: [] for b in (oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING, oc.B_WAITING, oc.B_COMPLETED)}
    assert "BOMBI ADMIN" in messages.dashboard_text(buckets)
    assert "CLEAR" in messages.daily_summary("Lesha", buckets).upper()
