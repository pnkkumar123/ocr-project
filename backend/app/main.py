from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import documents, health
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()
# Serve rendered page PNGs so the Next.js viewer can load them directly.
app.mount("/storage", StaticFiles(directory=settings.storage_dir), name="storage")

app.include_router(health.router)
app.include_router(documents.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
