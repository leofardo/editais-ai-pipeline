"""Compara a silver (extração do LLM) com os gabaritos em evaluation/gabarito/*.json.

Uso:  python scripts/evaluate_extraction.py [--model gpt-4.1-mini] [--prompt v2]
Saída: relatório no terminal + linhas em editais_silver.extraction_eval (histórico por versão).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from editais import warehouse as wh  # noqa: E402
from editais.evaluation import evaluate  # noqa: E402
from editais.llm_extraction import PROMPT_VERSION, default_model  # noqa: E402

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=default_model())
    ap.add_argument("--prompt", default=PROMPT_VERSION)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    params = {"m": args.model, "v": args.prompt}
    save_rows, resumo = [], []

    for path in sorted(glob.glob(str(Path(__file__).resolve().parents[1] / "evaluation/gabarito/*.json"))):
        gab = json.load(open(path, encoding="utf-8"))
        fname = gab["original_filename"]
        ed = wh.query(
            f"SELECT * FROM `{wh.table_id(wh.SILVER_EDITAIS)}` WHERE original_filename = @f "
            f"AND model = @m AND prompt_version = @v ORDER BY extracted_at DESC LIMIT 1",
            {**params, "f": fname},
        )
        if not ed:
            print(f"\n⚠️  {fname}: sem extração para {args.model}/{args.prompt}")
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
        print(f"\n=== {fname}  ({args.model} / prompt {args.prompt})")
        print(f"cargos: {res['cargos_extraidos']} extraídos / {res['cargos_esperados']} esperados | "
              f"recall={res['cargos_recall']} precisão={res['cargos_precisao']} | "
              f"acurácia dos campos={res['acuracia_campos']} | alucinações={res['alucinacoes']}")
        for r in res["detalhes"]:
            if r["status"] != "ok":
                print(f"   ✗ [{r['status']}] {r['escopo']}:{r['item'] or '-'}:{r['campo']} "
                      f"predito={r['predito']!r} esperado={r['esperado']!r}")
        if res["cargos_extras"]:
            print(f"   + cargos extraídos que não estão no gabarito: {res['cargos_extras']}")
        save_rows += [{"original_filename": fname, "model": args.model, "prompt_version": args.prompt,
                       **{k: (None if r[k] is None else str(r[k])) if k in ("predito", "esperado") else r[k]
                          for k in ("escopo", "item", "campo", "status", "predito", "esperado")},
                       "evaluated_at": now} for r in res["detalhes"]]

    if resumo:
        all_rows = [r for _, res in resumo for r in res["detalhes"] if r["campo"] != "encontrado"]
        by_field = {}
        for r in all_rows:
            by_field.setdefault(r["campo"], []).append(r["status"] == "ok")
        print("\n=== ACURÁCIA POR CAMPO (todos os gabaritos)")
        for campo, oks in sorted(by_field.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            print(f"   {campo:<26} {sum(oks):>3}/{len(oks):<3} {100 * sum(oks) / len(oks):5.0f}%")
    if save_rows and not args.no_save:
        print(f"\n{wh.load_rows(EVAL_TABLE, save_rows)} linhas salvas em editais_silver.extraction_eval")


if __name__ == "__main__":
    os.environ.setdefault("GCP_PROJECT_ID", "")
    main()
