"""Droplet storage/health checks. The evidence dir lives on a Docker volume
backed by the host filesystem, so disk_usage() there reports the HOST disk —
the same 8.65 GB that filled up and broke things. Used for the /diskspace
command and a daily low-disk warning."""
from __future__ import annotations

import logging
import os
import shutil

from app.config import get_settings

log = logging.getLogger(__name__)

_GB = 1024 ** 3
WARN_PERCENT = 85  # alert the admin at/above this usage


def disk_report() -> dict:
    """Host disk usage, measured via the evidence volume mount."""
    path = get_settings().storage_dir or "/app/data"
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = "/"
    total, used, free = shutil.disk_usage(path)
    return {
        "total_gb": total / _GB,
        "used_gb": used / _GB,
        "free_gb": free / _GB,
        "percent": (used / total * 100) if total else 0.0,
    }


def format_report(r: dict) -> str:
    pct = r["percent"]
    icon = "🟢" if pct < 70 else ("🟠" if pct < WARN_PERCENT else "🔴")
    return (
        f"💾 <b>Droplet storage</b>\n\n"
        f"{icon} Used: <b>{r['used_gb']:.1f} GB / {r['total_gb']:.1f} GB "
        f"({pct:.0f}%)</b>\n"
        f"Free: <b>{r['free_gb']:.1f} GB</b>"
        + ("\n\n⚠️ Getting full — on the droplet run "
           "<code>docker system prune -af</code> to reclaim space."
           if pct >= WARN_PERCENT else "")
    )
