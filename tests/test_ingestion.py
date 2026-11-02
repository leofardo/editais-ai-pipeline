import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from editais.ingestion import ingest_pdf, list_landing_pdfs, raw_key_for, write_manifest
from editais.storage import LocalStorage


def make_pdf(path: Path, pages: int = 2) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "lake")


def test_ingere_pdf_valido(tmp_path, storage):
    pdf = make_pdf(tmp_path / "edital.pdf", pages=3)
    rec = ingest_pdf(pdf, storage)
    assert rec.status == "ingested"
    assert rec.num_pages == 3
    assert storage.exists(raw_key_for(rec.sha256))


def test_reprocessar_e_idempotente(tmp_path, storage):
    pdf = make_pdf(tmp_path / "edital.pdf")
    primeiro = ingest_pdf(pdf, storage)
    segundo = ingest_pdf(pdf, storage)
    assert segundo.status == "skipped_duplicate"
    assert segundo.lake_uri == primeiro.lake_uri


def test_mesmo_conteudo_com_outro_nome_e_duplicata(tmp_path, storage):
    a = make_pdf(tmp_path / "a.pdf")
    b = tmp_path / "copia_renomeada.pdf"
    b.write_bytes(a.read_bytes())
    ingest_pdf(a, storage)
    assert ingest_pdf(b, storage).status == "skipped_duplicate"


def test_rejeita_arquivo_que_nao_e_pdf(tmp_path, storage):
    fake = tmp_path / "falso.pdf"
    fake.write_text("isso não é um PDF")
    rec = ingest_pdf(fake, storage)
    assert rec.status == "rejected_invalid_pdf"
    assert rec.lake_uri is None


def test_lista_apenas_pdfs(tmp_path):
    make_pdf(tmp_path / "x.pdf")
    (tmp_path / "notas.txt").write_text("ignorar")
    assert [Path(p).name for p in list_landing_pdfs(tmp_path)] == ["x.pdf"]


def test_manifesto_jsonl(tmp_path, storage):
    pdf = make_pdf(tmp_path / "edital.pdf")
    from editais.ingestion import record_to_dict

    rec = record_to_dict(ingest_pdf(pdf, storage))
    uri = write_manifest([rec], storage, "manual__2026-11-02T10:00:00")
    linhas = Path(uri).read_text().splitlines()
    assert json.loads(linhas[0])["sha256"] == rec["sha256"]
    assert ":" not in Path(uri).name  # run_id sanitizado
