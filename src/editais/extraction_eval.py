"""Roda a avaliação da extração: silver x gabaritos -> editais_silver.extraction_eval.

Não chama o LLM: só lê a silver e compara com os gabaritos conferidos à mão.
A comparação fica em `evaluation.py`; aqui ficam a leitura e a gravação no BigQuery.
Usado pela DAG `silver_editais` e por `scripts/evaluate_extraction.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from editais import warehouse as wh
from editais.evaluation import evaluate
from editais.llm_extraction import PROMPT_VERSION, default_model

EVAL_TABLE = wh.TableDef(
    "silver",
    "extraction_eval",
    [
        ("original_filename", "STRING", "REQUIRED"),
        ("model", "STRING", "REQUIRED"),
        ("prompt_version", "STRING", "REQUIRED"),
        ("escopo", "STRING", "REQUIRED"),
        ("item", "STRING", "NULLABLE"),
        ("campo", "STRING", "REQUIRED"),
        ("status", "STRING", "REQUIRED"),
        ("predito", "STRING", "NULLABLE"),
        ("esperado", "STRING", "NULLABLE"),
        ("evaluated_at", "TIMESTAMP", "REQUIRED"),
    ],
    "evaluated_at",
    ("prompt_version",),
)


def run_evaluation(
    model: str | None = None,
    prompt: str | None = None,
    gabarito_dir: str | Path | None = None,
    save: bool = True,
) -> dict:
    """Avalia uma versão (por padrão, a atual) e retorna o resumo."""
    model = model or default_model()
    prompt = prompt or PROMPT_VERSION
    gabarito_dir = Path(gabarito_dir or os.getenv("GABARITO_DIR", "evaluation/gabarito"))
    paths = sorted(gabarito_dir.glob("*.json"))
    if not paths:  # sem isto, a pasta não montada pareceria "nenhuma extração para avaliar"
        raise FileNotFoundError(f"Nenhum gabarito em {gabarito_dir}")

    now = datetime.now(timezone.utc).isoformat()
    params = {"m": model, "v": prompt}
    save_rows, resumo = [], []

    for path in paths:
        gab = json.loads(path.read_text(encoding="utf-8"))
        fname = gab["original_filename"]
        ed = wh.query(
            f"SELECT * FROM `{wh.table_id(wh.SILVER_EDITAIS)}` WHERE original_filename = @f "
            f"AND model = @m AND prompt_version = @v ORDER BY extracted_at DESC LIMIT 1",
            {**params, "f": fname},
        )
        if not ed:
            print(f"\n⚠️  {fname}: sem extração para {model}/{prompt}")
            continue
        ed = ed[0]
        ed = {k: (v.isoformat() if hasattr(v, "isoformat") else (float(v) if type(v).__name__ == "Decimal" else v))
              for k, v in ed.items()}
        cargos = wh.query(
            f"SELECT * FROM `{wh.table_id(wh.SILVER_CARGOS)}` WHERE sha256 = @s AND model = @m "
            f"AND prompt_version = @v AND extracted_at = (SELECT MAX(extracted_at) FROM `{wh.table_id(wh.SILVER_CARGOS)}` "
            f"WHERE sha256 = @s AND model = @m AND prompt_version = @v)",
            {**params, "s": ed["sha256"]},
        )
        cargos = [{k: (float(v) if type(v).__name__ == "Decimal" else v) for k, v in c.items()} for c in cargos]

        res = evaluate(ed, cargos, gab)
        resumo.append((fname, res))
        print(f"\n=== {fname}  ({model} / prompt {prompt})")
        print(f"cargos: {res['cargos_extraidos']} extraídos / {res['cargos_esperados']} esperados | "
              f"recall={res['cargos_recall']} precisão={res['cargos_precisao']} | "
              f"acurácia dos campos={res['acuracia_campos']} | alucinações={res['alucinacoes']}")
        for r in res["detalhes"]:
            if r["status"] != "ok":
                print(f"   ✗ [{r['status']}] {r['escopo']}:{r['item'] or '-'}:{r['campo']} "
                      f"predito={r['predito']!r} esperado={r['esperado']!r}")
        if res["cargos_extras"]:
            print(f"   + cargos extraídos que não estão no gabarito: {res['cargos_extras']}")
        save_rows += [{"original_filename": fname, "model": model, "prompt_version": prompt,
                       **{k: (None if r[k] is None else str(r[k])) if k in ("predito", "esperado") else r[k]
                          for k in ("escopo", "item", "campo", "status", "predito", "esperado")},
                       "evaluated_at": now} for r in res["detalhes"]]

    all_rows = [r for _, res in resumo for r in res["detalhes"] if r["campo"] != "encontrado"]
    if resumo:
        by_field = {}
        for r in all_rows:
            by_field.setdefault(r["campo"], []).append(r["status"] == "ok")
        print("\n=== ACURÁCIA POR CAMPO (todos os gabaritos)")
        for campo, oks in sorted(by_field.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            print(f"   {campo:<26} {sum(oks):>3}/{len(oks):<3} {100 * sum(oks) / len(oks):5.0f}%")
    saved = 0
    if save_rows and save:
        saved = wh.load_rows(EVAL_TABLE, save_rows)
        print(f"\n{saved} linhas salvas em editais_silver.extraction_eval")

    acertos = sum(r["status"] == "ok" for r in all_rows)
    return {"model": model, "prompt_version": prompt, "arquivos": len(resumo), "linhas_salvas": saved,
            "acertos": acertos, "avaliacoes": len(all_rows)}
