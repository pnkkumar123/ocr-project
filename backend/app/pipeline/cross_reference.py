"""Cross-reference stage (rule-based, no training).

Associates each detected door with the nearest OCR'd tag, joins that tag to a
door-schedule row, and resolves the final fire-rating using a priority of
signals: explicit schedule rating > wall rating > legend default.
"""

from __future__ import annotations

import math
import re

from app.models.schemas import DoorDetection
from app.pipeline.ocr import TextSpan
from app.pipeline.schedule_parser import ScheduleRow

# Ratings we treat as "fire rated" when found in a schedule cell.
_FIRE_RATING_TOKENS = ("20 MIN", "45 MIN", "60 MIN", "90 MIN", "3 HR", "FR", "RATED")

# Door marks look like "101", "103A" — not material/legend labels like "WD" or
# "WALL" that happen to sit closer to a door symbol than its actual tag.
_TAG_LIKE = re.compile(r"^\d{1,4}[A-Z]?$")

# Beyond this pixel radius a "nearest" span is probably an unrelated label, not
# this door's tag — better to leave it untagged than guess wrong. This is a tight
# "at-the-doorway" radius (~1 in at 200 DPI): we only claim a per-door tag when a
# mark genuinely sits next to the swing. Drawings that key the schedule by room
# number (label mid-room, far from the door) will match nothing here by design —
# their fire-door inventory comes from the schedule itself, not spatial guessing.
_MAX_TAG_DIST = 250.0


def _center(box) -> tuple[float, float]:
    return box.x + box.w / 2, box.y + box.h / 2


def associate_tags(doors: list[DoorDetection], spans: list[TextSpan]) -> None:
    """Attach the closest mark-shaped text span to each door as its tag (in place)."""
    candidates = [s for s in spans if _TAG_LIKE.match(s.text.strip())]
    for door in doors:
        dcx, dcy = _center(door.box)
        best, best_dist = None, float("inf")
        for span in candidates:
            scx, scy = span.x + span.w / 2, span.y + span.h / 2
            dist = math.hypot(dcx - scx, dcy - scy)
            if dist < best_dist:
                best, best_dist = span, dist
        if best is not None and best_dist <= _MAX_TAG_DIST:
            door.tag = best.text.strip()


def resolve_fire_rating(doors: list[DoorDetection], schedule: list[ScheduleRow]) -> None:
    """Join door tags to schedule rows and set fire_rated / fire_rating (in place)."""
    by_tag = {row.tag.upper(): row for row in schedule}
    for door in doors:
        if not door.tag:
            continue
        row = by_tag.get(door.tag.upper())
        if row and row.fire_rating:
            rating = row.fire_rating.upper()
            door.fire_rating = row.fire_rating
            door.fire_rated = any(tok in rating for tok in _FIRE_RATING_TOKENS)
            door.rating_source = "schedule"
