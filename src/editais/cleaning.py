"""Limpeza do texto bruto (bronze -> silver). Determinística e gratuita."""

from __future__ import annotations

import re

# Linhas que são "lixo" de portais e cabeçalhos, sem valor para extração/RAG.
_NOISE_LINE_PATTERNS = [
    re.compile(r"^pcimarkpci\b.*$", re.I),  # marca d'água do PCI Concursos
    re.compile(r"^www\.pciconcursos\.com\.br$", re.I),
    re.compile(r"^p[áa]gina\s+\d+\s+(de|/)\s+\d+$", re.I),  # "Página 3 de 46"
    re.compile(r"^[_\-=.\s]{5,}$"),  # linhas de separação "_____"
]

# Número solto só é ruído na 1ª/última linha (numeração de página). No meio da
# página pode ser dado de tabela (ex.: "59" vagas): bug real encontrado no TCE-SP.
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")  # "inscri-\nção" -> "inscrição"
_SPACES = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


def _strip_blank_edges(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start]:
        start += 1
    while end > start and not lines[end - 1]:
        end -= 1
    return lines[start:end]


def clean_page_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = []
    for raw in text.split("\n"):
        line = _SPACES.sub(" ", raw).strip()
        if any(p.match(line) for p in _NOISE_LINE_PATTERNS):
            continue
        lines.append(line)
    lines = _strip_blank_edges(lines)
    if lines and _PAGE_NUMBER.match(lines[0]):  # no máximo UM no topo
        lines = _strip_blank_edges(lines[1:])
    if lines and _PAGE_NUMBER.match(lines[-1]):  # e UM no rodapé
        lines = _strip_blank_edges(lines[:-1])
    return _MANY_NEWLINES.sub("\n\n", "\n".join(lines)).strip()
