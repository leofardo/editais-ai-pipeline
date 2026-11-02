"""Extração de texto dos PDFs (sem LLM, custo zero) -> linhas para o BigQuery.

Uma linha por página. Guardar por página permite citar a fonte na resposta
do RAG ("ver página 12 do edital") e detectar PDFs escaneados.

Usamos PyMuPDF: em editais reais (ex.: TCE-SP) o pypdf colava as palavras
("OTRIBUNALDECON TASDOEST ADO"), e o PyMuPDF preserva os espaços.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pymupdf

EXTRACTOR = f"pymupdf-{pymupdf.VersionBind}"

# Abaixo disso, a página provavelmente é imagem (PDF escaneado) e precisará de OCR.
MIN_CHARS_TEXT_PAGE = 50


def extract_pages(pdf_path: str | Path, sha256: str, original_filename: str) -> list[dict]:
    loaded_at = datetime.now(timezone.utc).isoformat()
    rows = []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = (page.get_text() or "").replace("\x00", "").strip()
            rows.append(
                {
                    "sha256": sha256,
                    "original_filename": original_filename,
                    "page_number": i,
                    "text": text,
                    "char_count": len(text),
                    "needs_ocr": len(text) < MIN_CHARS_TEXT_PAGE,
                    "extractor": EXTRACTOR,
                    "loaded_at": loaded_at,
                }
            )
    return rows
