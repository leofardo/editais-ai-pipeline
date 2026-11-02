"""Pergunte aos editais pelo terminal.

  python scripts/ask.py "Quais cargos de nível superior pagam mais de 5 mil?"
  python scripts/ask.py --modo rag "Quem tem direito à isenção da taxa na UFG?"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from editais.rag.rag_chain import build_rag_chain  # noqa: E402
from editais.rag.router import route  # noqa: E402
from editais.rag.text_to_sql import ask_sql  # noqa: E402
from editais.rag.agent import ask_agent  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pergunta")
ap.add_argument("--modo", choices=["agente", "auto", "sql", "rag"], default="agente")
a = ap.parse_args()

modo = a.modo
if modo == "agente":
    st = ask_agent(a.pergunta)
    print("Caminho do agente:\n  " + "\n  ".join(st["steps"]))
    if st.get("sql"):
        print(f"\nSQL:\n{st['sql']}")
    print(f"\nResposta: {st['answer']}\n\nFontes: {', '.join(st.get('sources') or []) or '-'}")
    raise SystemExit
if modo == "auto":
    r = route(a.pergunta)
    modo = r.destino
    print(f"[roteador] {modo}: {r.motivo}\n")

if modo == "sql":
    out = ask_sql(a.pergunta)
    print(f"SQL:\n{out['sql']}\n\nResposta: {out['answer']}")
else:
    out = build_rag_chain().invoke(a.pergunta)
    print(f"Resposta: {out['answer']}\n\nFontes: " + ", ".join(
        sorted({f"{d.metadata['orgao']} p.{d.metadata['pagina']}" for d in out["docs"]})))
