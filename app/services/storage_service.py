"""
Evidence storage abstraction (spec section 40/41: "wrap storage so it can be
replaced later").

Two backends, chosen by STORAGE_BACKEND:
  * "local"  — store files on the server's disk (default). Works with a personal
               Google account. On the Droplet this lives on a persistent Docker
               volume so evidence survives redeploys.
  * "drive"  — Google Drive (only works with a Workspace Shared Drive, because
               plain service accounts have no Drive storage quota).

Public API (same shape for both backends):
    save_bytes(data, filename, mime_type, date, task_type) -> {file_id, storage_path}
    read_bytes(file_id) -> bytes
    delete(file_id) -> None
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import date
from pathlib import Path

from app.config import get_settings


def _backend() -> str:
    return get_settings().storage_backend.lower()


def _base_dir() -> Path:
    p = Path(get_settings().storage_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(filename: str) -> str:
    base = os.path.basename(filename or "upload.jpg")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "upload.jpg"


def save_bytes(data: bytes, filename: str, mime_type: str, d: date, task_type: str) -> dict:
    if _backend() == "drive":
        from app.services import drive_service
        return drive_service.upload_bytes(data, filename, mime_type, d, task_type)

    safe_type = task_type.replace(" ", "_").upper()
    rel = f"{d:%Y}/{d:%m}/{d.isoformat()}/{safe_type}/{uuid.uuid4().hex[:8]}_{_safe_name(filename)}"
    full = _base_dir() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return {"file_id": rel, "storage_path": rel}


def read_bytes(file_id: str) -> bytes:
    if _backend() == "drive":
        from app.services import drive_service
        return drive_service.download_bytes(file_id)
    return (_base_dir() / file_id).read_bytes()


def delete(file_id: str) -> None:
    if _backend() == "drive":
        from app.services import drive_service
        drive_service.delete_file(file_id)
        return
    try:
        (_base_dir() / file_id).unlink()
    except FileNotFoundError:
        pass
