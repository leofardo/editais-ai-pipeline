"""Avaliação das respostas com QAEvalChain (mesma técnica da aula), comparando 3 sistemas:

  sem_rag  : o LLM sozinho (baseline)
  rag      : sempre RAG no pgvector
  roteado  : roteador decide entre Text-to-SQL (gold) e RAG (Fase 4)
  agente   : grafo LangGraph com identificação do edital, CRAG e Self-RAG (Fase 5)

Também mede tokens e custo estimado por pergunta (callback de uso do LangChain).

Uso:  python scripts/evaluate_qa.py [--sistemas sem_rag,rag,roteado]
Saída: placar no terminal + histórico em editais_silver.qa_eval
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_classic.evaluation.qa import QAEvalChain  # noqa: E402
from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from editais import warehouse as wh  # noqa: E402
from editais.rag import settings  # noqa: E402
from editais.rag.agent import ask_agent  # noqa: E402
from editais.rag.rag_chain import build_no_rag_chain, build_rag_chain  # noqa: E402
from editais.rag.router import route  # noqa: E402
from editais.rag.text_to_sql import ask_sql  # noqa: E402

QA_TABLE = wh.TableDef("silver", "qa_eval", [
    ("sistema", "STRING", "REQUIRED"), ("tipo", "STRING", "NULLABLE"), ("query", "STRING", "REQUIRED"),
    ("esperado", "STRING", "NULLABLE"), ("resposta", "STRING", "NULLABLE"), ("rota", "STRING", "NULLABLE"),
    ("nota", "STRING", "REQUIRED"), ("correto", "BOOL", "REQUIRED"), ("model", "STRING", "REQUIRED"),
    ("evaluated_at", "TIMESTAMP", "REQUIRED"),
    ("tokens_in", "INT64", "NULLABLE"), ("tokens_out", "INT64", "NULLABLE"), ("custo_usd", "FLOAT64", "NULLABLE"),
    ("chamadas_llm", "INT64", "NULLABLE")], "evaluated_at", ("sistema",))

TIPOS = ("sql", "rag", "agregacao", "fora_da_base")


def answer(sistema: str, q: str) -> tuple[str, str]:
    if sistema == "agente":
        st = ask_agent(q)
        return st["answer"], " > ".join(x.split(" →")[0] for x in st["steps"])
    if sistema == "sem_rag":
        return build_no_rag_chain().invoke({"question": q}), "llm"
    if sistema == "rag":
        return build_rag_chain().invoke(q)["answer"], "rag"
    r = route(q).destino
    if r == "sql":
        try:
            return ask_sql(q)["answer"], "sql"
        except Exception as exc:  # SQL inválido/bloqueado: cai para o RAG
            return build_rag_chain().invoke(q)["answer"], f"sql_falhou->rag ({type(exc).__name__})"
    return build_rag_chain().invoke(q)["answer"], "rag"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sistemas", default="sem_rag,rag,roteado")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    examples = json.load(open(ROOT / "evaluation/qa_dataset.json", encoding="utf-8"))
    grader = QAEvalChain.from_llm(ChatOpenAI(model=settings.CHAT_MODEL, temperature=0))
    now = datetime.now(timezone.utc).isoformat()
    rows, placar = [], {}

    for sistema in args.sistemas.split(","):
        preds = []
        for ex in examples:
            with get_usage_metadata_callback() as cb:  # conta tokens de TODAS as chamadas ao LLM da pergunta
                resp, rota = answer(sistema, ex["query"])
            t_in = sum(u.get("input_tokens", 0) for u in cb.usage_metadata.values())
            t_out = sum(u.get("output_tokens", 0) for u in cb.usage_metadata.values())
            preds.append({**ex, "result": resp, "rota": rota, "t_in": t_in, "t_out": t_out})
        notas = grader.evaluate(examples, preds, question_key="query", answer_key="answer", prediction_key="result")
        for ex, p, n in zip(examples, preds, notas):
            nota = (n.get("results") or n.get("text") or "").strip()
            ok = "INCORRECT" not in nota.upper() and "CORRECT" in nota.upper()
            rows.append({"sistema": sistema, "tipo": ex["tipo"], "query": ex["query"], "esperado": ex["answer"],
                         "resposta": p["result"], "rota": p["rota"][:300], "nota": nota[:50], "correto": ok,
                         "model": settings.CHAT_MODEL, "evaluated_at": now,
                         "tokens_in": p["t_in"], "tokens_out": p["t_out"],
                         "custo_usd": round(settings.cost_usd(p["t_in"], p["t_out"]), 6), "chamadas_llm": None})
        sis = [r for r in rows if r["sistema"] == sistema]
        placar[sistema] = {t: (sum(r["correto"] for r in sis if r["tipo"] == t), sum(r["tipo"] == t for r in sis))
                           for t in TIPOS}
        placar[sistema]["_custo"] = sum(r["custo_usd"] for r in sis) / len(sis)
        placar[sistema]["_tin"] = sum(r["tokens_in"] for r in sis) / len(sis)
        placar[sistema]["_tout"] = sum(r["tokens_out"] for r in sis) / len(sis)
        print(f"\n=== {sistema}")
        for r in sis:
            print(f"  {'✅' if r['correto'] else '❌'} [{r['tipo']}] {r['query'][:60]}  "
                  f"({r['tokens_in']}+{r['tokens_out']} tok, US$ {r['custo_usd']:.4f}) | {r['rota'][:90]}")
            if not r["correto"]:
                print(f"       esperado: {r['esperado'][:90]}\n       resposta: {r['resposta'][:160]!r}")

    print("\n=== PLACAR (acertos / perguntas) e custo médio por pergunta")
    print(f"  {'sistema':<9}" + "".join(f"{t:>14}" for t in TIPOS) + f"{'total':>9}{'tokens/perg':>14}{'US$/perg':>11}")
    for s, p in placar.items():
        tot = sum(p[t][0] for t in TIPOS), sum(p[t][1] for t in TIPOS)
        print(f"  {s:<9}" + "".join(f"{p[t][0]:>10}/{p[t][1]:<3}" for t in TIPOS)
              + f"{tot[0]:>5}/{tot[1]:<3}{p['_tin'] + p['_tout']:>12,.0f}{p['_custo']:>11.4f}")
    print(f"  (preços de referência: US$ {settings.PRICE_IN}/1M entrada, US$ {settings.PRICE_OUT}/1M saída; "
          "embeddings da pergunta e juiz do QAEvalChain não incluídos)")
    if not args.no_save:
        print(f"\n{wh.load_rows(QA_TABLE, rows)} linhas salvas em editais_silver.qa_eval")


if __name__ == "__main__":
    main()
