"""Model-assisted pre-labeling for fine-tuning (see docs/FINE_TUNING.md §3).

Runs the current door detector over real plan PDFs and writes an image +
YOLO-format label file per floor-plan page. You then upload the output folder
to Roboflow (or any labeling tool) and *correct* the boxes — delete false
positives, add missed doors, tighten sloppy boxes — instead of drawing every
box from scratch. That's 3-5x faster, and it's the same correction work the
in-app review UI will eventually capture from users automatically.

Two deliberate choices for *labeling* (different from production inference):

  - **Lower confidence threshold** (`--conf`, default 0.15 vs. 0.25 in prod).
    When pre-labeling you want recall, not precision: deleting a wrong box is
    a single click, but spotting and drawing a door the model never proposed
    is slow. Over-propose on purpose.
  - **Skip pages with no detections.** Schedules, details, and title sheets
    aren't floor plans and would just be noise in the training set.

Usage (ML venv, which has torch/ultralytics):
  ./.venv-ml/Scripts/python.exe scripts/prelabel.py ../datasets/pdfs/sanibel.pdf
  ./.venv-ml/Scripts/python.exe scripts/prelabel.py ../datasets/pdfs/*.pdf --max-pages 8
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402  (PyMuPDF)
from PIL import Image  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.pipeline.door_detector import DoorDetector  # noqa: E402
from app.services.pdf_ingest import ingest_pdf  # noqa: E402

# Single-class dataset: we're refining "where is a door", not classifying types.
# Door sub-type (single/double/fire) is a separate model bootstrapped from these
# same boxes later — see docs/FINE_TUNING.md §3 "Class strategy".
_DOOR_CLASS = 0


def _write_yolo_labels(detections, img_w: int, img_h: int, dst: Path) -> int:
    """YOLO format: one line per box, `<class> <cx> <cy> <w> <h>`, normalized 0-1."""
    lines = []
    for d in detections:
        cx = (d.box.x + d.box.w / 2) / img_w
        cy = (d.box.y + d.box.h / 2) / img_h
        w = d.box.w / img_w
        h = d.box.h / img_h
        # Clamp: tiled detection can produce boxes a hair outside the page edge,
        # and YOLO training rejects out-of-range coordinates.
        cx, cy, w, h = (min(max(v, 0.0), 1.0) for v in (cx, cy, w, h))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{_DOOR_CLASS} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    dst.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def _candidate_pages(pdf_path: Path, n_candidates: int) -> list[int]:
    """Cheaply rank pages by how 'floor-plan-like' they are, WITHOUT rendering
    or running the model — a full set can be hundreds of pages (Ann Arbor is
    799) and rendering + detecting all of them to find ~6 keepers is enormously
    wasteful.

    Signal: floor plans are dense linework (many vector draw ops) or a scanned
    image; title/notes/schedule sheets are mostly sparse text.

    Note this is the same page-filtering heuristic deliberately *rejected* for
    the production detection path (see PROGRESS.md) — there, wrongly skipping a
    page could silently lose a real fire door, which is unacceptable. Here it
    only picks which pages to *offer for labeling*, where missing one costs
    nothing: we just want ~6 good pages, not completeness. Same heuristic,
    different stakes.
    """
    scored: list[tuple[float, int]] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            try:
                drawings = len(page.get_drawings())
            except Exception:  # noqa: BLE001 — a malformed page shouldn't abort the scan
                drawings = 0
            images = len(page.get_images())
            # Scanned plans carry their linework inside an image, so an embedded
            # raster counts for a lot; pure-text sheets score near zero.
            score = drawings + images * 500
            if score > 200:
                scored.append((score, i))
    scored.sort(reverse=True)
    return sorted(idx for _, idx in scored[:n_candidates])


def prelabel_pdf(
    pdf_path: Path,
    out_dir: Path,
    detector: DoorDetector,
    max_pages: int | None,
    n_candidates: int,
) -> int:
    candidates = _candidate_pages(pdf_path, n_candidates)
    print(f"\n{pdf_path.name}: {len(candidates)} candidate pages -> {candidates}", flush=True)

    data = pdf_path.read_bytes()
    info = ingest_pdf(data, pdf_path.name)

    # Detect only on candidates, then rank by door count — most doors = floor plan.
    per_page = []
    for page in info.pages:
        if page.index not in candidates:
            continue
        src = settings.storage_dir / page.image_path
        doors = detector.detect(str(src), page.index)
        if doors:
            per_page.append((page, doors, src))
        print(f"  p{page.index}: {len(doors)} doors", flush=True)

    per_page.sort(key=lambda t: -len(t[1]))
    if max_pages is not None:
        per_page = per_page[:max_pages]

    stem = pdf_path.stem
    total_boxes = 0
    for page, doors, src in per_page:
        with Image.open(src) as im:
            img_w, img_h = im.size
        base = f"{stem}_p{page.index:04d}"
        shutil.copyfile(src, out_dir / f"{base}.png")
        n = _write_yolo_labels(doors, img_w, img_h, out_dir / f"{base}.txt")
        total_boxes += n
        print(f"  -> {base}.png  ({n} pre-labeled boxes)")

    return total_boxes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF(s) to pre-label")
    parser.add_argument(
        "--out", type=Path, default=Path("../datasets/label_inbox"),
        help="output folder for images + YOLO labels (default: ../datasets/label_inbox)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.15,
        help="detection threshold; lower than production on purpose (default: 0.15)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=6,
        help="keep only the N pages with the most doors per PDF, i.e. the floor "
             "plans (default: 6; use 0 for all pages with detections)",
    )
    parser.add_argument(
        "--candidates", type=int, default=20,
        help="how many drawing-dense pages per PDF to run detection on before "
             "ranking (default: 20). Bounds cost on huge sets.",
    )
    parser.add_argument(
        "--device", default=None,
        help="inference device, e.g. 'cuda' on Colab. Default None = CPU "
             "(production default); pre-labeling a large set is much faster on GPU.",
    )
    args = parser.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    max_pages = None if args.max_pages == 0 else args.max_pages

    detector = DoorDetector(conf=args.conf, device=args.device)

    grand_total = 0
    for pdf in args.pdfs:
        if not pdf.exists():
            print(f"skip (not found): {pdf}")
            continue
        grand_total += prelabel_pdf(pdf, out_dir, detector, max_pages, args.candidates)

    print(f"\nDone. {grand_total} pre-labeled boxes written to {out_dir.resolve()}")
    print("Next: upload that folder to Roboflow (images + .txt labels together),")
    print("then CORRECT the boxes — see docs/FINE_TUNING.md §3 for conventions.")


if __name__ == "__main__":
    main()
