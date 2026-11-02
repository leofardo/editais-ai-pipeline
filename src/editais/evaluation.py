"""Avaliação da extração: silver (predito) x gabarito manual (verdade).

Métricas:
- Campos do edital: acerto por campo (string normalizada, data exata, número com tolerância).
- Cargos: recall (cargos do gabarito encontrados) e precisão (cargos extraídos que existem).
- Campos dos cargos casados: escolaridade, vagas_total, salario_inicial, carga_horaria_semanal.
- Alucinação: o modelo preencheu um valor que o gabarito diz não existir no documento (null).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

EDITAL_FIELDS = [
    "orgao", "numero_edital", "banca_organizadora", "esfera", "uf", "data_publicacao",
    "inscricao_inicio", "inscricao_fim", "data_prova", "taxa_inscricao_min", "taxa_inscricao_max",
]
CARGO_FIELDS = ["escolaridade", "vagas_total", "salario_inicial", "carga_horaria_semanal"]
NAME_MATCH_THRESHOLD = 0.8


def normalize(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _num_equal(a, b, tol=0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _edital_number_equal(pred, true) -> bool:
    nums = lambda s: [int(n) for n in re.findall(r"\d+", str(s or ""))]  # "001/2025" == "1/2025"
    return bool(nums(true)) and nums(pred) == nums(true)


def compare_value(field: str, pred, true) -> str:
    """Retorna: 'ok' | 'erro' | 'alucinacao' (preencheu o que não existe) | 'omissao' (deixou null)."""
    if true is None:
        return "ok" if pred is None else "alucinacao"
    if pred is None:
        return "omissao"
    if isinstance(true, list):  # mais de uma resposta aceita (ex.: escolaridade médio/técnico)
        return "ok" if normalize(pred) in {normalize(t) for t in true} else "erro"
    if isinstance(true, (int, float)):
        return "ok" if _num_equal(pred, true) else "erro"
    if field == "numero_edital":
        return "ok" if _edital_number_equal(pred, true) else "erro"
    p, t = normalize(pred), normalize(true)
    # "Fundação VUNESP" x "FUNDACAO VUNESP": igual após normalizar; aceita também contenção
    return "ok" if p == t or (len(t) > 3 and (t in p or p in t)) else "erro"


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def match_cargos(pred: list[dict], true: list[dict]) -> list[tuple[dict, dict | None]]:
    """Casamento guloso 1-para-1 pelo nome mais parecido."""
    pairs = sorted(
        ((name_similarity(p["nome"], t["nome"]), i, j) for j, t in enumerate(true) for i, p in enumerate(pred)),
        reverse=True,
    )
    used_p, used_t, matched = set(), set(), {}
    for score, i, j in pairs:
        if score < NAME_MATCH_THRESHOLD or i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        matched[j] = pred[i]
    return [(t, matched.get(j)) for j, t in enumerate(true)]


def evaluate(pred_edital: dict, pred_cargos: list[dict], gabarito: dict) -> dict:
    rows = []  # uma linha por (escopo, campo) com o status
    for f in EDITAL_FIELDS:
        if f in gabarito["edital"]:
            rows.append({"escopo": "edital", "item": "", "campo": f,
                         "status": compare_value(f, pred_edital.get(f), gabarito["edital"][f]),
                         "predito": pred_edital.get(f), "esperado": gabarito["edital"][f]})

    pairs = match_cargos(pred_cargos, gabarito["cargos"])
    for true_c, pred_c in pairs:
        if pred_c is None:
            rows.append({"escopo": "cargo", "item": true_c["nome"], "campo": "encontrado",
                         "status": "omissao", "predito": None, "esperado": true_c["nome"]})
            continue
        for f in CARGO_FIELDS:
            if f in true_c:
                rows.append({"escopo": "cargo", "item": true_c["nome"], "campo": f,
                             "status": compare_value(f, pred_c.get(f), true_c[f]),
                             "predito": pred_c.get(f), "esperado": true_c[f]})

    found = sum(1 for _, p in pairs if p is not None)
    matched_ids = {id(p) for _, p in pairs if p is not None}
    extras = [p["nome"] for p in pred_cargos if id(p) not in matched_ids]
    scored = [r for r in rows if r["campo"] != "encontrado"]
    return {
        "cargos_esperados": len(gabarito["cargos"]),
        "cargos_extraidos": len(pred_cargos),
        "cargos_recall": round(found / len(gabarito["cargos"]), 3) if gabarito["cargos"] else None,
        "cargos_precisao": round(found / len(pred_cargos), 3) if pred_cargos else None,
        "cargos_extras": extras,
        "acuracia_campos": round(sum(r["status"] == "ok" for r in scored) / len(scored), 3) if scored else None,
        "alucinacoes": sum(r["status"] == "alucinacao" for r in rows),
        "detalhes": rows,
    }
