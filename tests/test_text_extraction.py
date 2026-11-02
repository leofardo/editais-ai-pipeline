import pytest
from pypdf import PdfWriter

from editais.text_extraction import extract_pages

canvas = pytest.importorskip("reportlab.pdfgen.canvas")


def make_text_pdf(path, pages):
    c = canvas.Canvas(str(path))
    for text in pages:
        if text:
            c.drawString(72, 750, text)
        c.showPage()
    c.save()
    return path


def test_uma_linha_por_pagina_com_texto(tmp_path):
    texto = "EDITAL N 01/2026 - Cargo: Analista de Sistemas - Vagas: 12 - Salario R$ 8.500,00"
    pdf = make_text_pdf(tmp_path / "e.pdf", [texto, texto])
    rows = extract_pages(pdf, "abc", "e.pdf")
    assert [r["page_number"] for r in rows] == [1, 2]
    assert "Analista de Sistemas" in rows[0]["text"]
    assert rows[0]["needs_ocr"] is False
    assert rows[0]["sha256"] == "abc"


def test_pagina_sem_texto_marca_ocr(tmp_path):
    w = PdfWriter()
    w.add_blank_page(595, 842)
    pdf = tmp_path / "scan.pdf"
    w.write(pdf)
    (row,) = extract_pages(pdf, "x", "scan.pdf")
    assert row["needs_ocr"] is True and row["char_count"] == 0
