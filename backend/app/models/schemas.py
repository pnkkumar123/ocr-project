from enum import Enum

from pydantic import BaseModel, Field


class PageKind(str, Enum):
    """How a PDF page is authored — drives which extraction path we use."""

    vector = "vector"          # CAD export: text + line geometry available
    raster = "raster"          # scanned/flattened image: needs OCR + image CV
    mixed = "mixed"            # vector geometry over a raster background


class PageInfo(BaseModel):
    index: int = Field(..., description="0-based page number")
    width_pt: float
    height_pt: float
    kind: PageKind
    has_text_layer: bool = Field(
        ..., description="Page has an extractable text layer (schedule readable without OCR)"
    )
    text_chars: int = Field(..., description="Characters in the vector text layer")
    vector_drawings: int = Field(..., description="Count of vector draw ops")
    raster_images: int = Field(..., description="Embedded raster images on the page")
    image_path: str = Field(..., description="Rendered PNG path relative to storage")
    render_dpi: int


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    page_count: int
    pages: list[PageInfo]


class BoundingBox(BaseModel):
    """Axis-aligned box in rendered-image pixel coordinates."""

    x: float
    y: float
    w: float
    h: float


class DoorDetection(BaseModel):
    """Output of component #1 (YOLO) + #2 (type classification)."""

    page_index: int
    box: BoundingBox
    confidence: float
    door_type: str = "unknown"          # single | double | fire | ...
    tag: str | None = None              # e.g. "101A", filled by OCR association
    fire_rated: bool | None = None      # resolved via schedule cross-reference
    fire_rating: str | None = None      # e.g. "45 MIN", "90 MIN"
    rating_source: str | None = None    # schedule | wall | legend
    needs_review: bool = False          # low-confidence -> flag, don't silently trust


class PageDetections(BaseModel):
    page_index: int
    image_path: str                     # annotated PNG (relative to storage)
    doors: list["DoorDetection"]


class DetectionSummary(BaseModel):
    """Reliability-oriented rollup shown to the user."""

    document_id: str
    total_doors: int
    high_confidence: int                # confidence >= review threshold
    needs_review: int                   # low-confidence, flagged for a human
    pages: list[PageDetections]


class ScheduleFireDoor(BaseModel):
    """A fire-rated door read directly from the door schedule (text layer).

    This is the *authoritative* fire-door inventory — exact tag + rating from the
    schedule, no visual guessing. Independent of whether we could locate the door
    symbol on the plan (`located`)."""

    tag: str
    fire_rating: str
    located_on_page: int | None = None  # page where a matching door symbol was tagged, if any


class AnalysisSummary(BaseModel):
    """Full pipeline rollup: detection + tag association + fire-rating resolution.

    Two independent signals, deliberately not conflated:
      - `schedule_fire_doors`: exact inventory from the schedule text (source of
        truth for *how many* fire doors and their ratings).
      - per-door `fire_rated` in `pages`: best-effort spatial match of a detected
        symbol to a schedule mark; may be < the schedule count when the drawing
        keys doors by room number rather than tagging each door.
    """

    document_id: str
    total_doors: int
    high_confidence: int                # confidence >= review threshold
    needs_review: int                   # low-confidence, flagged for a human
    fire_rated_located: int             # doors visually matched to a fire rating
    schedule_fire_doors: list[ScheduleFireDoor]  # authoritative inventory from schedule
    pages: list[PageDetections]


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class AnalysisJob(BaseModel):
    """Background analysis job — /analyze returns one of these immediately
    instead of blocking the request for however long detection+OCR takes
    (minutes, on a large document). Poll GET .../analyze/{job_id} for status."""

    job_id: str
    document_id: str
    status: JobStatus
    summary: AnalysisSummary | None = None
    error: str | None = None
