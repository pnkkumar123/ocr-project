"""Component #3 — text recognition for door tags and schedule cells.

Uses a pretrained OCR engine (PaddleOCR / EasyOCR). Fine-tune only if the
stylized CAD fonts hurt accuracy. Kept behind a lazy loader like the detector.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextSpan:
    text: str
    x: float
    y: float
    w: float
    h: float
    confidence: float


def text_layer_spans(pdf_path: str, page_index: int, render_dpi: int) -> list[TextSpan]:
    """Read door-tag text straight from the PDF text layer (no OCR) for pages
    that have one. Coordinates are scaled to match the rendered PNG's pixel
    space so they line up with detector boxes.

    `get_text("words")` returns coordinates in raw *mediabox* space, ignoring
    any page `/Rotate` flag — but the rendered PNG (and therefore every YOLO
    box) is in *displayed* space, post-rotation. Landscape architectural sheets
    saved with a rotation flag are common (5 of our 6 real test sets have at
    least one rotated page); without this transform, tags land tens of inches
    away from their doors and every cross-reference silently fails.
    """
    import fitz  # lazy: keeps this module importable without PyMuPDF at collection time

    zoom = render_dpi / 72.0
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        words = page.get_text("words")
        m = page.rotation_matrix
        spans = []
        for x0, y0, x1, y1, text, *_ in words:
            p0, p1 = fitz.Point(x0, y0) * m, fitz.Point(x1, y1) * m
            rx0, rx1 = sorted((p0.x, p1.x))
            ry0, ry1 = sorted((p0.y, p1.y))
            spans.append(
                TextSpan(
                    text=text,
                    x=rx0 * zoom,
                    y=ry0 * zoom,
                    w=(rx1 - rx0) * zoom,
                    h=(ry1 - ry0) * zoom,
                    confidence=1.0,
                )
            )
    return spans


class OcrEngine:
    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._reader = None

    def _ensure_reader(self):
        if self._reader is None:
            import easyocr  # lazy heavy import

            self._reader = easyocr.Reader([self.lang], gpu=False)
        return self._reader

    def read(self, image_path: str) -> list[TextSpan]:
        reader = self._ensure_reader()
        spans: list[TextSpan] = []
        for box, text, conf in reader.readtext(image_path):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            spans.append(
                TextSpan(
                    text=text,
                    x=min(xs),
                    y=min(ys),
                    w=max(xs) - min(xs),
                    h=max(ys) - min(ys),
                    confidence=float(conf),
                )
            )
        return spans
