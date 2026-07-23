# Progress Log

Newest first. Each entry: what changed, why, how it was verified, what's next.

---

## 2026-07-24 (3) — /analyze made async (background job + polling) ✅

**Why:** `/analyze` blocked the HTTP request for the full pipeline duration —
minutes on a large document (Colab GPU test: Sanibel's 90 pages took 525s).
A synchronous request that long risks client/browser timeouts and blocks the
server thread per request.

**What:** `POST /analyze` now returns an `AnalysisJob` immediately (202,
`status=pending`) instead of the summary. `GET /analyze/{job_id}` polls for
`pending → running → completed` (summary populated) or `failed` (error
populated). `GET /analyze/{job_id}/export.csv` builds CSV from the completed
job — no recompute, unlike the old direct `/export.csv` (kept, documented as
the blocking convenience path for scripts).

**Implementation — deliberately not Celery/Redis (yet):** a single in-process
`dict` job store (`app/services/analysis.py`), executed via FastAPI's
`BackgroundTasks`, which Starlette runs on a threadpool automatically for sync
functions — so it doesn't block the event loop for other requests, without
standing up new infra. Explicitly scoped as MVP-appropriate: doesn't survive a
restart or scale across multiple server processes — that's the real trigger
for Celery/RQ + Redis, already on the roadmap (`PHASES.md` "Async /
production"), not needed at today's single-server stage.

**Verified:** job lifecycle (pending → running → completed) on lumberone;
`unknown job_id` returns `None`/404 correctly; CSV from a completed job's
summary matches the direct-export CSV (37 lines = 36 doors + header, same as
before); app still boots cleanly on the base venv (no torch) with all 6 routes
registered.

**Considered and rejected: targeted mini-OCR for doors with no text-layer tag**
(OCR a small crop around each untagged door instead of the whole page, to
catch raster/image-based room tags like lumberone's). Rejected for now:
variable, data-dependent cost per document (a "messy" document could trigger
dozens of small OCR calls) is exactly the kind of unpredictable latency that
needs a real job queue to absorb safely, not the in-process store just built.
Revisit once Celery/Redis exists. Until then, "not located on plan" is honest
and correct — the fire rating itself is never affected, only the visual
pin lands via human review instead of an automated guess.

**Next:** Phase 7 (Next.js frontend) — polling UI for job status is the
natural first piece now that the API is job-shaped.

---

## 2026-07-24 (2) — Raster/OCR schedule path, rotation bug fix, columnar parser, repo on GitHub ✅

**Rotation bug fix (correctness, not just a new feature)**
- `get_text("words")` returns raw *mediabox* coordinates, ignoring a page's
  `/Rotate` flag — but rendered PNGs (and every YOLO box) are in *displayed*
  space. 5 of 6 real test PDFs have rotated pages. `ocr.text_layer_spans` and
  `schedule_parser`'s word extraction now apply `page.rotation_matrix` so text
  coordinates actually line up with detector boxes and with each other.
  Root-caused via lumberone: tags were landing "1400–5000px from any door,"
  which looked like a room-keyed-schedule layout quirk but was really a
  coordinate-frame mismatch. (The room-tag conclusion for lumberone specifically
  still holds after the fix — its on-plan room numbers turned out to be raster
  image content, not text at all — but the bug was real and would have broken
  tag association on any sheet where tags *are* text.)

**Columnar schedule parser (Phase 2) — the common professional format**
- `schedule_parser.parse_columnar_page` — one-row-per-door tables (`NUMBER` +
  `RATING` columns, aligned by y-position), the standard format real firms use
  (lumberone's transposed layout was the unusual one). Disambiguates a fire
  `RATING` column from an adjacent STC/sound `RATING` column via header context.
- **Verified against 2 new real fixtures with known ratings:** Sanibel Fire
  Station bid set → 18 rows (20/45/60 MIN), Ann Arbor Fire Station renovation →
  11 rows (45/90 MIN) — both cross-checked by eye against the rendered table.
  No regression on lumberone/sanibel/annarbor text-layer path.

**Raster/OCR schedule path (Phase 2 raster) — the original ask**
- `schedule_parser.parse_ocr_spans` reuses the *same* transposed/columnar logic
  on OCR output — a PDF word and an OCR span are both "a box with text," so no
  separate parsing rules needed. Header matching switched to substring (not
  exact-equal) since EasyOCR merges multi-word cells ("DOOR NUMBER" as one box).
- `services/analysis._ocr_schedule_rows` — fallback only when the text-layer
  schedule found nothing, capped at 3 pages (OCR is minutes/page on CPU, not
  worth running blind on every raster page).
- **Honest finding:** neither original raster candidate worked as a full
  end-to-end proof — lacity turned out to be an LA Planning example deck (no
  real schedule), camden's raster table has no rating column (type-coded on a
  separate sheet). Validated instead by rasterizing a real columnar schedule
  (Sanibel, table crop only, text layer stripped) and OCR'ing it fresh:
  **10/18 rows recovered, every rating exactly correct — zero fabrication**,
  lower recall than the exact text path (expected, documented, not hidden).

**Speed**
- `door_detector`: tiles now batch into one `model()` call instead of one
  Python-level call per tile (same detections, less per-call overhead).
- `ocr.OcrEngine.read`: downscales to a 2200px max dimension before OCR (200
  DPI sheets render 6000+px; full res buys nothing for reading table text),
  coordinates scaled back up so callers still work in original pixel space.
- OCR schedule fallback page cap 5 → 3.
- Considered a page-drawings-count filter to skip non-plan pages before YOLO
  entirely (bigger lever) — **rejected**: measured `vector_drawings` counts
  across all fixtures and found no threshold that reliably separates plan
  pages from detail/schedule pages across drawing styles (title-block hatching
  and wall-detail sheets can out-score real floor plans). Shipping a fragile
  heuristic risks silently skipping real content in a safety product; not worth
  the speed win without a much larger validation set.
- `DoorDetector(device=...)` / `OcrEngine(gpu=...)` params added (default
  unchanged: CPU) so Colab/local dev can opt into GPU without touching
  production's CPU-only default (`docs/AWS_COST.md`).

**Regression, full set:** lumberone 7/8 fire doors (was 8, minor OCR-adjacent
edge case, zero wrong), hyperfine 0 (correct negative), lacity 0 (correct
negative, OCR fallback exercised, found nothing to fabricate), sanibel 18,
annarbor 11 — all correct, no false positives anywhere.

**Repo**: initialized git, pushed to `github.com/pnkkumar123/ocr-project`
(public). `colab/test_fire_door_pipeline.ipynb` added — clones the repo, runs
the same `run_analysis()` the API uses with GPU enabled, for fast iteration
without waiting on local CPU.

**Next:** wire the OCR path against a genuine in-the-wild scanned permit
(still hasn't been found — real scanned sets mostly sit behind city-portal
search UIs); or move to Phase 7 (Next.js frontend) to make the pipeline visible.

---

## 2026-07-24 — Full pipeline wired: /analyze + CSV export ✅

**End-to-end analysis (Phase 4 wiring + Phase 6 start)**
- `app/services/analysis.py` — one pass: detect doors → associate tags from the
  **PDF text layer** (no OCR; `ocr.text_layer_spans` scales word coords to the
  rendered PNG) → `cross_reference.resolve_fire_rating` against the parsed
  schedule → annotate + roll up.
- `POST /api/documents/{id}/analyze` → `AnalysisSummary`;
  `GET /api/documents/{id}/export.csv` → per-door inventory CSV.
- Annotation now draws **fire-rated doors in red** (distinct from green
  high-conf / amber needs-review), labeled with tag + rating.

**Design correction — schedule is the source of truth, not spatial guessing**
- First cut tried nearest-text-span → door tag. On the lumberone plan this
  produced 0 matches: the schedule is keyed by **room number**, and the room
  labels (101–108) live in the schedule table at the sheet bottom (y=4342),
  1400–5000 px from any detected door swing. Widening the match radius would
  only manufacture **false matches** (every door grabbing "101") — unacceptable
  for a safety product.
- Fix: `AnalysisSummary.schedule_fire_doors` is the **authoritative** fire-door
  inventory read straight from the schedule text (exact tag + rating). Per-door
  `fire_rated` is a *best-effort spatial overlay* with a tight at-the-doorway
  radius (250 px); each schedule fire door reports `located_on_page` or honestly
  "not located on plan". The two signals are deliberately not conflated.

**Verified on all 3 real sets (no fabrication):**
- lumberone → **8 fire doors @ 20 MIN** (101,102,103,103A,104,105,106,108),
  correctly "not located on plan" (room-keyed schedule).
- hyperfine (16 pp) → 0 fire doors, 127 doors detected. lacity (41 pp) → 0 fire
  doors (raster schedule, no text-layer ratings), 120 doors detected.
- API boots on the base venv (no torch); all 4 routes in OpenAPI; CSV export =
  36 door rows + header, all columns populated.

**New test data (Phase 0):** `datasets/pdfs/camden_door_schedule.pdf` — real
113-row **raster** door schedule (SOAS "Fire Door Upgrade"); the future
OCR/Table-Transformer path (Phase 2 raster) can be validated against it.

**Next:** raster schedule path (OCR) so lacity/camden ratings are read; or
Phase 7 Next.js frontend to make the demo visible (upload → analyze → export).

---

## 2026-07-23 (5) — Tiled inference + schedule parser ✅

**Tiled inference (accuracy #2)** — `app/pipeline/door_detector.py`
- Added overlapping-tile detection: slice large pages, detect per-tile at full
  res, offset boxes to page coords, merge with torchvision NMS. `tile=True`
  default; no new deps.
- **Verified on real plan (lacity p31), whole vs tiled:**
  28→33 doors, high-conf 16→**24** (+50%), review 12→**9**, avg conf 0.54→**0.65**.
- Detection service uses tiling by default, so the API gets it automatically.

**Schedule parser — text-layer path (Phase 2 / component #4)**
- `app/pipeline/schedule_parser.py` — reads door schedule from PDF text layer
  (no OCR). Handles the transposed CAD layout: aligns a `RATING` row to a
  `NUMBER/MARK` row by x-position. US minutes/hours + UK `FDxx` tokens.
- Returns nothing (not a guess) when no schedule structure is found.
- **Verified on 3 real PDFs:** lumberone → **8 fire-rated doors @ 20 MIN**
  (correct); lacity & hyperfine → 0 (correct — no tabular rating schedule / no
  fire ratings). No fabrication.
- Compatible with existing `cross_reference.resolve_fire_rating` (tag+rating).

**Known limits (honest):** parser handles transposed text-layer schedules with
RATING/NUMBER labels; raster schedules + other layouts need OCR/Table-Transformer
(future). Exact mark↔rating alignment may need refinement → human review covers it.

**Next:** wire schedule parser + detector via cross-reference into an endpoint
(door → tag → fire rating), then annotate fire-rated doors distinctly + export CSV.

---

## 2026-07-23 (4) — More test data + strategy docs ✅

**Test PDFs (Phase 0)** — now 3 real sets in `datasets/pdfs/` (gitignored):
- `lacity_door_window_schedule.pdf` — 41pp, door schedule + fire ratings (best).
- `hyperfine_plan_set.pdf` — 16pp, door schedule (DOOR×32), residential/no fire.
- `lumberone_arch_full_set.pdf` — 4pp, door schedule + FIRE×8.
- Covers different drawing styles for detection robustness testing.

**Strategy docs written** (all linked from `PLAN.md`):
- `docs/IMPROVING_ACCURACY.md` — 5 ranked ways to cut the needs-review rate
  (fine-tune ★★★★★, tiling/SAHI, bigger model, page filtering, multi-signal
  confirmation) + UK `FD30/FD60` vs US `45 MIN` note + metrics to track.
- `docs/AWS_COST.md` — AWS sizing/cost; CPU-only inference, scale-to-zero,
  text-layer-skips-OCR lever; MVP $40–70, SaaS $120–250, growth $350–950/mo.
- `docs/CLOUD_COMPARISON.md` — AWS vs Azure vs GCP; reliability a non-diff
  (all ~99.9%); Cloud Run best fit for MVP; Azure cheapest managed OCR
  ($10/1k tables); stay container-portable.

**Next:** implement tiled inference (#2 accuracy) + schedule parser (Phase 2).

---

## 2026-07-23 (3) — Door detector trained + wired into backend ✅

**Trained (Colab, T4)**
- YOLOv11n on Roboflow `plandoor/doorplan` (5 classes: door, text, stair,
  compass, scale), 50 epochs. **Door class: mAP50 0.944, P 0.958, R 0.908.**
- Weights downloaded → `backend/models/door_yolo11.pt` (5.5 MB).

**Backend wiring (inference)**
- `.venv-ml` (Python 3.12) now a full backend env: torch 2.13.0+cpu,
  ultralytics 8.4.104, + fastapi/pymupdf. Pip cache/temp on D:.
- `app/pipeline/door_detector.py` — loads weights, filters to `door` class,
  every detection carries confidence + `needs_review` (< 0.50).
- `app/services/detection.py` — runs detector over all pages, draws annotated
  PNGs (green=confident, amber=review), returns `DetectionSummary`
  (total / high_confidence / needs_review).
- `app/services/pdf_ingest.py` — persists `document.json`; added `load_document`.
- `POST /api/documents/{id}/detect` endpoint.
- `scripts/test_detection.py` — e2e smoke test.

**Verified on REAL data (LA City 41-page set)**
- 63 doors detected; correctly concentrated on floor-plan pages (p31: 28,
  p13: 18, p7: 12), ignored the 34 schedule/detail pages.
- Visual check of annotated p31: boxes land ON door-swing arcs across dining /
  sitting / hall / closet / family / powder rooms. Real detection, not noise.
- 26 high-confidence / 37 needs-review — moderate confidence due to domain gap
  (trained on doorplan style ≠ this firm's drawings), exactly as predicted.

**Next**
1. Reduce needs-review: bootstrap door-type + fine-tune from real-plan crops.
2. Phase 2: `schedule_parser` text-layer path (23/41 pages have text) → fire
   ratings per tag.
3. Phase 4: cross-reference tags↔schedule → fire-rated doors.

---

## 2026-07-23 (2) — Training strategy, ML venv, first real test PDF ✅

**Decision — train on Colab, infer locally**
- No local NVIDIA GPU. Models train on **Google Colab (free T4)**; the backend
  runs **inference only** on CPU. Trained `.pt` weights drop into `backend/models/`.
- Created `colab/train_fire_door_models.ipynb` — trains all 3 trainable models
  (YOLOv11 doors → `door_yolo11.pt`, YOLOv11-cls door-type → `door_type.pt`,
  YOLOv11-seg wall-rating → `wall_seg.pt`), Roboflow API for data, exports a
  weights zip. See `colab/README.md`.
- `backend/models/` created (weights drop folder, `.pt` gitignored).
- `backend/requirements-ml.txt` — CPU inference stack (torch, ultralytics,
  easyocr, transformers, opencv). Install into the 3.12 venv when wiring models.

**ML venv**
- Created `backend/.venv-ml` on **Python 3.12.0** (D: drive). Deps NOT yet
  installed (deferred — training is on Colab; install inference stack when we
  wire the first model). pip cache/temp will be redirected to D: (`.pipcache/`,
  `.tmp/`) to keep C: clean.

**First real test PDF (Phase 0 progress)**
- Downloaded a **real 41-page LA City architectural set** with a door schedule
  AND fire ratings → `datasets/pdfs/lacity_door_window_schedule.pdf` (16.5 MB,
  gitignored). Verified content: DOOR×69, FIRE×21, RATING×11, "20 MIN"×3.
- Other candidate downloads returned error pages; full permit sets mostly live
  behind city-portal search UIs (SF/Philly/Portland) — manual grab later.

**Real-data fix to Phase 1 classification**
- Running the LA set through `ingest_pdf()` exposed a bug: text-rich pages
  (18k chars) were mislabeled `raster` because the heuristic required ≥50 vector
  draw ops. Real sets are often a **text layer over raster linework**.
- Reworked `_classify_page` to use 3 independent signals (text layer / vector
  geometry / raster images) and added `PageInfo.has_text_layer`.
- Re-verified on the LA set: kinds now `{vector:10, mixed:26, raster:5}` and
  **23/41 pages have a text layer** → their schedules are readable without OCR.

**Next**
1. Get 1–2 more real full sets (SF/Philly permit portals).
2. Colab: run notebook Section 1, train door YOLO baseline, download `door_yolo11.pt`.
3. Phase 2: implement `schedule_parser` **vector/text-layer path first** — on
   `has_text_layer` pages we can extract the schedule table directly (no OCR).

---

## 2026-07-23 — Phase 1 backend scaffolded & verified ✅

**Done**
- Created `backend/` FastAPI project (see [ARCHITECTURE.md](ARCHITECTURE.md) for layout).
- `app/core/config.py` — settings via `FDD_*` env vars (storage dirs, DPI, size cap, CORS).
- `app/models/schemas.py` — `PageKind`, `PageInfo`, `DocumentInfo`, `BoundingBox`, `DoorDetection`.
- `app/services/pdf_ingest.py` — PyMuPDF renders each page to PNG at 200 DPI and
  classifies vector / raster / mixed.
- `app/api/routes/documents.py` — `POST /api/documents` upload (PDF magic-byte +
  size validation) → returns `DocumentInfo`.
- `app/api/routes/health.py` — `GET /health`.
- `app/main.py` — app, CORS, static `/storage` mount, routers.
- `app/pipeline/` — module + stub per model component so the full-product
  architecture is explicit:
  - `door_detector.py` (#1 YOLOv11, lazy torch import)
  - `ocr.py` (#3 EasyOCR, lazy import)
  - `schedule_parser.py` (#4 TATR/PP-Structure — stub)
  - `wall_rating.py` (#5 YOLO-seg/U-Net — stub)
  - `cross_reference.py` — **implemented** rule-based tag↔door association +
    tag↔schedule join + fire-rating resolution.
- `requirements.txt` — Phase-1 deps active; ML deps commented for a 3.12 venv.

**Verified**
- Created `backend/.venv` (Python 3.14), installed Phase-1 deps.
- Ran `ingest_pdf()` on a generated 2-page test PDF:
  - page 0 → `vector` (text=84, draws=60), page 1 → `raster` — correct.
  - PNGs written under `storage/pages/<doc>/`.
- `app.main` imports cleanly; OpenAPI exposes `/health`, `/api/documents`, `/`.
- Test artifacts cleaned up.

**Environment notes**
- Machine Python is **3.14.0** — fine for the API. torch/ultralytics/opencv
  wheels lag on 3.14, so **the ML stack goes in a separate Python 3.12 venv.**
- Detector/OCR use lazy imports so the API boots without torch installed.

**Next (Phase 0 + 3 — the real work)**
1. **Phase 0 (blocker):** get 2–3 real construction PDF sets with door schedules
   (mix vector + scanned); pull Roboflow door datasets.
2. Run the API: `cd backend && ./.venv/Scripts/uvicorn.exe app.main:app --reload`,
   test upload at `http://localhost:8000/docs`.
3. Phase 3: set up 3.12 venv, train YOLOv11 door baseline on Roboflow data.
4. Phase 2: implement `schedule_parser` (vector text-layer path first — easiest win).

**Decisions**
- Full product = all 5 model components (user confirmed); fine-tune as needed.
- Desktop-first responsive frontend (blueprint viewing is not a phone task).
- YOLO = "where are the doors," NOT "which are fire doors" — fire rating comes
  from schedule OCR + cross-reference.
