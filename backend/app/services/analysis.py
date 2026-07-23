"""Analysis service — the full pipeline: detect doors, associate tags (from
the PDF text layer where available, no OCR needed), resolve fire ratings via
the door schedule, and produce a reviewable annotated output + CSV export.

Fire-rated doors are drawn distinctly (red) from plain high-confidence (green)
and needs-review (amber) detections, so a human reviewer can scan a page and
immediately see what the pipeline claims is fire-rated and why (tag + rating
shown in the label).
"""

from __future__ import annotations

import csv
import io
from functools import lru_cache

from PIL import Image, ImageDraw

from app.core.config import settings
from app.models.schemas import (
    AnalysisSummary,
    DoorDetection,
    PageDetections,
    PageInfo,
    ScheduleFireDoor,
)
from app.pipeline import cross_reference
from app.pipeline.door_detector import DoorDetector
from app.pipeline.ocr import OcrEngine, text_layer_spans
from app.pipeline.schedule_parser import ScheduleRow, parse_ocr_spans, parse_pdf
from app.services.pdf_ingest import load_document

_HIGH = (34, 197, 94)     # green — high confidence, not fire-rated
_REVIEW = (245, 158, 11)  # amber — needs review
_FIRE = (220, 38, 38)     # red — resolved fire-rated door (takes priority)


@lru_cache(maxsize=1)
def _detector() -> DoorDetector:
    # Cached so the YOLO weights load once per process, not per request.
    return DoorDetector()


@lru_cache(maxsize=1)
def _ocr_engine() -> OcrEngine:
    return OcrEngine()


# OCR is far slower than the text-layer path (seconds per page vs.
# milliseconds), so it only runs where there's no text layer to read the
# schedule from, and only over a bounded number of pages — a raster schedule
# table is normally one or two sheets, not the whole set.
_MAX_OCR_SCHEDULE_PAGES = 5


def _ocr_schedule_rows(info) -> list[ScheduleRow]:
    """Best-effort schedule extraction for pages with no text layer (scanned
    schedules), via OCR + the same transposed/columnar table logic used for
    text-layer schedules. Only a fallback: runs when the text layer found
    nothing, since it's much slower and noisier."""
    engine = _ocr_engine()
    rows: list[ScheduleRow] = []
    seen: set[str] = set()
    candidates = [p for p in info.pages if not p.has_text_layer][:_MAX_OCR_SCHEDULE_PAGES]
    for page in candidates:
        src = settings.storage_dir / page.image_path
        spans = engine.read(str(src))
        for row in parse_ocr_spans(spans):
            if row.tag not in seen:
                seen.add(row.tag)
                rows.append(row)
    return rows


def _pdf_path(document_id: str):
    return settings.uploads_dir / f"{document_id}.pdf"


def _annotate(src_png, detections: list[DoorDetection], dst_png) -> None:
    with Image.open(src_png).convert("RGB") as img:
        draw = ImageDraw.Draw(img)
        for d in detections:
            color = _FIRE if d.fire_rated else (_REVIEW if d.needs_review else _HIGH)
            x, y, w, h = d.box.x, d.box.y, d.box.w, d.box.h
            draw.rectangle([x, y, x + w, y + h], outline=color, width=4 if d.fire_rated else 3)
            label = d.tag or ""
            if d.fire_rated:
                label = f"{label} FIRE {d.fire_rating or ''}".strip()
            elif d.needs_review:
                label = f"{label} {d.confidence:.2f}".strip()
            if label:
                draw.text((x, max(0, y - 12)), label, fill=color)
        img.save(dst_png)


def _detect_and_tag(pdf_path, detector: DoorDetector, page: PageInfo) -> list[DoorDetection]:
    src = settings.storage_dir / page.image_path
    doors = detector.detect(str(src), page.index)
    if page.has_text_layer:
        spans = text_layer_spans(str(pdf_path), page.index, page.render_dpi)
        cross_reference.associate_tags(doors, spans)
    return doors


def run_analysis(document_id: str) -> AnalysisSummary | None:
    """Detect doors, associate tags, and resolve fire ratings for every page."""
    info = load_document(document_id)
    if info is None:
        return None

    pdf_path = _pdf_path(document_id)
    detector = _detector()
    out_dir = settings.pages_dir / document_id / "analyzed"
    out_dir.mkdir(parents=True, exist_ok=True)

    schedule = parse_pdf(str(pdf_path))
    if not schedule:
        # No text-layer schedule found anywhere — try OCR on raster pages
        # before concluding there's nothing to report.
        schedule = _ocr_schedule_rows(info)

    per_page = [(page, _detect_and_tag(pdf_path, detector, page)) for page in info.pages]
    all_doors = [door for _, doors in per_page for door in doors]
    cross_reference.resolve_fire_rating(all_doors, schedule)

    # Authoritative fire-door inventory straight from the schedule text, plus the
    # page (if any) where we could visually locate each one on the plan.
    located_by_tag: dict[str, int] = {
        d.tag.upper(): d.page_index
        for d in all_doors
        if d.tag and d.fire_rated
    }
    schedule_fire_doors = [
        ScheduleFireDoor(
            tag=row.tag,
            fire_rating=row.fire_rating,
            located_on_page=located_by_tag.get(row.tag.upper()),
        )
        for row in schedule
        if row.fire_rating
    ]

    pages: list[PageDetections] = []
    total = high = review = fire = 0
    for page, doors in per_page:
        src = settings.storage_dir / page.image_path
        dst = out_dir / f"{page.index:04d}.png"
        _annotate(src, doors, dst)

        total += len(doors)
        review += sum(d.needs_review for d in doors)
        high += sum(not d.needs_review for d in doors)
        fire += sum(bool(d.fire_rated) for d in doors)

        pages.append(
            PageDetections(
                page_index=page.index,
                image_path=str(dst.relative_to(settings.storage_dir).as_posix()),
                doors=doors,
            )
        )

    return AnalysisSummary(
        document_id=document_id,
        total_doors=total,
        high_confidence=high,
        needs_review=review,
        fire_rated_located=fire,
        schedule_fire_doors=schedule_fire_doors,
        pages=pages,
    )


def export_csv(document_id: str) -> str | None:
    """Run the full analysis and return a CSV door inventory."""
    summary = run_analysis(document_id)
    if summary is None:
        return None

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "page", "tag", "confidence", "needs_review",
            "fire_rated", "fire_rating", "rating_source",
            "x", "y", "w", "h",
        ]
    )
    for page in summary.pages:
        for d in page.doors:
            writer.writerow(
                [
                    d.page_index,
                    d.tag or "",
                    f"{d.confidence:.3f}",
                    d.needs_review,
                    "" if d.fire_rated is None else d.fire_rated,
                    d.fire_rating or "",
                    d.rating_source or "",
                    f"{d.box.x:.1f}",
                    f"{d.box.y:.1f}",
                    f"{d.box.w:.1f}",
                    f"{d.box.h:.1f}",
                ]
            )
    return buf.getvalue()
