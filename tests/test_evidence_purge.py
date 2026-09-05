"""Evidence retention purge: delete image FILES older than N days, keep the row."""
from datetime import timedelta

from app import clock
from app.repositories import evidence_repo
from app.services import evidence_service, storage_service


def _iso_days_ago(n):
    return clock.iso(clock.now() - timedelta(days=n))


def _wire(monkeypatch, rows):
    deleted, updated = [], []
    monkeypatch.setattr(evidence_repo, "all_rows", lambda: rows)
    monkeypatch.setattr(evidence_repo, "update", lambda eid, ch: updated.append((eid, ch)) or True)
    monkeypatch.setattr(storage_service, "delete", lambda path: deleted.append(path))
    return deleted, updated


def test_purges_only_files_older_than_window(monkeypatch):
    rows = [
        {"Evidence ID": "EV1", "Storage Path": "2026/07/old.jpg", "Uploaded At": _iso_days_ago(60)},
        {"Evidence ID": "EV2", "Storage Path": "2026/09/new.jpg", "Uploaded At": _iso_days_ago(10)},
    ]
    deleted, updated = _wire(monkeypatch, rows)
    n = evidence_service.purge_old(50)
    assert n == 1
    assert deleted == ["2026/07/old.jpg"]          # only the old file deleted
    assert updated == [("EV1", {"Storage Path": ""})]  # row kept, path cleared


def test_skips_already_purged_rows(monkeypatch):
    rows = [{"Evidence ID": "EV1", "Storage Path": "", "Uploaded At": _iso_days_ago(90)}]
    deleted, updated = _wire(monkeypatch, rows)
    assert evidence_service.purge_old(50) == 0 and deleted == [] and updated == []


def test_keeps_records_never_deletes_row(monkeypatch):
    # purge must NOT call evidence_repo.delete (which removes the audit row).
    called = {"delete": 0}
    monkeypatch.setattr(evidence_repo, "delete", lambda *a: called.__setitem__("delete", called["delete"] + 1))
    rows = [{"Evidence ID": "EV1", "Storage Path": "old.jpg", "Uploaded At": _iso_days_ago(80)}]
    _wire(monkeypatch, rows)
    evidence_service.purge_old(50)
    assert called["delete"] == 0  # row preserved, only the file removed
