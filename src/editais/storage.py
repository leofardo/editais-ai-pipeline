"""Abstração do data lake: a mesma interface grava no disco local ou no GCS.

Assim o pipeline roda sem GCP no começo e, trocando STORAGE_BACKEND=gcs,
passa a gravar no bucket sem mudar nenhuma linha da DAG.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from editais.config import Settings


class Storage(Protocol):
    def exists(self, key: str) -> bool: ...
    def uri(self, key: str) -> str: ...
    def upload_file(self, local_path: Path, key: str) -> str: ...
    def write_text(self, key: str, content: str) -> str: ...
    def read_text(self, key: str) -> str: ...
    def local_path(self, key: str, tmp_dir: Path) -> Path: ...


class LocalStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _path(self, key: str) -> Path:
        return self.base_dir / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def uri(self, key: str) -> str:
        return str(self._path(key))

    def upload_file(self, local_path: Path, key: str) -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        return str(dest)

    def write_text(self, key: str, content: str) -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return str(dest)

    def read_text(self, key: str) -> str:
        return self._path(key).read_text(encoding="utf-8")

    def local_path(self, key: str, tmp_dir: Path) -> Path:
        return self._path(key)  # já está no disco, não precisa baixar


class GCSStorage:
    def __init__(self, bucket_name: str):
        from google.cloud import storage  # import tardio: só exige a lib se usar GCS

        self.bucket_name = bucket_name
        self.bucket = storage.Client().bucket(bucket_name)

    def exists(self, key: str) -> bool:
        return self.bucket.blob(key).exists()

    def uri(self, key: str) -> str:
        return f"gs://{self.bucket_name}/{key}"

    def upload_file(self, local_path: Path, key: str) -> str:
        self.bucket.blob(key).upload_from_filename(str(local_path))
        return f"gs://{self.bucket_name}/{key}"

    def write_text(self, key: str, content: str) -> str:
        self.bucket.blob(key).upload_from_string(content, content_type="application/json")
        return f"gs://{self.bucket_name}/{key}"

    def read_text(self, key: str) -> str:
        return self.bucket.blob(key).download_as_text(encoding="utf-8")

    def local_path(self, key: str, tmp_dir: Path) -> Path:
        dest = Path(tmp_dir) / Path(key).name
        self.bucket.blob(key).download_to_filename(str(dest))
        return dest


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "gcs":
        if not settings.gcs_bucket:
            raise ValueError("STORAGE_BACKEND=gcs exige GCS_BUCKET definido no .env")
        return GCSStorage(settings.gcs_bucket)
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_lake_dir)
    raise ValueError(f"STORAGE_BACKEND inválido: {settings.storage_backend!r}")
