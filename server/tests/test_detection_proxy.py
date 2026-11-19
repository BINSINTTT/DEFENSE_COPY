"""The disease route forwards one image to the configured detector."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import validation_api as api  # noqa: E402


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
            data={"file": (io.BytesIO(b"image bytes"), "leaf.jpg"), "conf": "0.25"},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.json["images"][0]["results"][0]["name"] == "EarlyBlightVirus"
    args, kwargs = upstream.call_args
    assert args == ("https://detector.example/predict",)
    assert kwargs["headers"] == {"Authorization": "Bearer test-secret"}
    assert kwargs["data"] == {"conf": "0.25"}
    assert kwargs["files"]["file"][1] == b"image bytes"
    assert kwargs["timeout"] == 120


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
            data={"file": (io.BytesIO(b"image bytes"), "leaf.jpg")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 502
    assert "Retry the scan" in response.json["message"]
    assert "<!DOCTYPE" not in response.json["message"]
