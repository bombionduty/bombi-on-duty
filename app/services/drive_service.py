"""
Google Drive evidence storage (spec section 41).

Folder layout:
  Berry Bomb Ops Evidence / YYYY / MM / YYYY-MM-DD / TASK_TYPE / file

Files are NOT made public. The backend downloads bytes on demand for the admin
Mini App gallery and "Send Evidence Here". We cache folder IDs so we don't
re-create the same date folders repeatedly.
"""
from __future__ import annotations

import io
import logging
from datetime import date

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.config import get_settings
from app.sheets.client import build_credentials

log = logging.getLogger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"
_service = None
_folder_cache: dict[str, str] = {}


def _drive():
    global _service
    if _service is None:
        _service = build("drive", "v3", credentials=build_credentials(), cache_discovery=False)
    return _service


def _find_or_create_folder(name: str, parent_id: str) -> str:
    cache_key = f"{parent_id}/{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]
    safe = name.replace("'", "\\'")
    q = (
        f"name = '{safe}' and mimeType = '{_FOLDER_MIME}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    res = _drive().files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        fid = files[0]["id"]
    else:
        meta = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
        fid = _drive().files().create(body=meta, fields="id").execute()["id"]
    _folder_cache[cache_key] = fid
    return fid


def folder_for(d: date, task_type: str) -> str:
    """Return the Drive folder id for an operating date + checkpoint."""
    root = get_settings().google_drive_evidence_folder_id
    year = _find_or_create_folder(f"{d:%Y}", root)
    month = _find_or_create_folder(f"{d:%m}", year)
    day = _find_or_create_folder(d.isoformat(), month)
    return _find_or_create_folder(task_type.replace(" ", "_").upper(), day)


def upload_bytes(
    data: bytes, filename: str, mime_type: str, d: date, task_type: str
) -> dict:
    """Upload evidence bytes. Returns {file_id, storage_path}."""
    parent = folder_for(d, task_type)
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    meta = {"name": filename, "parents": [parent]}
    f = _drive().files().create(body=meta, media_body=media, fields="id, name").execute()
    storage_path = f"{d:%Y}/{d:%m}/{d.isoformat()}/{task_type.replace(' ', '_').upper()}/{filename}"
    return {"file_id": f["id"], "storage_path": storage_path}


def download_bytes(file_id: str) -> bytes:
    """Securely download a file's bytes (used for gallery + Send Evidence Here)."""
    request = _drive().files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def delete_file(file_id: str) -> None:
    _drive().files().delete(fileId=file_id).execute()
