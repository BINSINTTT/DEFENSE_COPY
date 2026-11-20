"""OpenCV leaf and symptom-area severity assessment.

Disease identity comes from the trained classifiers. This module measures only
visible symptom extent and never converts classification confidence to severity.
The result is an image-processing estimate, not a clinically validated score.
"""

from __future__ import annotations

import struct
from typing import Any

import cv2
import numpy as np

from . import thresholds as thr

UNABLE = "Unable to Assess"
VALID_DISEASES = frozenset({"healthy", "early_blight", "tlcv", "spotted_wilt"})


def _normalize_disease(raw: str | None) -> str:
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "yellowleafcurlvirus": "tlcv",
        "yellow_leaf_curl": "tlcv",
        "yellow_leaf_curl_virus": "tlcv",
        "tylcv": "tlcv",
        "earlyblight": "early_blight",
        "early_blight_virus": "early_blight",
        "spottedwilt": "spotted_wilt",
        "spotted_wilt_virus": "spotted_wilt",
        "tswv": "spotted_wilt",
    }
    key = aliases.get(key, key)
    return key if key in VALID_DISEASES else ""


def _result(
    *,
    disease: str,
    severity: str,
    affected_area_pct: float | None,
    measurable: bool,
    reason: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    entry = {
        "severity": severity,
        "severity_pct": affected_area_pct,
        "affected_area_pct": affected_area_pct,
        "measurable": measurable,
        "reason": reason,
        "metric": "opencv_symptom_pixels_over_leaf_pixels",
    }
    return {
        "ok": True,
        "disease": disease,
        **entry,
        "source": "opencv_color_segmentation",
        "model": "opencv",
        "evidence": evidence or [],
        "rescan_recommended": not measurable,
        "image_quality": {"issues": [] if measurable else [reason.replace("_", " ")]},
        "disease_severities": {disease: entry} if disease else {},
        "thresholds": thr.thresholds_echo(),
    }


def _jpeg_orientation(data: bytes) -> int:
    """Read the EXIF orientation phone cameras store. OpenCV ignores it otherwise."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return 1
    offset = 2
    while offset + 4 < len(data) and data[offset] == 0xFF:
        marker = data[offset + 1]
        if marker in (0xDA, 0xD9):
            break
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if length < 2 or offset + 2 + length > len(data):
            break
        if marker == 0xE1:
            return _orientation_in_exif(data[offset + 4 : offset + 2 + length])
        offset += 2 + length
    return 1


def _orientation_in_exif(segment: bytes) -> int:
    if not segment.startswith(b"Exif\x00\x00") or len(segment) < 14:
        return 1
    tiff = segment[6:]
    if tiff.startswith(b"II"):
        endian = "<"
    elif tiff.startswith(b"MM"):
        endian = ">"
    else:
        return 1
    ifd = struct.unpack_from(endian + "I", tiff, 4)[0]
    if ifd < 0 or ifd + 2 > len(tiff):
        return 1
    count = struct.unpack_from(endian + "H", tiff, ifd)[0]
    for index in range(count):
        entry = ifd + 2 + index * 12
        if entry + 12 > len(tiff):
            break
        tag, field_type, number = struct.unpack_from(endian + "HHI", tiff, entry)
        if tag == 0x0112 and field_type == 3 and number >= 1:
            value = struct.unpack_from(endian + "H", tiff, entry + 8)[0]
            return value if 1 <= value <= 8 else 1
    return 1


def _apply_orientation(bgr: np.ndarray, orientation: int) -> np.ndarray:
    if orientation == 2:
        return cv2.flip(bgr, 1)
    if orientation == 3:
        return cv2.rotate(bgr, cv2.ROTATE_180)
    if orientation == 4:
        return cv2.flip(bgr, 0)
    if orientation == 5:
        return cv2.flip(cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), 1)
    if orientation == 6:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 7:
        return cv2.flip(cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE), 1)
    if orientation == 8:
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return bgr


def _limit_long_edge(bgr: np.ndarray, max_edge: int = 1600) -> np.ndarray:
    height, width = bgr.shape[:2]
    edge = max(height, width)
    if edge <= max_edge:
        return bgr
    scale = max_edge / float(edge)
    return cv2.resize(
        bgr,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def decode_image(image_bytes: bytes) -> np.ndarray | None:
    if not image_bytes:
        return None
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    # Phone cameras store the picture sideways and at several megapixels.
    # Turn it upright and limit the size so the same area measurement used
    # for a desktop upload also finishes for a mobile photo.
    bgr = _apply_orientation(bgr, _jpeg_orientation(image_bytes))
    return _limit_long_edge(bgr)


def decode_leaf_mask(mask_png: bytes, shape: tuple[int, int]) -> np.ndarray | None:
    """Read the Python segmentation mask at the severity image's resolution."""
    if not mask_png:
        return None
    mask = cv2.imdecode(np.frombuffer(mask_png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        return None
    height, width = shape
    if mask.shape != shape:
        mask_height, mask_width = mask.shape
        if abs(mask_width / mask_height - width / height) > 0.01:
            return None
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    binary = np.where(mask >= 128, 255, 0).astype(np.uint8)
    fraction = cv2.countNonZero(binary) / float(height * width)
    return binary if 0.06 <= fraction <= 0.72 else None


def _largest_component(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == largest, 255, 0).astype(np.uint8)


def _remove_small_components(mask: np.ndarray, minimum_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= minimum_area:
            cleaned[labels == label] = 255
    return cleaned


def _color_channels(bgr: np.ndarray) -> dict[str, np.ndarray]:
    smooth = cv2.bilateralFilter(bgr, 7, 35, 35)
    hsv = cv2.cvtColor(smooth, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB)
    hue, saturation, value = cv2.split(hsv)
    _, lab_a, lab_b = cv2.split(lab)
    blue, green, red = cv2.split(smooth.astype(np.int16))
    return {
        "hue": hue,
        "saturation": saturation,
        "value": value,
        "lab_a": lab_a,
        "lab_b": lab_b,
        "excess_green": 2 * green - red - blue,
    }


def _generic_symptom_mask(bgr: np.ndarray) -> np.ndarray:
    channels = _color_channels(bgr)
    hue = channels["hue"]
    saturation = channels["saturation"]
    value = channels["value"]
    lab_a = channels["lab_a"]
    lab_b = channels["lab_b"]
    excess_green = channels["excess_green"]

    brown_red = (
        (((hue <= 24) | (hue >= 170)) & (saturation >= 35) & (value <= 225))
        | ((lab_a >= 136) & (value <= 210) & (saturation >= 22))
        | ((excess_green < -8) & (value <= 195) & (saturation >= 22))
    )
    yellow_bronze = (
        (hue >= 14)
        & (hue <= 42)
        & (saturation >= 32)
        & (value >= 50)
        & (lab_b >= 138)
    )
    dark_necrosis = (
        (value <= 72)
        & (saturation >= 18)
        & ((lab_a >= 122) | (hue <= 25) | (hue >= 170))
    )
    purple = (hue >= 132) & (hue <= 168) & (saturation >= 24) & (value <= 210)
    return (brown_red | yellow_bronze | dark_necrosis | purple).astype(np.uint8) * 255


def segment_leaf(bgr: np.ndarray) -> tuple[np.ndarray | None, str]:
    """Create a leaf denominator mask and reject unreliable segmentation."""
    if bgr is None or bgr.size == 0:
        return None, "empty_image"

    height, width = bgr.shape[:2]
    frame_area = float(height * width)
    if frame_area <= 0:
        return None, "empty_image"

    channels = _color_channels(bgr)
    hue = channels["hue"]
    saturation = channels["saturation"]
    value = channels["value"]
    excess_green = channels["excess_green"]

    foliage = (
        ((hue >= 22) & (hue <= 105) & (saturation >= 18) & (value >= 20))
        | ((excess_green >= 8) & (value >= 18))
    ).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    foliage = cv2.morphologyEx(foliage, cv2.MORPH_OPEN, kernel, iterations=1)
    foliage = cv2.morphologyEx(foliage, cv2.MORPH_CLOSE, kernel, iterations=2)
    foliage = _largest_component(foliage)

    contours, _ = cv2.findContours(foliage, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, "no_leaf_contour"

    largest = max(contours, key=cv2.contourArea)
    contour_area = float(cv2.contourArea(largest))
    if contour_area < thr.MIN_LEAF_CONTOUR_AREA:
        return None, "leaf_contour_too_small"

    clean = np.zeros((height, width), dtype=np.uint8)
    cv2.drawContours(clean, [largest], -1, 255, thickness=cv2.FILLED)

    # Keep discoloured tissue attached to the green leaf, so symptoms remain
    # inside the denominator even when those pixels are no longer green.
    nearby = cv2.dilate(
        clean,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)),
        iterations=1,
    )
    attached_symptoms = cv2.bitwise_and(_generic_symptom_mask(bgr), nearby)
    clean = cv2.bitwise_or(clean, attached_symptoms)
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel, iterations=2)

    leaf_pixels = float(cv2.countNonZero(clean))
    fraction = leaf_pixels / frame_area
    if fraction < thr.MIN_LEAF_AREA_FRACTION:
        return None, "leaf_area_fraction_low"
    if fraction > thr.MAX_LEAF_AREA_FRACTION:
        return None, "leaf_area_fraction_high"

    final_contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    final_largest = max(final_contours, key=cv2.contourArea)
    area = float(cv2.contourArea(final_largest))
    hull_area = float(cv2.contourArea(cv2.convexHull(final_largest))) or 1.0
    if area / hull_area < thr.MIN_LEAF_SOLIDITY:
        return None, "leaf_solidity_low"
    return clean, ""


def symptom_mask(bgr: np.ndarray, leaf_mask: np.ndarray, disease: str) -> np.ndarray:
    channels = _color_channels(bgr)
    hue = channels["hue"]
    saturation = channels["saturation"]
    value = channels["value"]
    lab_a = channels["lab_a"]
    lab_b = channels["lab_b"]
    excess_green = channels["excess_green"]

    if disease == "early_blight":
        raw = (
            (((hue <= 25) | (hue >= 160)) & (saturation >= 40) & (value <= 185))
            | ((hue >= 15) & (hue <= 40) & (saturation >= 40) & (value >= 80))
        )
    elif disease == "tlcv":
        raw = (
            (hue >= 15)
            & (hue <= 42)
            & (saturation >= 32)
            & (value >= 65)
            & (lab_b >= 138)
        )
    else:  # spotted_wilt
        brown_red = (
            (((hue <= 24) | (hue >= 170)) & (saturation >= 40) & (value <= 220))
            | ((lab_a >= 136) & (value <= 205) & (saturation >= 25))
            | ((excess_green < -8) & (value <= 190) & (saturation >= 25))
        )
        yellow_bronze = (
            (hue >= 16)
            & (hue <= 30)
            & (saturation >= 45)
            & (value >= 55)
            & (lab_a >= 118)
            & (lab_b >= 150)
        )
        dark_necrosis = (
            (value <= 68)
            & (saturation >= 20)
            & ((lab_a >= 122) | (hue <= 25) | (hue >= 170))
        )
        purple = (hue >= 132) & (hue <= 168) & (saturation >= 24) & (value <= 205)
        raw = brown_red | yellow_bronze | dark_necrosis | purple

    inner_leaf = cv2.erode(
        leaf_mask,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )
    mask = cv2.bitwise_and(raw.astype(np.uint8) * 255, inner_leaf)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    minimum_area = max(7, int(cv2.countNonZero(leaf_mask) * 0.0003))
    return _remove_small_components(mask, minimum_area)


def affected_pct_from_masks(leaf_mask: np.ndarray, symptoms: np.ndarray) -> float | None:
    leaf_pixels = int(cv2.countNonZero(leaf_mask))
    if leaf_pixels <= 0:
        return None
    symptom_pixels = int(cv2.countNonZero(symptoms))
    if symptom_pixels < thr.MIN_LESION_PIXELS:
        return 0.0
    return round(min(100.0, symptom_pixels / leaf_pixels * 100.0), 2)


def assess_severity(
    image_bytes: bytes, disease_raw: str | None, *, leaf_mask_png: bytes | None = None
) -> dict[str, Any]:
    disease = _normalize_disease(disease_raw)
    if not disease:
        return {
            "ok": False,
            "error": "invalid_disease",
            "message": "Send disease/bar_key: healthy, early_blight, tlcv, or spotted_wilt.",
            "severity": UNABLE,
            "severity_pct": None,
            "affected_area_pct": None,
            "measurable": False,
            "reason": "invalid_disease",
            "source": "opencv_color_segmentation",
            "rescan_recommended": True,
            "thresholds": thr.thresholds_echo(),
        }

    bgr = decode_image(image_bytes)
    if bgr is None:
        return _result(
            disease=disease,
            severity=UNABLE,
            affected_area_pct=None,
            measurable=False,
            reason="image_decode_failed",
        )

    if leaf_mask_png is not None:
        leaf_mask = decode_leaf_mask(leaf_mask_png, bgr.shape[:2])
        failure = "invalid_leaf_mask" if leaf_mask is None else ""
    else:
        leaf_mask, failure = segment_leaf(bgr)
    if leaf_mask is None:
        return _result(
            disease=disease,
            severity=UNABLE,
            affected_area_pct=None,
            measurable=False,
            reason=failure or "low_leaf_mask_quality",
        )

    leaf_pixels = int(cv2.countNonZero(leaf_mask))
    if disease == "healthy":
        return _result(
            disease=disease,
            severity="Healthy",
            affected_area_pct=0.0,
            measurable=True,
            reason="healthy_leaf_segmented",
            evidence=[f"{leaf_pixels} OpenCV leaf pixels"],
        )

    symptoms = symptom_mask(bgr, leaf_mask, disease)
    symptom_pixels = int(cv2.countNonZero(symptoms))
    affected = affected_pct_from_masks(leaf_mask, symptoms)
    if affected is None:
        return _result(
            disease=disease,
            severity=UNABLE,
            affected_area_pct=None,
            measurable=False,
            reason="symptom_measurement_failed",
        )

    return _result(
        disease=disease,
        severity=thr.band_for_affected_pct(affected),
        affected_area_pct=affected,
        measurable=True,
        reason=f"{disease}_opencv_estimate",
        evidence=[
            f"{leaf_pixels} OpenCV leaf pixels",
            f"{symptom_pixels} OpenCV symptom pixels",
        ],
    )
