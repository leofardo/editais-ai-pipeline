"""Configuração lida de variáveis de ambiente (definidas no .env / docker-compose)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    storage_backend: str
    gcs_bucket: str
    landing_dir: Path
    local_lake_dir: Path


def get_settings() -> Settings:
    return Settings(
        storage_backend=os.getenv("STORAGE_BACKEND", "local").lower(),
        gcs_bucket=os.getenv("GCS_BUCKET", ""),
        landing_dir=Path(os.getenv("LANDING_DIR", "data/landing")),
        local_lake_dir=Path(os.getenv("LOCAL_LAKE_DIR", "data/lake")),
    )
