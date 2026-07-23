# Build Phases

Each phase is independently demoable. Status: ✅ done · 🚧 in progress · ⬜ todo

## Phase 0 — Data & framing 🚧 (critical path)
Collect 2–3 real architectural PDF sets with door schedules (mix vector +
scanned). Without these, nothing works end-to-end.
- [x] 1st real set: LA City 41-page set w/ door schedule + fire ratings
      (`datasets/pdfs/lacity_door_window_schedule.pdf`, verified)
- [ ] 1–2 more real sets (SF/Philly/Portland permit portals)
- [ ] Pull Roboflow door datasets for YOLO training (via Colab notebook)
- [ ] Note schedule formats / fire-rating conventions seen

## Training infra — Colab ✅
Train on Google Colab (free GPU), infer locally on CPU.
- [x] `colab/train_fire_door_models.ipynb` — YOLOv11 doors + door-type + wall-seg
- [x] `backend/models/` weights drop folder; `backend/requirements-ml.txt`
- [x] `backend/.venv-ml` (Python 3.12) created (inference deps install deferred)

## Phase 1 — PDF ingestion + rendering ✅
FastAPI backend that ingests a PDF, classifies each page vector/raster/mixed,
and rasterizes pages to PNG for the CV pipeline.
- [x] FastAPI app + CORS + static serving of rendered pages
- [x] `POST /api/documents` upload endpoint (validation, size cap)
- [x] `pdf_ingest.ingest_pdf()` — PyMuPDF render + page classification
- [x] Pydantic schemas (DocumentInfo / PageInfo / DoorDetection)
- [x] Verified: 2-page test PDF → correct vector/raster split, PNGs written

## Phase 2 — Door schedule extraction ✅ (text-layer + raster/OCR both working)
Locate + parse door schedule into structured rows keyed by tag.
- [x] Transposed CAD layout: RATING↔NUMBER row aligned by x-position, US + UK
      tokens (`parse_page_words`). Verified: lumberone → 7-8 doors @ 20 MIN.
- [x] Columnar layout (the common professional format): NUMBER + RATING
      columns aligned by y-position, disambiguates fire vs. STC/sound RATING
      columns (`parse_columnar_page`). Verified: Sanibel Fire Station → 18
      doors (20/45/60 MIN), Ann Arbor Fire Station → 11 doors (45/90 MIN).
- [x] Raster path: EasyOCR + the *same* transposed/columnar logic reused on OCR
      spans (`parse_ocr_spans`), gated to pages with no text layer, capped at 3
      pages. Verified via rasterized real schedule: 10/18 rows recovered, every
      rating exactly correct, zero fabrication (lower recall than text-layer,
      as expected).
- [x] Page-rotation bug fixed — word coordinates now match rendered/detector
      space (was silently breaking tag cross-reference on rotated sheets).
- [ ] Capture size/type/hardware columns (currently tag + fire-rating only)
- [ ] Validate raster path against a genuine in-the-wild scanned schedule
      (candidates so far were either not real schedules or had no rating column)
- Slot: `app/pipeline/schedule_parser.py`, `app/pipeline/ocr.py`

## Phase 3 — Door detection + tag OCR 🚧 (slot ready)
- [ ] Train YOLOv11 on Roboflow door datasets (baseline)
- [ ] Fine-tune on labeled real-plan door symbols
- [ ] Door-type classification (single/double/fire) — component #2
- [ ] OCR tags near doors (component #3)
- Slots: `app/pipeline/door_detector.py`, `app/pipeline/ocr.py`

## Phase 4 — Cross-reference + fire-rating logic ✅ (text-layer path)
- [x] Tag↔door nearest-neighbor association (`cross_reference.associate_tags`),
      mark-shaped filter + tight at-doorway radius (no false matches)
- [x] Tag↔schedule join + fire-rating resolution (`resolve_fire_rating`)
- [x] Wired to real detector + parser via `services/analysis.run_analysis`
- [x] Authoritative schedule fire-door inventory surfaced independently of
      spatial matching (`AnalysisSummary.schedule_fire_doors`)
- [ ] Wall-rating fallback signal (component #5)
- Slot: `app/pipeline/cross_reference.py`, `app/services/analysis.py`

## Phase 5 — Wall / fire-barrier line detection ⬜ (training required)
- [ ] Label fire-barrier line patterns
- [ ] Train YOLO-seg / U-Net segmentation
- [ ] Associate wall ratings with nearby doors
- Slot: `app/pipeline/wall_rating.py`

## Phase 6 — Annotate + export 🚧 (PNG + CSV done)
- [x] Draw highlight boxes on rendered pages (PIL) — green high-conf / amber
      review / **red fire-rated**, labeled with tag + rating (`services/analysis`)
- [x] Export door inventory to CSV (`GET /api/documents/{id}/export.csv`)
- [ ] Annotated multi-page PDF export + Excel (openpyxl) if a client wants it

## Phase 7 — Next.js frontend ⬜
- [ ] Upload → processing state → interactive viewer with highlight toggle
- [ ] Results table + download buttons
- [ ] Wire to FastAPI

## Phase 8 — Demo polish + proposal ⬜
- [ ] 60–90s screen capture: upload → detect → highlight → export
- [ ] Proposal: stack, MVP timeline (3–5 wks), vector-vs-scanned question

## Async / production (later)
- [ ] Job queue (Celery/RQ + Redis), object storage, auth, per-customer accounts
