from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.models.schemas import AnalysisSummary, DetectionSummary, DocumentInfo
from app.services.analysis import export_csv, run_analysis
from app.services.detection import run_detection
from app.services.pdf_ingest import ingest_pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentInfo)
async def upload_document(file: UploadFile = File(...)) -> DocumentInfo:
    """Upload an architectural PDF; render pages and classify vector/raster."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported")

    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File is {size_mb:.1f} MB; limit is {settings.max_upload_mb} MB",
        )
    if not data[:5] == b"%PDF-":
        raise HTTPException(status_code=400, detail="File does not look like a PDF")

    return ingest_pdf(data, file.filename or "upload.pdf")


@router.post("/{document_id}/detect", response_model=DetectionSummary)
async def detect_doors(document_id: str) -> DetectionSummary:
    """Run door detection on an already-uploaded document; returns detections,
    annotated page images, and a high-confidence / needs-review summary."""
    summary = run_detection(document_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    return summary


@router.post("/{document_id}/analyze", response_model=AnalysisSummary)
async def analyze_document(document_id: str) -> AnalysisSummary:
    """Run the full pipeline: detect doors, associate tags from the PDF text
    layer, resolve fire ratings via the door schedule, and annotate fire-rated
    doors distinctly. Returns the same reliability rollup as /detect plus
    fire-rating counts."""
    summary = run_analysis(document_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    return summary


@router.get("/{document_id}/export.csv")
async def export_document_csv(document_id: str) -> PlainTextResponse:
    """Door inventory (page, tag, confidence, fire rating) as CSV."""
    csv_text = export_csv(document_id)
    if csv_text is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{document_id}_doors.csv"'},
    )
