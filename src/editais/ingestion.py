"""Regras de negócio da ingestão, sem dependência do Airflow (fácil de testar)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from editais.storage import Storage

RAW_PREFIX = "raw/editais"
MANIFEST_PREFIX = "manifests/ingestion"


@dataclass
class IngestionRecord:
    original_filename: str
    sha256: str
    size_bytes: int
    num_pages: int | None
    status: str  # "ingested" | "skipped_duplicate" | "rejected_invalid_pdf"
    lake_uri: str | None
    error: str | None
    processed_at: str


def list_landing_pdfs(landing_dir: Path) -> list[str]:
    return sorted(str(p) for p in Path(landing_dir).glob("*.pdf") if p.is_file())


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def raw_key_for(sha256: str) -> str:
    # Chave pelo hash do conteúdo => mesmo PDF nunca é gravado duas vezes,
    # mesmo que chegue com outro nome. É isso que torna a ingestão idempotente.
    return f"{RAW_PREFIX}/{sha256}.pdf"


def ingest_pdf(path: str | Path, storage: Storage) -> IngestionRecord:
    path = Path(path)
    now = datetime.now(timezone.utc).isoformat()
    sha = sha256_of(path)
    size = path.stat().st_size

    try:
        num_pages = len(PdfReader(path).pages)
        if num_pages == 0:
            raise ValueError("PDF sem páginas")
    except Exception as exc:  # PDF corrompido / não é PDF
        return IngestionRecord(path.name, sha, size, None, "rejected_invalid_pdf", None, str(exc), now)

    key = raw_key_for(sha)
    if storage.exists(key):
        return IngestionRecord(path.name, sha, size, num_pages, "skipped_duplicate", storage.uri(key), None, now)

    uri = storage.upload_file(path, key)
    return IngestionRecord(path.name, sha, size, num_pages, "ingested", uri, None, now)


def write_manifest(records: list[dict], storage: Storage, run_id: str) -> str:
    safe_run_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    return storage.write_text(f"{MANIFEST_PREFIX}/{safe_run_id}.jsonl", content)


def record_to_dict(record: IngestionRecord) -> dict:
    return asdict(record)
