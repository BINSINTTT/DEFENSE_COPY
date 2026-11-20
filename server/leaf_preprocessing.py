"""Select and gently enhance one leaf before disease detection.

MobileSAM runs through ONNX Runtime with Pillow/NumPy preprocessing. OpenCV is
reserved for the separate severity measurement after disease detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

MODEL_DIR = Path(__file__).resolve().parent / "models"
LOGGER = logging.getLogger(__name__)
MAX_EDGE = 1024
PIXEL_MEAN = (123.675, 116.28, 103.53)
PIXEL_STD = (58.395, 57.12, 57.375)


@dataclass(frozen=True)
class IsolatedLeaf:
    image_png: bytes
    mask_png: bytes
    mask: np.ndarray


@lru_cache(maxsize=1)
def _sessions() -> tuple[ort.InferenceSession, ort.InferenceSession]:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    # Render's free instance has little RAM; keep temporary encoder buffers
    # available to the OS after inference rather than retaining an arena.
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    providers = ["CPUExecutionProvider"]
    encoder = ort.InferenceSession(
        str(MODEL_DIR / "mobile_sam_encoder.onnx"), sess_options=options, providers=providers
    )
    decoder = ort.InferenceSession(
        str(MODEL_DIR / "mobile_sam_decoder.onnx"), sess_options=options, providers=providers
    )
    return encoder, decoder


def _read_image(image_bytes: bytes) -> Image.Image | None:
    try:
        with Image.open(BytesIO(image_bytes)) as uploaded:
            image = ImageOps.exif_transpose(uploaded).convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError):
        return None
    if min(image.size) < 80:
        return None
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    return image


def _embedding(image: Image.Image, encoder: ort.InferenceSession) -> np.ndarray:
    width, height = image.size
    scale = MAX_EDGE / max(width, height)
    resized_width = int(width * scale + 0.5)
    resized_height = int(height * scale + 0.5)
    resized = np.asarray(
        image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)
    )
    model_input = np.zeros((1, 3, MAX_EDGE, MAX_EDGE), dtype=np.float32)
    for channel in range(3):
        model_input[0, channel, :resized_height, :resized_width] = (
            resized[:, :, channel].astype(np.float32) - PIXEL_MEAN[channel]
        ) / PIXEL_STD[channel]
    return encoder.run(None, {"image": model_input})[0]


def _candidate_masks(
    image: Image.Image, embedding: np.ndarray, decoder: ort.InferenceSession
):
    width, height = image.size
    scale = MAX_EDGE / max(width, height)
    prompt_positions = (
        (0.50, 0.50),
        (0.35, 0.35),
        (0.65, 0.35),
        (0.35, 0.65),
        (0.65, 0.65),
    )
    common = {
        "image_embeddings": embedding,
        "mask_input": np.zeros((1, 1, 256, 256), dtype=np.float32),
        "has_mask_input": np.zeros((1,), dtype=np.float32),
        "orig_im_size": np.array([height, width], dtype=np.float32),
    }
    for x_fraction, y_fraction in prompt_positions:
        point_x = min(width - 1, int(width * x_fraction))
        point_y = min(height - 1, int(height * y_fraction))
        feed = {
            **common,
            "point_coords": np.array(
                [[[point_x * scale, point_y * scale], [0, 0]]], dtype=np.float32
            ),
            "point_labels": np.array([[1, -1]], dtype=np.float32),
        }
        masks, scores, _ = decoder.run(None, feed)
        # Mask zero is intended for multi-point prompts; one-point prompts use
        # the three alternative masks, as in MobileSAM's predictor.
        for index in range(1, min(4, masks.shape[1])):
            yield masks[0, index] > 0, float(scores[0, index]), (point_x, point_y)


def _select_mask(image: Image.Image, embedding: np.ndarray, decoder: ort.InferenceSession):
    rgb = np.asarray(image)
    height, width = rgb.shape[:2]
    greenish = (
        (rgb[:, :, 1] >= rgb[:, :, 0].astype(np.float32) * 0.75)
        & (rgb[:, :, 1] >= rgb[:, :, 2].astype(np.float32) * 0.75)
        & (rgb[:, :, 1] >= 35)
    )
    best_mask = None
    best_rank = -1.0
    for raw_mask, model_score, (point_x, point_y) in _candidate_masks(image, embedding, decoder):
        if model_score < 0.75:
            continue
        raw_fraction = float(raw_mask.mean())
        if not 0.06 <= raw_fraction <= 0.72 or not raw_mask[point_y, point_x]:
            continue
        mask = np.asarray(
            Image.fromarray(raw_mask.astype(np.uint8) * 255).filter(ImageFilter.MedianFilter(3))
        ) > 0
        if not mask[point_y, point_x]:
            continue
        connected = Image.fromarray(mask.astype(np.uint8) * 255).copy()
        ImageDraw.floodfill(connected, (point_x, point_y), 128)
        mask = np.asarray(connected) == 128
        fraction = float(mask.mean())
        if not 0.06 <= fraction <= 0.72 or float(greenish[mask].mean()) < 0.12:
            continue
        ys, xs = np.nonzero(mask)
        left, right = int(xs.min()), int(xs.max()) + 1
        top, bottom = int(ys.min()), int(ys.max()) + 1
        box_width, box_height = right - left, bottom - top
        if box_width < width * 0.18 or box_height < height * 0.18:
            continue
        extent = mask.sum() / float(box_width * box_height)
        if extent < 0.30:
            continue
        distance = ((point_x / width - 0.5) ** 2 + (point_y / height - 0.5) ** 2) ** 0.5
        rank = model_score + 0.03 * min(1.0, fraction / 0.35) - 0.08 * distance
        if rank > best_rank:
            best_mask, best_rank = mask, rank
        if best_rank >= 0.98 and distance == 0:
            break
    return best_mask


def _enhance_leaf(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Lift dark leaves and modestly increase contrast without changing hue."""
    original = rgb.astype(np.float32)
    luminance = (
        0.2126 * original[:, :, 0]
        + 0.7152 * original[:, :, 1]
        + 0.0722 * original[:, :, 2]
    )
    median = float(np.median(luminance[mask]))
    lift = min(20.0, max(0.0, (110.0 - median) * 0.35))
    adjusted = np.clip((luminance - median) * 1.08 + median + lift, 1, 255)
    ratio = np.clip(adjusted / np.maximum(luminance, 1), 0.75, 1.35)
    return np.clip(original * ratio[:, :, None], 0, 255).astype(np.uint8)


