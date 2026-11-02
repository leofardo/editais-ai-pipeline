"""Camada de serviço usada pela API e pelo servidor MCP.

Centraliza: execução do agente/cadeias, medição de tokens e custo, e a TRAVA DE GASTO DIÁRIO
(uma API pública com LLM sem limite de gasto é um risco financeiro).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date
from functools import lru_cache

from langchain_core.callbacks import get_usage_metadata_callback

from editais.rag import settings

DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "1.00"))


class BudgetExceeded(RuntimeError):
    pass


class _Budget:
    """Contador em memória (suficiente para 1 instância; em produção: Redis/BigQuery)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.day, self.spent, self.questions = date.today(), 0.0, 0

    def _roll(self) -> None:
        if date.today() != self.day:
            self.day, self.spent, self.questions = date.today(), 0.0, 0

    def check(self) -> None:
        with self._lock:
            self._roll()
            if self.spent >= DAILY_BUDGET_USD:
                raise BudgetExceeded(f"Limite diário de US$ {DAILY_BUDGET_USD:.2f} atingido")

    def add(self, usd: float) -> None:
        with self._lock:
            self._roll()
            self.spent += usd
            self.questions += 1

    def snapshot(self) -> dict:
        with self._lock:
            self._roll()
            return {"dia": self.day.isoformat(), "gasto_usd": round(self.spent, 5), "perguntas": self.questions,
                    "limite_usd": DAILY_BUDGET_USD}


budget = _Budget()


def answer(question: str, mode: str = "agente") -> dict:
    budget.check()
    t0 = time.perf_counter()
    with get_usage_metadata_callback() as cb:
        if mode == "agente":
            from editais.rag.agent import ask_agent

            st = ask_agent(question)
            out = {"resposta": st["answer"], "fontes": st.get("sources") or [], "caminho": st.get("steps", []),
                   "sql": st.get("sql"), "edital": st.get("orgao")}
        elif mode == "sql":
            from editais.rag.text_to_sql import ask_sql

            r = ask_sql(question)
            out = {"resposta": r["answer"], "fontes": ["BigQuery gold (SQL)"], "caminho": ["consultar_sql"],
                   "sql": r["sql"], "edital": None}
        elif mode == "rag":
            from editais.rag.rag_chain import build_rag_chain

            r = build_rag_chain().invoke(question)
            out = {"resposta": r["answer"], "caminho": ["recuperar", "gerar"], "sql": None, "edital": None,
                   "fontes": sorted({f"{d.metadata['orgao']} p.{d.metadata['pagina']}" for d in r["docs"]})}
        else:
            raise ValueError(f"modo inválido: {mode}")
    t_in = sum(u.get("input_tokens", 0) for u in cb.usage_metadata.values())
    t_out = sum(u.get("output_tokens", 0) for u in cb.usage_metadata.values())
    cost = settings.cost_usd(t_in, t_out)
    budget.add(cost)
    return {**out, "modo": mode, "tokens_entrada": t_in, "tokens_saida": t_out,
            "custo_usd": round(cost, 6), "latencia_ms": int((time.perf_counter() - t0) * 1000)}


@lru_cache
def _catalog_rows() -> tuple:
    from editais.rag.text_to_sql import run_sql

    rows = run_sql(
        f"SELECT edital_id, orgao, uf, esfera, banca_organizadora, numero_edital, qtd_cargos, vagas_total, "
        f"salario_min, salario_max, status_inscricao FROM {settings.gold_table('dim_editais')} ORDER BY orgao")
    return tuple(rows)


def list_editais() -> list[dict]:
    return list(_catalog_rows())
