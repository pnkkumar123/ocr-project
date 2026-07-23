"""Phase 1 — PDF ingestion.

Loads an architectural PDF, classifies each page as vector / raster / mixed,
and rasterizes every page to a PNG the downstream CV pipeline consumes.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import fitz  # PyMuPDF

from app.core.config import settings
from app.models.schemas import DocumentInfo, PageInfo, PageKind

# Three independent signals decide the extraction path:
#   text layer  -> we can read the door schedule WITHOUT OCR (big win)
#   vector geom -> door linework is vector (exact), not a rasterized image
#   raster imgs -> drawing (or part of it) is an embedded bitmap -> needs image CV
# Real construction PDFs are often hybrids: a rich text layer sitting over a
# raster drawing (searchable scans / CAD-to-PDF with image fills). Those must be
# treated as `mixed`, not `raster`, so the schedule parser uses the text layer.
_TEXT_CHARS_MIN = 80
_DRAWINGS_VECTOR_MIN = 50


def _classify_page(page: fitz.Page) -> tuple[PageKind, bool, int, int, int]:
    text_chars = len(page.get_text("text").strip())
    drawings = len(page.get_drawings())
    images = len(page.get_images(full=True))

    has_text = text_chars >= _TEXT_CHARS_MIN
    has_geom = drawings >= _DRAWINGS_VECTOR_MIN

    if images and (has_text or has_geom):
        kind = PageKind.mixed          # searchable/vector content over raster imagery
    elif has_geom or (has_text and not images):
        kind = PageKind.vector         # pure CAD: text + linework, no bitmap
    else:
        kind = PageKind.raster         # true scan: no usable text/geometry layer

    return kind, has_text, text_chars, drawings, images


def ingest_pdf(pdf_bytes: bytes, filename: str) -> DocumentInfo:
    """Persist the upload, render pages, and return per-page metadata."""
    settings.ensure_dirs()
    document_id = uuid.uuid4().hex

    upload_path = settings.uploads_dir / f"{document_id}.pdf"
    upload_path.write_bytes(pdf_bytes)

    page_out_dir = settings.pages_dir / document_id
    page_out_dir.mkdir(parents=True, exist_ok=True)

    zoom = settings.render_dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    pages: list[PageInfo] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc):
            kind, has_text, text_chars, drawings, images = _classify_page(page)

            pixmap = page.render(matrix=matrix) if hasattr(page, "render") else page.get_pixmap(matrix=matrix)
            image_path = page_out_dir / f"{index:04d}.png"
            pixmap.save(image_path)

            pages.append(
                PageInfo(
                    index=index,
                    width_pt=page.rect.width,
                    height_pt=page.rect.height,
                    kind=kind,
                    has_text_layer=has_text,
                    text_chars=text_chars,
                    vector_drawings=drawings,
                    raster_images=images,
                    image_path=str(image_path.relative_to(settings.storage_dir).as_posix()),
                    render_dpi=settings.render_dpi,
                )
            )

    info = DocumentInfo(
        document_id=document_id,
        filename=filename,
        page_count=len(pages),
        pages=pages,
    )
    # Persist metadata so later stages (detection, schedule parsing) can reload
    # a document by id without re-rendering.
    (page_out_dir / "document.json").write_text(info.model_dump_json(indent=2))
    return info


def load_document(document_id: str) -> DocumentInfo | None:
    """Reload persisted document metadata written during ingest."""
    meta = settings.pages_dir / document_id / "document.json"
    if not meta.exists():
        return None
    return DocumentInfo.model_validate_json(meta.read_text())
