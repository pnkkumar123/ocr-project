from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, overridable via environment or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FDD_", extra="ignore")

    app_name: str = "Fire Door Detection API"
    # Where uploaded PDFs and rendered page images are stored.
    storage_dir: Path = Path("storage")
    # DPI used when rasterizing PDF pages to PNG for the CV pipeline.
    render_dpi: int = 200
    # Reject uploads larger than this (architectural sets can be big, but cap it).
    max_upload_mb: int = 100
    # Allowed frontend origins for CORS (Next.js dev server by default).
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def pages_dir(self) -> Path:
        return self.storage_dir / "pages"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
