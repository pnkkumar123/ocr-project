"""Detection service — run the door detector over a document's pages and
produce annotated images + a reliability-oriented summary.

Boxes are drawn with PIL (green = high confidence, amber = needs review) so the
output is a *reviewable* artifact, not a black box.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from app.core.config import settings
from app.models.schemas import (
    DetectionSummary,
    DoorDetection,
    PageDetections,
)
from app.pipeline.door_detector import DoorDetector
from app.services.pdf_ingest import load_document

_HIGH = (34, 197, 94)     # green
_REVIEW = (245, 158, 11)  # amber


@lru_cache(maxsize=1)
def _detector() -> DoorDetector:
    # Cached so the YOLO weights load once per process, not per request.
    return DoorDetector()


def _annotate(src_png, detections: list[DoorDetection], dst_png) -> None:
    with Image.open(src_png).convert("RGB") as img:
        draw = ImageDraw.Draw(img)
        for d in detections:
            color = _REVIEW if d.needs_review else _HIGH
            x, y, w, h = d.box.x, d.box.y, d.box.w, d.box.h
            draw.rectangle([x, y, x + w, y + h], outline=color, width=3)
            draw.text((x, max(0, y - 12)), f"door {d.confidence:.2f}", fill=color)
        img.save(dst_png)


def run_detection(document_id: str) -> DetectionSummary | None:
    """Detect doors on every page of a persisted document."""
    info = load_document(document_id)
    if info is None:
        return None

    detector = _detector()
    out_dir = settings.pages_dir / document_id / "annotated"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages: list[PageDetections] = []
    total = high = review = 0

    for page in info.pages:
        src = settings.storage_dir / page.image_path
        doors = detector.detect(str(src), page.index)

        dst = out_dir / f"{page.index:04d}.png"
        _annotate(src, doors, dst)

        total += len(doors)
        review += sum(d.needs_review for d in doors)
        high += sum(not d.needs_review for d in doors)

        pages.append(
            PageDetections(
                page_index=page.index,
                image_path=str(dst.relative_to(settings.storage_dir).as_posix()),
                doors=doors,
            )
        )

    return DetectionSummary(
        document_id=document_id,
        total_doors=total,
        high_confidence=high,
        needs_review=review,
        pages=pages,
    )
