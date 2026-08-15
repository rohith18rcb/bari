from __future__ import annotations

from dataclasses import dataclass

from core.duplicate import DuplicateStatus, classify


@dataclass
class FakeDetection:
    pothole_id: str


def test_no_nearby_is_new():
    result = classify([], distance_threshold_meters=8.0)
    assert result.status == DuplicateStatus.NEW
    assert result.duplicate_of is None


def test_very_close_match_is_known():
    nearby = [(FakeDetection("PTH-000001"), 2.0)]  # well within half the 8m threshold
    result = classify(nearby, distance_threshold_meters=8.0)
    assert result.status == DuplicateStatus.KNOWN
    assert result.duplicate_of == "PTH-000001"


def test_borderline_match_is_possible_duplicate():
    nearby = [(FakeDetection("PTH-000002"), 6.0)]  # within full threshold but beyond half
    result = classify(nearby, distance_threshold_meters=8.0)
    assert result.status == DuplicateStatus.POSSIBLE_DUPLICATE
    assert result.duplicate_of == "PTH-000002"


def test_far_match_is_new():
    nearby = [(FakeDetection("PTH-000003"), 50.0)]
    result = classify(nearby, distance_threshold_meters=8.0)
    assert result.status == DuplicateStatus.NEW
    assert result.duplicate_of is None


def test_closest_of_multiple_candidates_used():
    nearby = [(FakeDetection("PTH-000005"), 3.0), (FakeDetection("PTH-000004"), 1.0)]
    result = classify(nearby, distance_threshold_meters=8.0)
    assert result.duplicate_of == "PTH-000005"  # caller is responsible for pre-sorting by distance
