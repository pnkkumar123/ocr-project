from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.models.schemas import AnalysisJob, DetectionSummary, DocumentInfo, JobStatus
from app.services.analysis import export_csv, get_job, run_job, start_analysis_job, summary_to_csv
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


@router.post("/{document_id}/analyze", response_model=AnalysisJob, status_code=202)
async def analyze_document(document_id: str, background_tasks: BackgroundTasks) -> AnalysisJob:
    """Start the full pipeline (detect, tag, resolve fire ratings, annotate) as
    a background job — large documents can take minutes (tiled YOLO + OCR
    fallback), too long for a client to hold an HTTP connection open. Returns
    immediately with a job to poll; the response never blocks on the pipeline."""
    job = start_analysis_job(document_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    background_tasks.add_task(run_job, job.job_id)
    return job


@router.get("/{document_id}/analyze/{job_id}", response_model=AnalysisJob)
async def get_analysis_job(document_id: str, job_id: str) -> AnalysisJob:
    """Poll a job started by POST /analyze. status: pending -> running ->
    completed (summary populated) or failed (error populated)."""
    job = get_job(job_id)
    if job is None or job.document_id != document_id:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return job


@router.get("/{document_id}/analyze/{job_id}/export.csv")
async def export_job_csv(document_id: str, job_id: str) -> PlainTextResponse:
    """Door inventory CSV from an already-completed job — no recompute, so
    this is fast regardless of how long the analysis itself took."""
    job = get_job(job_id)
    if job is None or job.document_id != document_id:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if job.status != JobStatus.completed or job.summary is None:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not completed yet")
    return PlainTextResponse(
        summary_to_csv(job.summary),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{document_id}_doors.csv"'},
    )


@router.get("/{document_id}/export.csv")
async def export_document_csv(document_id: str) -> PlainTextResponse:
    """Door inventory CSV, computed synchronously (blocking — re-runs the full
    pipeline). Convenience for scripts; prefer POST /analyze + the job-based
    export above from a browser/UI, which won't block on request timeout."""
    csv_text = export_csv(document_id)
    if csv_text is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{document_id}_doors.csv"'},
    )
