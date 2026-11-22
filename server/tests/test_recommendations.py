"""Recommendation plans are selected by affected-area severity, not confidence."""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from groq.recommendations import _normalize_guide, fetch_care_recommendation  # noqa: E402


def recommendation(confidence: float, affected_area: float | None, label: str | None = None) -> dict:
    result = fetch_care_recommendation(
        {"healthy": 0, "tlcv": confidence, "early_blight": 0, "spotted_wilt": 0},
        severity_pct=affected_area,
        severity_label=label,
    )
    assert result["ok"] is True
    return result["guide"]


def test_high_confidence_with_small_affected_area_uses_mild_plan(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    guide = recommendation(99, 12)

    assert guide["severity"] == "Mild"
    assert guide["affectedAreaPct"] == 12
    assert guide["recommendationBasis"] == "affected_area_severity"
    assert "Mild · 12% affected" in guide["urgencyNote"]
    assert not any("Remove the severely infected plant" in step for step in guide["actionSteps"])


def test_confidence_change_does_not_change_care_plan(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    lower_confidence = recommendation(55, 48)
    higher_confidence = recommendation(98, 48)

    assert lower_confidence["severity"] == "Moderate"
    assert lower_confidence["urgencyNote"] == higher_confidence["urgencyNote"]
    assert lower_confidence["actionSteps"] == higher_confidence["actionSteps"]


def test_affected_area_changes_the_selected_plan(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    mild = recommendation(90, 20)
    moderate = recommendation(90, 50)
    severe = recommendation(90, 80)

    assert [mild["severity"], moderate["severity"], severe["severity"]] == [
        "Mild",
        "Moderate",
        "Severe",
    ]
    assert mild["actionSteps"] != moderate["actionSteps"]
    assert moderate["actionSteps"] != severe["actionSteps"]
    assert severe["isCriticalRemoval"] is True
    assert severe["actionSteps"][0].startswith("Seek confirmation urgently")
    assert "if infection is confirmed" in severe["actionSteps"][0]


def test_returned_band_is_used_when_area_is_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    guide = recommendation(96, None, "Moderate")

    assert guide["severity"] == "Moderate"
    assert guide["affectedAreaPct"] is None
    assert guide["urgencyNote"].startswith("Moderate:")


def test_returned_band_wins_at_decimal_threshold_boundary(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    guide = recommendation(96, 33.5, "Moderate")

    assert guide["severity"] == "Moderate"
    assert guide["urgencyNote"].startswith("Moderate · 33.5% affected")


def test_unassessable_image_requests_rescan_instead_of_selecting_treatment(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    guide = recommendation(99, None, "Unable to Assess")

    assert guide["severity"] == "Unable to Assess"
    assert guide["actionSteps"][0].startswith("Retake the scan")
    assert not any("insecticide" in step.lower() for step in guide["actionSteps"])


def test_viral_plans_manage_spread_without_claiming_a_cure(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for key, insect in (("tlcv", "whiteflies"), ("spotted_wilt", "thrips")):
        for pct, band in ((20, "Mild"), (50, "Moderate"), (80, "Severe")):
            result = fetch_care_recommendation({key: 90}, severity_pct=pct)
            guide = result["guide"]
            assert guide["severity"] == band
            assert "no cure" in guide["summary"].lower()
            assert insect in " ".join(guide["preventionTips"]).lower()
            assert "remove" not in guide["actionSteps"][0].lower() or "confirm" in guide["actionSteps"][0].lower()


def test_groq_cannot_replace_viral_management_with_cure_claim():
    guide = _normalize_guide(
        {"summary": "A spray cures the virus.", "preventionTips": ["Ignore insects."]},
        "spotted_wilt", 80, "Severe",
    )
    assert "no cure" in guide["summary"].lower()
    assert "thrips" in " ".join(guide["preventionTips"]).lower()
    assert "cures" not in str(guide).lower()
