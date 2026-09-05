"""Disk report + low-disk warning formatting."""
from app.services import system_service as sys_svc


def test_disk_report_shape(monkeypatch):
    monkeypatch.setattr(sys_svc.shutil, "disk_usage",
                        lambda p: (100 * 1024**3, 80 * 1024**3, 20 * 1024**3))
    monkeypatch.setattr(sys_svc.os, "makedirs", lambda *a, **k: None)
    r = sys_svc.disk_report()
    assert round(r["total_gb"]) == 100 and round(r["used_gb"]) == 80
    assert round(r["free_gb"]) == 20 and round(r["percent"]) == 80


def test_format_warns_when_full():
    high = {"total_gb": 8.6, "used_gb": 8.0, "free_gb": 0.6, "percent": 93}
    out = sys_svc.format_report(high)
    assert "🔴" in out and "prune" in out and "93%" in out


def test_format_healthy_no_warning():
    low = {"total_gb": 8.6, "used_gb": 3.0, "free_gb": 5.6, "percent": 35}
    out = sys_svc.format_report(low)
    assert "🟢" in out and "prune" not in out