def isolate_leaf(image_bytes: bytes) -> tuple[IsolatedLeaf | None, str]:
    image = _read_image(image_bytes)
    if image is None:
        return None, "invalid_image"
    try:
        encoder, decoder = _sessions()
        mask = _select_mask(image, _embedding(image, encoder), decoder)
    except Exception:
        LOGGER.exception("Leaf segmentation model failed")
        return None, "leaf_model_unavailable"
    if mask is None:
        return None, "leaf_not_separated"

    rgb = np.asarray(image)
    enhanced = _enhance_leaf(rgb, mask)
    white = np.full_like(rgb, 255)
    white[mask] = enhanced[mask]
    ys, xs = np.nonzero(mask)
    box_width = int(xs.max() - xs.min() + 1)
    box_height = int(ys.max() - ys.min() + 1)
    margin = max(12, round(max(box_width, box_height) * 0.05))
    left, top = max(0, int(xs.min()) - margin), max(0, int(ys.min()) - margin)
    right = min(image.width, int(xs.max()) + margin + 1)
    bottom = min(image.height, int(ys.max()) + margin + 1)
    image_buffer, mask_buffer = BytesIO(), BytesIO()
    Image.fromarray(white).crop((left, top, right, bottom)).save(image_buffer, format="PNG")
    Image.fromarray(mask.astype(np.uint8) * 255).save(mask_buffer, format="PNG")
    return IsolatedLeaf(image_buffer.getvalue(), mask_buffer.getvalue(), mask.astype(np.uint8) * 255), ""
