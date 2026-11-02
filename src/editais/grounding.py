"""Ancoragem: o número extraído aparece de verdade no texto enviado ao LLM?

Defesa determinística (e gratuita) contra alucinação e contas feitas pelo modelo.
Ex.: no TCE-SP o modelo respondeu 63 vagas (59 + 4); "63" não existe no texto -> suspeito.
"""

from __future__ import annotations

import re


def _int_patterns(n: int) -> list[str]:
    plain = str(n)
    dotted = f"{n:,}".replace(",", ".")  # 10170 -> 10.170
    return list({plain, dotted})


def int_in_text(n: int | None, text: str) -> bool | None:
    if n is None:
        return None
    return any(re.search(rf"(?<![\d.,]){re.escape(p)}(?![\d]|[.,]\d)", text) for p in _int_patterns(int(n)))


def money_in_text(v: float | None, text: str) -> bool | None:
    if v is None:
        return None
    cents = f"{float(v):,.2f}"  # 17,743.05
    br = cents.replace(",", "X").replace(".", ",").replace("X", ".")  # 17.743,05
    candidates = {br, br.replace(".", "")}  # 17.743,05 e 17743,05
    if float(v).is_integer():
        candidates |= {f"{int(v):,}".replace(",", "."), str(int(v))}
    return any(c in text for c in candidates)


def ground_cargos(cargo_rows: list[dict], source_text: str) -> list[dict]:
    """Adiciona colunas *_no_texto em cada cargo (True/False, None se o valor é nulo)."""
    out = []
    for c in cargo_rows:
        vagas = c.get("vagas_total") if c.get("vagas_total") is not None else c.get("vagas_total_grupo")
        out.append({**c,
                    "vagas_no_texto": int_in_text(vagas, source_text),
                    "salario_no_texto": money_in_text(c.get("salario_inicial"), source_text)})
    return out
