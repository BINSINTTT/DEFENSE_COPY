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

from severity.assess import assess_severity, decode_image, segment_leaf  # noqa: E402
from severity.thresholds import band_for_affected_pct  # noqa: E402


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


def test_bands_remain_compatible_with_the_interface():
    assert band_for_affected_pct(0) == "Healthy"
    assert band_for_affected_pct(33) == "Mild"
    assert band_for_affected_pct(34) == "Moderate"
    assert band_for_affected_pct(67) == "Severe"
