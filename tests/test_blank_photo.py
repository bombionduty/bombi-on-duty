"""Blank / black-screen live-photo detection — catches staff who 'take a photo'
without aiming the camera at the task (an all-black or featureless frame)."""
import random

from PIL import Image

from app.services import evidence_service as es


def test_all_black_is_blank():
    black = Image.new("RGB", (120, 120), (0, 0, 0))
    assert es._blank_or_dark(black) is True


def test_flat_frame_is_blank():
    # A featureless frame (e.g. lens covered, solid wall) has ~zero variation.
    white = Image.new("RGB", (120, 120), (255, 255, 255))
    assert es._blank_or_dark(white) is True


def test_real_photo_passes():
    img = Image.new("RGB", (120, 120))
    rnd = random.Random(1)
    img.putdata([(rnd.randint(0, 255),) * 3 for _ in range(120 * 120)])
    assert es._blank_or_dark(img) is False


def test_dim_but_real_photo_passes():
    # Low-light but with real detail: mean ~45, plenty of variation.
    img = Image.new("RGB", (120, 120))
    rnd = random.Random(2)
    img.putdata([(rnd.randint(20, 90),) * 3 for _ in range(120 * 120)])
    assert es._blank_or_dark(img) is False


def test_none_is_not_blank():
    assert es._blank_or_dark(None) is False
