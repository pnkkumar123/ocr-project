"""End-to-end smoke test: ingest a real PDF, run the full analysis pipeline
(detect + tag + fire-rating resolution), report.

Run with the ML venv:
  ./.venv-ml/Scripts/python.exe scripts/test_analysis.py <path-to-pdf>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis import run_analysis  # noqa: E402
from app.services.pdf_ingest import ingest_pdf  # noqa: E402


def main(pdf_path: str) -> None:
    data = Path(pdf_path).read_bytes()
    info = ingest_pdf(data, Path(pdf_path).name)
    print(f"ingested {info.document_id[:8]} — {info.page_count} pages")

    summary = run_analysis(info.document_id)
    print(
        f"doors: {summary.total_doors} total | "
        f"{summary.high_confidence} high-confidence | "
        f"{summary.needs_review} need review | "
        f"{summary.fire_rated_located} fire-rated located on plan"
    )
    print(f"schedule fire-door inventory ({len(summary.schedule_fire_doors)} doors):")
    for fd in summary.schedule_fire_doors:
        where = f"located on page {fd.located_on_page}" if fd.located_on_page is not None else "not located on plan"
        print(f"  {fd.tag}: {fd.fire_rating}  ({where})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../datasets/pdfs/lumberone_arch_full_set.pdf")
