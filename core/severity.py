"""
severity.py — heuristic pothole severity estimation.

IMPORTANT: Severity is an estimated heuristic in V1, not a professionally
certified road-damage measurement. It approximates seriousness from what a
2D monocular detector can actually observe (bounding-box geometry and
detection persistence) — it does not measure depth, volume, or structural
road damage. A future version could replace this module with a trained
regression/classification model without touching any calling code, as long
as it exposes the same ``estimate_severity`` interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.config import settings


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class SeverityInputs:
    box_width: float
    box_height: float
    frame_width: float
    frame_height: float
    frame_count: int = 1
    mean_confidence: float = 0.0


@dataclass(frozen=True)
class SeverityResult:
    severity: Severity
    relative_area: float
    aspect_ratio: float
    score: float
    explanation: str


def estimate_severity(inputs: SeverityInputs) -> SeverityResult:
    """Estimate severity from detection geometry + persistence.

    Heuristic (V1, transparent and tunable via .env):
      relative_area = (box_w * box_h) / (frame_w * frame_h)
      score = relative_area, nudged up slightly by track persistence
              (a pothole tracked across many frames was closely/clearly
              observed, which correlates with it being large/close rather
              than a fleeting, ambiguous detection).

      score <  SEVERITY_AREA_LOW           -> LOW
      SEVERITY_AREA_LOW <= score < HIGH     -> MEDIUM
      score >= SEVERITY_AREA_HIGH           -> HIGH
    """
    frame_area = max(inputs.frame_width * inputs.frame_height, 1.0)
    box_area = max(inputs.box_width * inputs.box_height, 0.0)
    relative_area = box_area / frame_area

    aspect_ratio = inputs.box_width / max(inputs.box_height, 1e-6)

    persistence_bonus = min(inputs.frame_count / 30.0, 1.0) * 0.005
    score = relative_area + persistence_bonus

    low, high = settings.severity_area_low, settings.severity_area_high
    if score < low:
        severity = Severity.LOW
    elif score < high:
        severity = Severity.MEDIUM
    else:
        severity = Severity.HIGH

    explanation = (
        f"relative_area={relative_area:.4f}, persistence_bonus={persistence_bonus:.4f}, "
        f"score={score:.4f} vs thresholds(low={low}, high={high})"
    )
    return SeverityResult(severity=severity, relative_area=relative_area, aspect_ratio=aspect_ratio, score=score, explanation=explanation)
