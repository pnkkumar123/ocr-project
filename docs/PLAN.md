# Fire Door Detection — Master Plan

## What we're building
An AI application that reads architectural blueprint PDFs and produces an
accurate inventory of **fire-rated doors** in a building. Built as a demo to win
an Upwork engagement, with a path to a commercial SaaS product for the fire-door
inspection industry.

### Core capabilities (from the job description)
1. Read architectural blueprint PDFs (vector CAD exports **and** scanned rasters).
2. Detect and identify door symbols on floor plans.
3. Read door tags and door schedules.
4. Cross-reference door schedules with floor plans.
5. Determine which doors are fire-rated (schedule rating, wall rating, legend).
6. Highlight identified fire doors directly on the drawings.
7. Export a complete door list to Excel/CSV.

## Deliverables (MVP)
- Blueprint PDF upload
- Automated fire-door detection
- Highlighted output drawing
- Door inventory export (Excel/CSV)
- Clean, documented source code

## Tech stack
| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js** (responsive, desktop-first viewer) | Demo shell, blueprint viewer, results table, export buttons |
| Backend API | **FastAPI (Python)** | Hosts the CV/OCR/ML pipeline |
| PDF | **PyMuPDF (fitz)** | Vector text + geometry extraction, high-DPI rendering |
| Detection | **YOLOv11 (Ultralytics)** | Door symbol detection + door-type classes |
| OCR | **PaddleOCR / EasyOCR / TrOCR** | Tag + schedule text (pretrained) |
| Tables | **Table Transformer (TATR) / PP-Structure** | Door schedule structure (pretrained) |
| Wall ratings | **YOLO-seg / U-Net** | Fire-barrier line segmentation (train) |
| Export | **pandas + openpyxl** | Excel/CSV |
| Deploy | Next.js → Vercel; FastAPI → Render/Railway/Fly | — |

> **Python versions:** the API (Phase 1) runs on 3.14. The ML stack
> (torch/ultralytics/opencv) should run in a **separate Python 3.12 venv** to
> avoid missing wheels on 3.14.

## The 5 trainable/model components
| # | Component | Model | Training |
|---|---|---|---|
| 1 | Door symbol detection | YOLOv11 detection | Fine-tune on door datasets + labeled real plans |
| 2 | Door type classification | YOLO classes / small CNN | Fine-tune (single/double/fire variants) |
| 3 | Text recognition (tags + schedule) | PaddleOCR/EasyOCR/TrOCR | Pretrained; fine-tune for CAD fonts if needed |
| 4 | Table structure recognition | Table Transformer / PP-Structure | Pretrained; fine-tune if schedules are messy |
| 5 | Fire-barrier / wall-rating lines | YOLO-seg / U-Net | Train (line-pattern segmentation) |

Everything else (tag↔door association, tag↔schedule join, fire-rating logic) is
**rule-based / geometric — no training.**

## Datasets (training)
- **Roboflow Universe** door datasets — YOLO-ready, fastest start
  (gilbertyolov5/yolo-door-detection, keerthi-edrbd/detecting-doors-from-floor-plan).
- **CubiCasa5K** — github.com/CubiCasa/CubiCasa5k (5k plans, polygons → boxes).
- **DoorDet** — arxiv 2508.07714 (35k door images derived from CubiCasa).
- **FloorPlanCAD** — arxiv 2105.07147, HF: Voxel51/FloorPlanCAD (vector CAD).
- **Gap:** none carry fire-rating labels — we label ~100–300 door symbols from
  real construction plans to fine-tune for the actual domain.

## Test PDFs
- Government procurement / bid portals (full construction sets w/ door schedules).
- WBDG VA Design-Build RFP + VA design standards (realistic, has schedules).
- University facilities design standards.

## Risks / notes
- **Biggest dependency = real construction PDFs** with door schedules. Nothing
  works end-to-end without 2–3 real sets (mix vector + scanned).
- Fire-rating determination has multiple signals; schedule rating is primary,
  wall/legend are fallbacks.
- Long processing time → move to async job queue (Celery/RQ + Redis) before prod.

See [PHASES.md](PHASES.md) for the build order and [ARCHITECTURE.md](ARCHITECTURE.md)
for the system design. Running log in [PROGRESS.md](PROGRESS.md).
Accuracy/trust strategy (reducing "needs review") in
[IMPROVING_ACCURACY.md](IMPROVING_ACCURACY.md). AWS resources & cost optimization
in [AWS_COST.md](AWS_COST.md). Cloud provider comparison (AWS/Azure/GCP) in
[CLOUD_COMPARISON.md](CLOUD_COMPARISON.md). Fine-tuning playbook (sourcing +
labeling real plans) in [FINE_TUNING.md](FINE_TUNING.md).
