"""OpenCV severity must use symptom area, not AI confidence."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from severity.assess import (  # noqa: E402
    _apply_orientation,
    _jpeg_orientation,
    _limit_long_edge,
    assess_severity,
    decode_image,
    decode_leaf_mask,
    segment_leaf,
)
from severity.thresholds import band_for_affected_pct  # noqa: E402
from leaf_preprocessing import isolate_leaf  # noqa: E402


def _encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def _leaf_image(symptom_color: tuple[int, int, int] | None = None) -> bytes:
    size = 260
    image = np.full((size, size, 3), 25, dtype=np.uint8)
    center = (size // 2, size // 2)
    axes = (82, 112)
    cv2.ellipse(image, center, axes, 0, 0, 360, (40, 160, 40), -1)
    if symptom_color is not None:
        cv2.circle(image, (center[0], center[1] - 20), 34, symptom_color, -1)
    return _encode(image)


def test_healthy_leaf_is_zero_percent():
    result = assess_severity(_leaf_image(), "healthy")
    assert result["ok"] is True
    assert result["measurable"] is True
    assert result["severity"] == "Healthy"
    assert result["severity_pct"] == 0.0
    assert result["source"] == "opencv_color_segmentation"


@pytest.mark.parametrize(
    ("disease", "symptom_color"),
    (
        ("early_blight", (30, 70, 140)),  # brown lesion
        ("tlcv", (20, 220, 220)),  # yellow chlorosis
        ("spotted_wilt", (150, 60, 120)),  # purple/bronze lesion
    ),
)
def test_diseases_get_opencv_area_values(disease, symptom_color):
    result = assess_severity(_leaf_image(symptom_color), disease)
    assert result["ok"] is True
    assert result["measurable"] is True
    assert result["severity_pct"] is not None
    assert result["severity_pct"] > 0
    assert result["severity"] in {"Mild", "Moderate", "Severe"}
    assert result["reason"] == f"{disease}_opencv_estimate"


def test_decode_and_leaf_segmentation():
    decoded = decode_image(_leaf_image())
    assert decoded is not None
    mask, reason = segment_leaf(decoded)
    assert reason == ""
    assert mask is not None
    assert cv2.countNonZero(mask) > 0


def test_isolated_leaf_mask_is_reused_for_severity():
    image = np.full((260, 360, 3), 25, dtype=np.uint8)
    cv2.ellipse(image, (190, 130), (84, 108), 0, 0, 360, (40, 160, 40), -1)
    cv2.circle(image, (190, 110), 22, (30, 70, 140), -1)
    cv2.ellipse(image, (40, 130), (25, 75), 0, 0, 360, (40, 160, 40), -1)
    isolated, reason = isolate_leaf(_encode(image))
    assert reason == ""
    assert isolated is not None
    assert isolated.mask[130, 190] == 255
    assert isolated.mask[130, 40] == 0
    result = assess_severity(_encode(image), "early_blight", leaf_mask_png=isolated.mask_png)
    assert result["measurable"] is True
    assert result["severity_pct"] > 0


def test_smaller_python_mask_is_aligned_to_original_for_severity():
    mask = np.zeros((683, 1024), dtype=np.uint8)
    cv2.ellipse(mask, (512, 341), (240, 280), 0, 0, 360, 255, -1)
    decoded = decode_leaf_mask(_encode(mask), (800, 1200))
    assert decoded is not None
    assert decoded.shape == (800, 1200)
    assert decoded[400, 600] == 255
    assert decoded[0, 0] == 0


def test_tightly_cropped_leaf_is_still_measurable():
    image = np.full((220, 220, 3), (40, 160, 40), dtype=np.uint8)
    cv2.rectangle(image, (2, 2), (217, 217), (20, 220, 220), thickness=35)
    result = assess_severity(_encode(image), "tlcv")
    assert result["measurable"] is True
    assert result["severity_pct"] is not None


def test_invalid_disease_is_rejected():
    result = assess_severity(_leaf_image(), "potato_blight")
    assert result["ok"] is False
    assert result["reason"] == "invalid_disease"


def test_phone_photo_is_turned_upright_and_limited():
    wide = np.zeros((40, 90, 3), dtype=np.uint8)
    wide[:, :30] = (40, 160, 40)
    upright = _apply_orientation(wide, 6)
    assert upright.shape[0] == 90
    assert upright.shape[1] == 40

    large = np.full((1800, 900, 3), (40, 160, 40), dtype=np.uint8)
    limited = _limit_long_edge(large, 1600)
    assert max(limited.shape[:2]) == 1600

    assert _jpeg_orientation(b"\xff\xd8\xff\xd9") == 1


def test_bands_remain_compatible_with_the_interface():
    assert band_for_affected_pct(0) == "Healthy"
    assert band_for_affected_pct(33) == "Mild"
    assert band_for_affected_pct(34) == "Moderate"
    assert band_for_affected_pct(67) == "Severe"
