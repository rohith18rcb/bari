from __future__ import annotations

from core.severity import Severity, SeverityInputs, estimate_severity


def test_small_box_is_low_severity():
    result = estimate_severity(SeverityInputs(
        box_width=10, box_height=10, frame_width=1280, frame_height=720, frame_count=1,
    ))
    assert result.severity == Severity.LOW


def test_large_box_is_high_severity():
    result = estimate_severity(SeverityInputs(
        box_width=400, box_height=300, frame_width=640, frame_height=480, frame_count=1,
    ))
    assert result.severity == Severity.HIGH


def test_medium_box_is_medium_severity():
    # relative_area ~0.025, between the default low=0.015 and high=0.05 thresholds
    result = estimate_severity(SeverityInputs(
        box_width=100, box_height=80, frame_width=640, frame_height=480, frame_count=1,
    ))
    assert result.severity == Severity.MEDIUM


def test_persistence_increases_score():
    low_persistence = estimate_severity(SeverityInputs(
        box_width=100, box_height=80, frame_width=640, frame_height=480, frame_count=1,
    ))
    high_persistence = estimate_severity(SeverityInputs(
        box_width=100, box_height=80, frame_width=640, frame_height=480, frame_count=30,
    ))
    assert high_persistence.score > low_persistence.score


def test_relative_area_computed_correctly():
    result = estimate_severity(SeverityInputs(
        box_width=64, box_height=48, frame_width=640, frame_height=480, frame_count=1,
    ))
    assert result.relative_area == (64 * 48) / (640 * 480)
