"""Select one foreground leaf for disease detection and severity measurement.

GrabCut separates the central foreground object from a busy scene. A conservative
quality gate rejects ambiguous masks instead of sending background foliage to
the disease detector as though it were one leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class IsolatedLeaf:
    image_png: bytes
    mask_png: bytes
    mask: np.ndarray


def _enhance_leaf_luminance(crop: np.ndarray, crop_mask: np.ndarray) -> np.ndarray:
    """Gently reveal texture without changing the leaf's color channels."""
    leaf_pixels = crop_mask > 0
    if not np.any(leaf_pixels):
        return crop

    # A neutral fill keeps background colors out of the local contrast estimate.
    work = crop.copy()
    work[~leaf_pixels] = np.median(crop[leaf_pixels], axis=0).astype(np.uint8)
    lab = cv2.cvtColor(work, cv2.COLOR_BGR2LAB)
    luminance, chroma_a, chroma_b = cv2.split(lab)
    grid = 4 if min(crop.shape[:2]) < 512 else 8
    equalized = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(grid, grid)).apply(luminance)

    # Bound the change: strong enhancement can invent spot-like artifacts and
    # shift the image away from the detector's training photographs.
    change = np.clip((equalized.astype(np.float32) - luminance) * 0.45, -18, 18)
    median_light = float(np.median(luminance[leaf_pixels]))
    if median_light < 110:
        change += min(24.0, (110.0 - median_light) * 0.4)
    enhanced_light = np.clip(luminance.astype(np.float32) + change, 0, 255).astype(np.uint8)
    enhanced_lab = cv2.merge((enhanced_light, chroma_a, chroma_b))
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)


def isolate_leaf(bgr: np.ndarray) -> tuple[IsolatedLeaf | None, str]:
    if bgr is None or bgr.size == 0:
        return None, "invalid_image"

    height, width = bgr.shape[:2]
    if min(height, width) < 80:
        return None, "image_too_small"

    scale = min(1.0, 640.0 / max(height, width))
    small = cv2.resize(
        bgr,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    ) if scale < 1 else bgr
    small_height, small_width = small.shape[:2]
    rect = (
        max(1, round(small_width * 0.08)),
        max(1, round(small_height * 0.04)),
        max(2, round(small_width * 0.84)),
        max(2, round(small_height * 0.92)),
    )
    labels = np.zeros((small_height, small_width), dtype=np.uint8)
    try:
        cv2.grabCut(
            small, labels, rect,
            np.zeros((1, 65), dtype=np.float64),
            np.zeros((1, 65), dtype=np.float64),
            5, cv2.GC_INIT_WITH_RECT,
        )
    except cv2.error:
        return None, "leaf_not_separated"

    foreground = np.where(
        (labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    count, components, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    if count <= 1:
        return None, "leaf_not_separated"
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask_small = np.where(components == largest, 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(mask_small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, "leaf_not_separated"
    # Fill internal gaps so pale or brown lesions remain part of the leaf.
    mask_small[:] = 0
    cv2.drawContours(mask_small, [max(contours, key=cv2.contourArea)], -1, 255, cv2.FILLED)
    mask = cv2.resize(mask_small, (width, height), interpolation=cv2.INTER_NEAREST)

    pixels = cv2.countNonZero(mask)
    fraction = pixels / float(width * height)
    x, y, box_width, box_height = cv2.boundingRect(cv2.findNonZero(mask))
    contour = max(cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea)
    contour_area = cv2.contourArea(contour)
    hull_area = cv2.contourArea(cv2.convexHull(contour)) or 1.0
    if (
        not 0.06 <= fraction <= 0.75
        or box_width < width * 0.18
        or box_height < height * 0.18
        # A sprawling contour usually joins several overlapping leaves.
        or contour_area / hull_area < 0.85
    ):
        return None, "leaf_not_separated"

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (22, 18, 20), (105, 255, 255))
    green_fraction = cv2.countNonZero(green) / float(width * height)
    # On a leaf close-up GrabCut may pick one patch of tissue and discard the
    # remaining surface. That patch is not a whole leaf for classification.
    if green_fraction > 0.80 and fraction < 0.30:
        return None, "leaf_not_separated"

    margin = max(12, round(max(box_width, box_height) * 0.05))
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(width, x + box_width + margin), min(height, y + box_height + margin)
    crop = bgr[top:bottom, left:right]
    crop_mask = mask[top:bottom, left:right]
    enhanced = _enhance_leaf_luminance(crop, crop_mask)
    white = np.full_like(crop, 255)
    white[crop_mask > 0] = enhanced[crop_mask > 0]
    ok_image, image_buffer = cv2.imencode(".png", white)
    ok_mask, mask_buffer = cv2.imencode(".png", mask)
    if not ok_image or not ok_mask:
        return None, "image_encoding_failed"
    return IsolatedLeaf(image_buffer.tobytes(), mask_buffer.tobytes(), mask), ""


def decode_leaf_mask(mask_png: bytes, shape: tuple[int, int]) -> np.ndarray | None:
    if not mask_png:
        return None
    mask = cv2.imdecode(np.frombuffer(mask_png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if mask is None or mask.shape != shape:
        return None
    binary = np.where(mask >= 128, 255, 0).astype(np.uint8)
    fraction = cv2.countNonZero(binary) / float(shape[0] * shape[1])
    return binary if 0.06 <= fraction <= 0.75 else None
