"""Component #4 — door-schedule extraction (text-layer path).

Reads the door schedule straight from the PDF text layer — no OCR, exact, free —
for pages where `has_text_layer` is true. Real schedules use (at least) two
layouts, both handled here:

  - *Transposed* CAD layout (`parse_page_words`): door marks run along one row
    and a parallel `RATING` row holds the fire ratings, aligned by x-position
    (verified on the lumberone set: marks `01..08` over a `20 20 20 ...` rating
    row = eight 20-minute fire doors).
  - *Columnar* layout (`parse_columnar_page`) — the far more common
    professional format: one row per door, a `NUMBER` column and a `RATING`
    column, aligned by y-position (verified on Sanibel Fire Station: 20/45/60
    MIN; Ann Arbor Fire Station: 45/90 MIN). Disambiguates a fire-rating
    `RATING` column from an adjacent STC/sound `RATING` column by header
    context, since both are common on the same sheet.

Both scan the same raw word coordinates and rely only on relative position
within that frame, so they're unaffected by PDF page-rotation flags (common on
landscape architectural sheets) — unlike anything that compares against
rendered-pixel coordinates (see `ocr.text_layer_spans`).

Falls back to returning nothing (not a guess) when no schedule structure is
found — better to report "no schedule detected" than fabricate ratings.

Raster-only schedule pages (no text layer) route to OCR/Table-Transformer later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

# US: bare minutes/hours appear only inside a RATING row, so they're unambiguous there.
_US_MIN = re.compile(r"^(20|30|45|60|90|180)$")
_US_HR = re.compile(r"^([1-4])\s*(HR|HOUR)S?$", re.I)
# UK fire doors: FD30, FD60, FD30S (S = smoke seals), FD 60, etc.
_UK_FD = re.compile(r"^FD\s?(20|30|60|90|120)S?$", re.I)
_MARK = re.compile(r"^\d{1,3}[A-Z]?$")

_RATING_LABELS = {"RATING", "FIRE", "LABEL"}
_MARK_LABELS = {"NUMBER", "MARK", "NO", "NO.", "#"}

# Columnar layout: a RATING header immediately preceded by one of these on the
# same header row is an acoustic/sound rating, not fire — skip it (Sanibel's
# schedule has both "DOOR/FRAME RATING" and "STC RATING" columns side by side).
_NON_FIRE_RATING_CONTEXT = {"STC", "SOUND"}
# Door mark cells: "101", "004A", up to 4 digits (Ann Arbor uses "200A" etc).
_MARK_CELL = re.compile(r"^\d{2,4}[A-Z]?$")
_RATING_CELL = re.compile(r"^(20|30|45|60|90|120|180)$")


@dataclass
class ScheduleRow:
    tag: str
    fire_rating: str | None = None
    fire_rated: bool = False
    extra: dict[str, str] = field(default_factory=dict)


def _normalize_rating(token: str) -> str | None:
    t = token.strip().upper()
    if _UK_FD.match(t):
        return t.replace(" ", "")
    if _US_MIN.match(t):
        return f"{t} MIN"
    if _US_HR.match(t):
        return re.sub(r"\s+", " ", t).replace("HOUR", "HR")
    return None


def _row_band(words, label) -> list:
    """Words vertically aligned with (same row as) the label word."""
    yc = (label[1] + label[3]) / 2
    h = max(1.0, label[3] - label[1])
    return [w for w in words if w is not label and abs((w[1] + w[3]) / 2 - yc) < h]


def parse_page_words(words) -> list[ScheduleRow]:
    """Parse a door schedule from PyMuPDF `words` (x0,y0,x1,y1,text,...)."""
    rating_lbl = next((w for w in words if w[4].upper() in _RATING_LABELS), None)
    mark_lbl = next((w for w in words if w[4].upper() in _MARK_LABELS), None)
    if not rating_lbl or not mark_lbl:
        return []

    # Values sit to the left of the right-aligned row label in this CAD layout.
    rating_row = [w for w in _row_band(words, rating_lbl) if w[0] < rating_lbl[0]]
    mark_row = [w for w in _row_band(words, mark_lbl) if w[0] < mark_lbl[0]]

    ratings = [(w, _normalize_rating(w[4])) for w in rating_row]
    ratings = [(w, r) for w, r in ratings if r]
    marks = [w for w in mark_row if _MARK.match(w[4])]
    if not ratings or not marks:
        return []

    rows: list[ScheduleRow] = []
    for w, rating in ratings:
        xc = (w[0] + w[2]) / 2
        nearest = min(marks, key=lambda m: abs((m[0] + m[2]) / 2 - xc))
        rows.append(ScheduleRow(tag=nearest[4], fire_rating=rating, fire_rated=True))
    # De-dup by tag (keep first rating seen).
    seen: dict[str, ScheduleRow] = {}
    for r in rows:
        seen.setdefault(r.tag, r)
    return list(seen.values())


def parse_columnar_page(words) -> list[ScheduleRow]:
    """Parse a standard one-row-per-door schedule table: a NUMBER column and a
    (fire) RATING column, values aligned to each row by y-position.

    Header matching is substring-based (not exact-equal) because OCR (the
    raster path) merges multi-word cells into one box — "DOOR NUMBER" comes
    back as a single span, not two words like the PDF text layer gives us.
    """
    number_hdrs = [w for w in words if "NUMBER" in w[4].upper()]
    rating_hdrs = [w for w in words if "RATING" in w[4].upper()]
    if not number_hdrs or not rating_hdrs:
        return []

    # Header row: a narrow y-band around the topmost NUMBER/RATING match, wide
    # enough to catch context words like "STC" or "DOOR/FRAME" on either side.
    header_y = min(w[1] for w in number_hdrs + rating_hdrs)
    header_band = sorted((w for w in words if abs(w[1] - header_y) < 20), key=lambda w: w[0])

    # Leftmost NUMBER header is the canonical door-mark column (wide tables
    # sometimes repeat it again on the far right for readability).
    mark_hdr = min(number_hdrs, key=lambda w: w[0])
    mark_x = (mark_hdr[0] + mark_hdr[2]) / 2

    rating_x = None
    for i, w in enumerate(header_band):
        if "RATING" not in w[4].upper():
            continue
        text_ctx = w[4].upper()
        prev = header_band[i - 1] if i > 0 else None
        if prev and (w[0] - prev[2]) < 60:
            text_ctx += " " + prev[4].upper()
        if any(bad in text_ctx for bad in _NON_FIRE_RATING_CONTEXT):
            continue
        rating_x = (w[0] + w[2]) / 2
        break
    if rating_x is None:
        return []

    header_bottom = max(w[3] for w in header_band)
    body = [w for w in words if w[1] > header_bottom]
    mark_col = [w for w in body if abs((w[0] + w[2]) / 2 - mark_x) < 45 and _MARK_CELL.match(w[4].strip())]
    rating_col = [w for w in body if abs((w[0] + w[2]) / 2 - rating_x) < 45 and _RATING_CELL.match(w[4].strip())]
    if not mark_col or not rating_col:
        return []

    rows: list[ScheduleRow] = []
    for mw in mark_col:
        myc = (mw[1] + mw[3]) / 2
        nearest = min(rating_col, key=lambda rw: abs((rw[1] + rw[3]) / 2 - myc))
        ryc = (nearest[1] + nearest[3]) / 2
        if abs(ryc - myc) > 12:  # not actually this door's row
            continue
        rating = _normalize_rating(nearest[4])
        if rating:
            rows.append(ScheduleRow(tag=mw[4].strip(), fire_rating=rating, fire_rated=True))
    seen: dict[str, ScheduleRow] = {}
    for r in rows:
        seen.setdefault(r.tag, r)
    return list(seen.values())


def _display_words(page) -> list:
    """Words in *displayed* reading orientation, not raw mediabox space.

    Both parsers reason about "same row" / "left of the label" in reading-order
    terms, which only holds once a page's `/Rotate` flag is applied — raw
    coordinates from `get_text("words")` ignore it, and a 90/270 rotation swaps
    the x/y axes entirely (see `ocr.text_layer_spans` for the same fix applied
    to detector-coordinate cross-referencing).
    """
    m = page.rotation_matrix
    out = []
    for x0, y0, x1, y1, text, *rest in page.get_text("words"):
        p0, p1 = fitz.Point(x0, y0) * m, fitz.Point(x1, y1) * m
        rx0, rx1 = sorted((p0.x, p1.x))
        ry0, ry1 = sorted((p0.y, p1.y))
        out.append((rx0, ry0, rx1, ry1, text, *rest))
    return out


def parse_pdf(pdf_path: str, page_indexes: list[int] | None = None) -> list[ScheduleRow]:
    """Scan text-layer pages of a PDF and return all fire-rated schedule rows."""
    out: list[ScheduleRow] = []
    seen: set[str] = set()
    with fitz.open(pdf_path) as doc:
        pages = page_indexes if page_indexes is not None else range(doc.page_count)
        for i in pages:
            words = _display_words(doc[i])
            rows = parse_page_words(words) or parse_columnar_page(words)
            for row in rows:
                if row.tag not in seen:
                    seen.add(row.tag)
                    out.append(row)
    return out


def parse_ocr_spans(spans) -> list[ScheduleRow]:
    """Parse a door schedule from OCR'd text (raster/scanned pages — no PDF
    text layer). Reuses the same transposed/columnar layout logic as the
    text-layer path: OCR spans and PDF words are both "boxes with text," so no
    separate parsing rules are needed — just noisier input (OCR errors instead
    of a guaranteed-correct extraction) and a lower bar for what counts as a
    "row" (word-level fuzziness), reflected in confidence, not fabrication.
    """
    words = [(s.x, s.y, s.x + s.w, s.y + s.h, s.text.strip().upper()) for s in spans]
    return parse_page_words(words) or parse_columnar_page(words)
