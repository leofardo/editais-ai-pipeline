"""Seleciona as páginas mais relevantes de um edital para mandar ao LLM.

Editais têm 100+ páginas, mas cargos, vagas, salários e datas costumam estar
em poucas. Mandar só essas páginas corta o custo sem perder informação.
"""

from __future__ import annotations

import re

# Pesos: termos que indicam quadro de vagas/remuneração valem mais.
_KEYWORDS = {
    r"\bvagas?\b": 3,
    r"remunera[çc][ãa]o|vencimento|sal[áa]rio|subs[íi]dio": 3,
    r"\bcargos?\b|\bfun[çc][ãa]o\b": 2,
    r"escolaridade|requisitos?|forma[çc][ãa]o": 2,
    r"cronograma|inscri[çc][õo]es|per[íi]odo de inscri": 2,
    r"taxa de inscri|valor da inscri": 2,
    r"carga hor[áa]ria|horas semanais": 1,
    r"cadastro reserva|\bCR\b": 1,
    r"data da prova|aplica[çc][ãa]o das provas": 1,
}
_COMPILED = [(re.compile(p, re.I), w) for p, w in _KEYWORDS.items()]
_MONEY = re.compile(r"R\$\s?\d")

CHARS_PER_TOKEN = 3.5  # aproximação conservadora para português


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def page_score(text: str) -> int:
    score = sum(w * min(len(p.findall(text)), 5) for p, w in _COMPILED)
    score += 2 * min(len(_MONEY.findall(text)), 10)  # valores em reais = remuneração/taxa
    return score


def select_pages(pages: list[dict], max_tokens: int, always_first: int = 2) -> list[dict]:
    """pages: [{"page_number": int, "text_clean": str}] -> subconjunto ordenado por página."""
    ordered = sorted(pages, key=lambda p: p["page_number"])
    chosen, used = [], 0

    for p in ordered[:always_first]:  # capa/abertura: órgão, número do edital, datas
        cost = estimate_tokens(p["text_clean"])
        if used + cost <= max_tokens:
            chosen.append(p)
            used += cost

    rest = sorted(ordered[always_first:], key=lambda p: page_score(p["text_clean"]), reverse=True)
    for p in rest:
        if page_score(p["text_clean"]) == 0:
            break
        cost = estimate_tokens(p["text_clean"])
        if used + cost > max_tokens:
            continue
        chosen.append(p)
        used += cost

    return sorted(chosen, key=lambda p: p["page_number"])
