# Fire Door Detection — Backend (FastAPI)

Phase-1 ingestion API. See [../docs/PLAN.md](../docs/PLAN.md),
[PHASES.md](../docs/PHASES.md), [ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Setup (Python 3.14 — API only)
```bash
cd backend
py -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## Run
```bash
./.venv/Scripts/uvicorn.exe app.main:app --reload
# open http://localhost:8000/docs
```

## Try it
`POST /api/documents` with a PDF → returns per-page metadata + rendered PNG
paths (served under `/storage/...`). Pages are classified `vector` / `raster` /
`mixed` to pick the extraction path.

## ML stack (Phases 3+)
Create a **separate Python 3.12 venv** and uncomment the ML block in
`requirements.txt` (torch/ultralytics/opencv wheels lag on 3.14). Detector/OCR
modules use lazy imports so this API runs without them.

## Config (env, prefix `FDD_`)
`FDD_RENDER_DPI` (200), `FDD_MAX_UPLOAD_MB` (100), `FDD_STORAGE_DIR`,
`FDD_CORS_ORIGINS`.
