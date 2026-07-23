"""Component #5 — fire-barrier / wall-rating line detection.

Fire-rated walls are drawn with distinct line patterns (e.g. dash-dot with
rating callouts). Detected via YOLO-seg or a U-Net segmentation model, then
associated with nearby doors as a fallback fire-rating signal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WallSegment:
    points: list[tuple[float, float]]
    rating: str | None = None
    confidence: float = 0.0


class WallRatingDetector:
    """Slot for the segmentation implementation (Phase 5, training required)."""

    def detect(self, image_path: str) -> list[WallSegment]:
        raise NotImplementedError("wall-rating segmentation lands in Phase 5")
