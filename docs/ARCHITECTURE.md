# Architecture

## System overview
```
┌─────────────────────┐         ┌──────────────────────────────┐
│   Next.js frontend  │  HTTP   │   FastAPI backend (Python)   │
│  (Vercel)           │ ──────► │   (Render/Railway/Fly)       │
│                     │         │                              │
│ • PDF upload        │         │  Pipeline (app/pipeline):    │
│ • Blueprint viewer  │ ◄────── │   1 ingest      ✅           │
│ • Highlight overlay │  JSON   │   2 door_detector (YOLO)     │
│ • Results table     │         │   3 door_classifier          │
│ • Excel/CSV export  │         │   4 ocr (tags+schedule)      │
└─────────────────────┘         │   5 schedule_parser (TATR)   │
        ▲                       │   6 wall_rating (seg)        │
        │ /storage/*.png        │   7 cross_reference (rules)  │
        └───────────────────────│   8 annotate + export        │
                                └──────────────────────────────┘
                                   ├─ PyMuPDF, OpenCV, Pillow
                                   ├─ Ultralytics (YOLOv11)
                                   ├─ PaddleOCR/EasyOCR, TATR
                                   └─ storage/ (uploads, pages)
```

## Backend layout
```
backend/
  requirements.txt          # Phase-1 deps active; ML deps commented (3.12 venv)
  app/
    main.py                 # FastAPI app, CORS, static /storage mount, routers
    core/config.py          # Settings (storage dirs, DPI, limits) via env FDD_*
    models/schemas.py       # Pydantic: DocumentInfo, PageInfo, DoorDetection...
    api/routes/
      health.py             # GET /health
      documents.py          # POST /api/documents (upload + ingest)
    services/
      pdf_ingest.py         # PyMuPDF render + vector/raster classification ✅
    pipeline/
      __init__.py           # documents the 8-stage order
      door_detector.py      # #1 YOLOv11  (lazy torch import)
      ocr.py                # #3 EasyOCR  (lazy import)
      schedule_parser.py    # #4 TATR/PP-Structure  (stub)
      wall_rating.py        # #5 YOLO-seg/U-Net      (stub)
      cross_reference.py    # rule-based tag↔schedule join + fire logic
  storage/                  # gitignored: uploads/*.pdf, pages/<doc>/<n>.png
```

## Data flow
1. **Upload** → `POST /api/documents` receives a PDF (validated: PDF magic
   bytes, size cap `FDD_MAX_UPLOAD_MB`).
2. **Ingest** → `ingest_pdf()` persists the PDF, renders each page to PNG at
   `FDD_RENDER_DPI`, classifies each page:
   - `vector`  — text ≥80 chars **and** ≥50 draw ops (CAD export)
   - `raster`  — little text / no geometry (scan) → OCR path
   - `mixed`   — vector geometry over an embedded image
   Returns `DocumentInfo` with per-page metadata + image paths.
3. **Detect** (Phase 3) → YOLO on each page PNG → `DoorDetection[]`.
4. **Read** (Phase 2/3) → OCR tags + parse door schedule → `ScheduleRow[]`.
5. **Cross-reference** (Phase 4) → associate tags to doors, join to schedule,
   resolve `fire_rated` / `fire_rating` / `rating_source`.
6. **Annotate + export** (Phase 6) → highlighted PDF + Excel/CSV.

## Page classification heuristic
`app/services/pdf_ingest.py` uses **3 independent signals** (thresholds
`_TEXT_CHARS_MIN=80`, `_DRAWINGS_VECTOR_MIN=50`):
- **text layer** (`PageInfo.has_text_layer`) → schedule readable **without OCR**
- **vector geometry** → door linework is exact vector, not a bitmap
- **raster images** → drawing is (partly) a bitmap → needs image CV

Kinds: `vector` (text+linework, no bitmap), `raster` (true scan, no text layer),
`mixed` (text/vector content over raster imagery — common in real permit sets).
Whenever `has_text_layer` is true we read the schedule from the text layer
directly (faster, exact) regardless of `kind`. Validated on the LA City set:
23/41 pages carry a usable text layer.

## Model training vs inference (split)
Training runs on **Google Colab** (free GPU) via `colab/train_fire_door_models.ipynb`;
exported `.pt` weights land in `backend/models/`. The backend loads them for
**CPU inference** (`.venv-ml`, Python 3.12). No GPU or training libs needed to serve.

## Fire-rating resolution priority
`schedule rating` (primary) > `wall rating` (fallback) > `legend default`.
Tokens treated as fire-rated: `20/45/60/90 MIN`, `3 HR`, `FR`, `RATED`
(`cross_reference._FIRE_RATING_TOKENS`).

## Model runtime isolation
API boots without torch — detector/OCR use **lazy imports**, so the heavy ML
stack (Python 3.12 venv) can live/scale separately (even a different service)
without blocking the ingestion API on 3.14.

## Config (env, prefix `FDD_`)
`FDD_STORAGE_DIR`, `FDD_RENDER_DPI` (default 200), `FDD_MAX_UPLOAD_MB` (100),
`FDD_CORS_ORIGINS`.

## Future (SaaS)
Async job queue (Celery/RQ + Redis), object storage (S3), Postgres for
projects/doors, auth + per-customer accounts, model registry for fine-tunes.
