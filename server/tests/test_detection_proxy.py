"""The disease route forwards one image to the configured detector."""

from __future__ import annotations

import io
import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import validation_api as api  # noqa: E402
from severity.leaf_isolation import _enhance_leaf_luminance  # noqa: E402


def _test_leaf_image() -> bytes:
    image = np.full((240, 240, 3), 30, dtype=np.uint8)
    cv2.ellipse(image, (120, 120), (72, 91), 0, 0, 360, (40, 160, 40), -1)
    cv2.circle(image, (110, 100), 18, (30, 75, 145), -1)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_dark_leaf_enhancement_lifts_detail_without_changing_leaf_colors():
    image = np.full((200, 200, 3), 30, dtype=np.uint8)
    mask = np.zeros((200, 200), dtype=np.uint8)
    cv2.ellipse(mask, (100, 100), (67, 80), 0, 0, 360, 255, -1)
    image[mask > 0] = (25, 70, 35)
    cv2.circle(image, (90, 90), 18, (15, 28, 70), -1)

    enhanced = _enhance_leaf_luminance(image, mask)
    before = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    after = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    assert np.median(after[:, :, 0][mask > 0]) > np.median(before[:, :, 0][mask > 0]) + 10
    assert np.abs(
        before[:, :, 1:].astype(np.int16) - after[:, :, 1:].astype(np.int16)
    )[mask > 0].mean() < 3
    assert abs(int(after[140, 100, 0]) - int(after[90, 90, 0])) >= abs(
        int(before[140, 100, 0]) - int(before[90, 90, 0])
    )


def test_classify_forwards_to_new_detector_without_exposing_key():
    class Response:
        status_code = 200

        def json(self):
            return {"images": [{"results": [{"name": "EarlyBlightVirus", "confidence": 0.91}]}]}

    with (
        patch.object(api, "ULTRALYTICS_DETECTION_URL", "https://detector.example/predict"),
        patch.object(api, "ULTRALYTICS_DETECTION_API_KEY", "test-secret"),
        patch.object(api.requests, "post", return_value=Response()) as upstream,
    ):
        response = api.app.test_client().post(
            "/classify",
            data={"file": (io.BytesIO(_test_leaf_image()), "leaf.png"), "conf": "0.25"},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.json["images"][0]["results"][0]["name"] == "EarlyBlightVirus"
    args, kwargs = upstream.call_args
    assert args == ("https://detector.example/predict",)
    assert kwargs["headers"] == {"Authorization": "Bearer test-secret"}
    assert kwargs["data"] == {"conf": "0.25"}
    isolated = cv2.imdecode(np.frombuffer(kwargs["files"]["file"][1], np.uint8), cv2.IMREAD_COLOR)
    assert kwargs["files"]["file"][0] == "isolated-leaf.png"
    assert kwargs["files"]["file"][2] == "image/png"
    assert isolated is not None
    assert np.all(isolated[0, 0] == 255)
    mask = cv2.imdecode(np.frombuffer(base64.b64decode(response.json["leaf_mask_png"]), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert mask.shape == (240, 240)
    assert mask[120, 120] == 255
    assert mask[0, 0] == 0
    assert kwargs["timeout"] == 120


def test_classify_uses_twenty_percent_when_client_omits_confidence():
    class Response:
        status_code = 200

        def json(self):
            return {"images": [{"results": []}]}

    with (
        patch.object(api, "ULTRALYTICS_DETECTION_URL", "https://detector.example/predict"),
        patch.object(api, "ULTRALYTICS_DETECTION_API_KEY", "test-secret"),
        patch.object(api, "isolate_leaf", return_value=(SimpleNamespace(image_png=b"isolated", mask_png=b"mask"), "")),
        patch.object(api.requests, "post", return_value=Response()) as upstream,
    ):
        response = api.app.test_client().post(
            "/classify",
            data={"file": (io.BytesIO(_test_leaf_image()), "leaf.png")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert upstream.call_args.kwargs["data"] == {"conf": "0.2"}


def test_old_specialist_route_is_gone():
    assert all(rule.rule != "/refine-disease" for rule in api.app.url_map.iter_rules())


def test_html_gateway_error_is_not_shown_to_users():
    class Response:
        status_code = 502
        text = "<!DOCTYPE html><title>502</title>"

        def json(self):
            raise ValueError("not JSON")

    with (
        patch.object(api, "ULTRALYTICS_DETECTION_URL", "https://detector.example/predict"),
        patch.object(api, "ULTRALYTICS_DETECTION_API_KEY", "test-secret"),
        patch.object(api.requests, "post", return_value=Response()),
    ):
        response = api.app.test_client().post(
            "/classify",
            data={"file": (io.BytesIO(_test_leaf_image()), "leaf.png")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 502
    assert "Retry the scan" in response.json["message"]
    assert "<!DOCTYPE" not in response.json["message"]


def test_classify_asks_for_another_leaf_when_isolation_fails():
    image = np.full((240, 240, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    with (
        patch.object(api, "ULTRALYTICS_DETECTION_URL", "https://detector.example/predict"),
        patch.object(api, "ULTRALYTICS_DETECTION_API_KEY", "test-secret"),
        patch.object(api.requests, "post") as upstream,
    ):
        response = api.app.test_client().post(
            "/classify",
            data={"file": (io.BytesIO(encoded.tobytes()), "blank.png")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 422
    assert response.json["error"] == "leaf_isolation_failed"
    upstream.assert_not_called()
