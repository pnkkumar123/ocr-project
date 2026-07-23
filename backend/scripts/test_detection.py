"""End-to-end smoke test: ingest a real PDF, run door detection, report.

Run with the ML venv:
  ./.venv-ml/Scripts/python.exe scripts/test_detection.py <path-to-pdf>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.detection import run_detection  # noqa: E402
from app.services.pdf_ingest import ingest_pdf  # noqa: E402


def main(pdf_path: str) -> None:
    data = Path(pdf_path).read_bytes()
    info = ingest_pdf(data, Path(pdf_path).name)
    print(f"ingested {info.document_id[:8]} — {info.page_count} pages")

    summary = run_detection(info.document_id)
    print(
        f"doors: {summary.total_doors} total | "
        f"{summary.high_confidence} high-confidence | "
        f"{summary.needs_review} need review"
    )
    # Pages with the most doors first — likely the floor plans.
    ranked = sorted(summary.pages, key=lambda p: -len(p.doors))[:6]
    for p in ranked:
        if p.doors:
            confs = [round(d.confidence, 2) for d in p.doors]
            print(f"  page {p.page_index}: {len(p.doors)} doors, conf {confs}")
            print(f"     annotated -> storage/{p.image_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../datasets/pdfs/lacity_door_window_schedule.pdf")
