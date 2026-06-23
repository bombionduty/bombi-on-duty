"""
Evidence processing (spec sections 11-15).

Responsibilities:
  * Add a small visible footer to live photos (review aid only).
  * Compute exact + perceptual hashes.
  * Read EXIF capture time when available.
  * Decide a metadata result (Live / Matched / Unavailable / Review / Duplicate).
  * Detect duplicate / near-duplicate images against recent evidence.
  * Upload to Google Drive and record the Evidence row.

Accountability rule: metadata is a *signal*, never the sole source of truth.
The authenticated user + server timestamp + capture source are authoritative.
"""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime

import imagehash
import piexif
from PIL import Image, ImageDraw, ImageFont

from app import clock, constants
from app.repositories import evidence_repo

log = logging.getLogger(__name__)

# Perceptual-hash hamming distance under which we treat two images as "similar".
_PHASH_SIMILAR_THRESHOLD = 6


# --------------------------------------------------------------------------
def _exact_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_image(data: bytes) -> Image.Image | None:
    try:
        return Image.open(io.BytesIO(data))
    except Exception:
        return None


def _perceptual_hash(img: Image.Image | None) -> str:
    if img is None:
        return ""
    try:
        return str(imagehash.phash(img.convert("RGB")))
    except Exception:
        return ""


def _exif_datetime(data: bytes) -> datetime | None:
    try:
        exif = piexif.load(data)
        raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if not raw:
            raw = exif.get("0th", {}).get(piexif.ImageIFD.DateTime)
        if not raw:
            return None
        return datetime.strptime(raw.decode(), "%Y:%m:%d %H:%M:%S").replace(tzinfo=clock.tz())
    except Exception:
        return None


_MAX_DIM = 1280       # downscale longest side; plenty for review, small files
_JPEG_QUALITY = 72    # good readability at a fraction of the size


def _downscale_bytes(data: bytes) -> bytes:
    """Shrink + compress phone photos/screenshots so they're fast to upload and
    cheap to store. Always re-encodes to JPEG (even if already small) to strip
    bloat; stays perfectly readable for evidence review."""
    img = _open_image(data)
    if img is None:
        return data
    img = img.convert("RGB")
    if max(img.size) > _MAX_DIM:
        img.thumbnail((_MAX_DIM, _MAX_DIM))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    compressed = out.getvalue()
    # Never make it bigger than the original.
    return compressed if len(compressed) < len(data) else data


def add_footer(data: bytes, checklist_type: str, staff_name: str) -> bytes:
    """Burn a footer like 'Closing Check • June 22, 2026 • 11:43 PM • Allyssa'."""
    img = _open_image(data)
    if img is None:
        return data
    img = img.convert("RGB")
    now = clock.now()
    label = (
        f"{checklist_type} • {clock.fmt_date(now.date())} "
        f"• {clock.fmt_time(now)} • {staff_name}"
    )
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(14, img.width // 45))
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 8
    y0 = img.height - th - pad * 2
    draw.rectangle([0, y0, img.width, img.height], fill=(0, 0, 0))
    draw.text((pad, y0 + pad), label, fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue()


def _find_duplicate(exact: str, phash: str, ignore_task_id: str) -> dict | None:
    for prev in evidence_repo.recent():
        if prev.get("Task ID") == ignore_task_id:
            continue
        if exact and str(prev.get("Exact Hash")) == exact:
            return prev
        prev_phash = str(prev.get("Perceptual Hash") or "")
        if phash and prev_phash:
            try:
                dist = imagehash.hex_to_hash(phash) - imagehash.hex_to_hash(prev_phash)
                if dist <= _PHASH_SIMILAR_THRESHOLD:
                    return prev
            except Exception:
                pass
    return None


def _metadata_result(item_type: str, capture_source: str, exif_dt: datetime | None) -> str:
    if capture_source == constants.CAP_LIVE:
        return constants.META_LIVE
    # Gallery upload:
    if item_type == constants.ITEM_LIVE_PHOTO:
        # A live-photo item satisfied via gallery fallback always deserves a look.
        return constants.META_REVIEW
    if exif_dt is None:
        return constants.META_UNAVAILABLE
    return constants.META_MATCHED


def process_and_store(
    *,
    task: dict,
    task_item: dict,
    data: bytes,
    filename: str,
    mime_type: str,
    capture_source: str,
    submitted_by: dict,
    submitted_by_role: str,
    on_behalf_of_staff_id: str = "",
) -> dict:
    """Process, upload, and record one piece of image/screenshot evidence.

    Returns the stored Evidence row (with keys 'Metadata Result',
    'Possible Duplicate', 'Review Status' filled in).
    """
    from app.services import storage_service  # local import avoids cycle at import time

    operating_date = clock.parse_date(str(task["Date"]))
    item_type = str(task_item.get("Item Type"))

    # Downscale first (fast hashing + small upload), then footer for live photos.
    stored_bytes = _downscale_bytes(data)
    if item_type == constants.ITEM_LIVE_PHOTO and capture_source == constants.CAP_LIVE:
        stored_bytes = add_footer(stored_bytes, str(task["Checklist Type"]),
                                  str(task["Assigned Staff Name"]))

    img = _open_image(stored_bytes)
    exact = _exact_hash(stored_bytes)
    phash = _perceptual_hash(img)
    exif_dt = _exif_datetime(data)

    duplicate = _find_duplicate(exact, phash, str(task["Task ID"]))
    meta_result = _metadata_result(item_type, capture_source, exif_dt)
    review_status = ""
    if duplicate:
        meta_result = constants.META_DUPLICATE
        review_status = "Review Required"
    elif meta_result == constants.META_REVIEW:
        review_status = "Review Recommended"

    # Save to the configured storage backend (local disk by default).
    up = storage_service.save_bytes(
        stored_bytes, filename, mime_type, operating_date, str(task["Checklist Type"])
    )

    row = evidence_repo.add({
        "Task ID": task["Task ID"],
        "Task Item ID": task_item["Task Item ID"],
        "Evidence Type": item_type,
        "Storage Path": up["storage_path"],
        "Drive File ID": up["file_id"],
        "Original Filename": filename,
        "MIME Type": mime_type,
        "File Size": len(stored_bytes),
        "Original Assigned Staff ID": task.get("Assigned Staff ID", ""),
        "Submitted By Staff ID": submitted_by.get("Staff ID", ""),
        "Submitted By Telegram User ID": str(submitted_by.get("Telegram User ID", "")),
        "Submitted By Role": submitted_by_role,
        "Submitted On Behalf Of Staff ID": on_behalf_of_staff_id,
        "Uploaded At": clock.iso(clock.now()),
        "Capture Source": capture_source,
        "EXIF Date": clock.iso(exif_dt) if exif_dt else "",
        "Metadata Result": meta_result,
        "Exact Hash": exact,
        "Perceptual Hash": phash,
        "Possible Duplicate": bool(duplicate),
        "Matching Evidence ID": duplicate.get("Evidence ID", "") if duplicate else "",
        "Review Status": review_status,
    })
    row["_duplicate_of"] = duplicate  # convenience for caller alerts
    return row
