"""A weekly task created mid-week must NOT backfill an occurrence whose cutoff
already passed (which would be instantly flagged 'missed'). Regression for the
Nov-2026 false 'Weekly checklist missed' alert."""
from app import clock
from app.services import weekly_service as ws


def _def(wid, time, cutoff):
    wd = clock.today().strftime("%a").upper()  # occurrence == today
    return {"Weekly ID": wid, "Title": f"T{wid}", "Weekday": wd,
            "Time": time, "Cutoff Time": cutoff, "Default Doer Staff ID": ""}


def test_skips_occurrence_whose_cutoff_already_passed(monkeypatch):
    added = []
    monkeypatch.setattr(ws.repo, "active_defs",
                        lambda: [_def("PAST", "00:00", "00:01"),   # cutoff ~midnight → passed
                                 _def("FUT", "23:58", "23:59")])    # cutoff tonight → future
    monkeypatch.setattr(ws.repo, "instance_for", lambda wid, d: None)
    monkeypatch.setattr(ws.staff_repo, "get_by_staff_id", lambda sid: None)
    monkeypatch.setattr(ws.repo, "add_instance", lambda **kw: added.append(kw["weekly_id"]))

    ws.ensure_instances(clock.today())
    assert "PAST" not in added     # not backfilled
    assert "FUT" in added          # future occurrence still created
