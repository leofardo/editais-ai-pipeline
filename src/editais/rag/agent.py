"""Fase 5: agente com LangGraph (roteamento + CRAG + Self-RAG).

                      ┌──────────────────┐
  pergunta ─► identificar_edital ─► rotear ─┬─► consultar_sql ──(ok)──────────────────────────► FIM
                                            │        └─(falhou/vazio)─┐
                                            ├─► recuperar ◄───────────┘◄──── reescrever ◄─┐
                                            │      └─► avaliar_documentos ─(nenhum útil)───┘ (máx. 1x)
                                            │                 ├─(nenhum útil, já reescreveu)─► sem_resposta ─► FIM
                                            │                 └─(úteis)─► gerar ─► verificar_fundamentacao
                                            │                                ▲            ├─(apoiada)──────► FIM
                                            │                                └─(não apoiada, 1x)─┘
                                            └─► fora_do_escopo ─► FIM

- identificar_edital: usa o catálogo da gold para achar o concurso citado (sigla ou nome) e
  FILTRAR a busca vetorial por ele (resolve trechos de outros editais na resposta).
- CRAG (Corrective RAG): avalia a relevância de cada trecho; se nenhum serve, reescreve a
  pergunta e busca de novo.
- Self-RAG: confere se a resposta está apoiada nos trechos; se não, gera de novo com regra mais rígida.
"""

from __future__ import annotations

import operator
from functools import lru_cache
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from editais.rag import settings
from editais.rag.rag_chain import format_docs
from editais.rag.store import get_store
from editais.rag.text_to_sql import ask_sql, catalog

MAX_REWRITES = 1
MAX_REGENERATIONS = 1
TOP_K = 6
NOT_FOUND = "Não encontrei essa informação nos editais indexados."


class AgentState(TypedDict, total=False):
    question: str
    search_query: str
    edital_id: Optional[str]
    orgao: Optional[str]
    route: str
    docs: list[Document]
    sql: Optional[str]
    answer: str
    sources: list[str]
    rewrites: int
    regenerations: int
    grounded: Optional[bool]
    steps: Annotated[list[str], operator.add]  # trilha do que o agente fez (vai para o log/LangSmith)


@lru_cache
def _llm() -> ChatOpenAI:
    return ChatOpenAI(model=settings.CHAT_MODEL, temperature=0)


@lru_cache
def _catalog() -> str:
    return catalog()


# ---------------------------------------------------------------- nós

class EditalRef(BaseModel):
    edital_id: Optional[str] = Field(description="edital_id do catálogo, ou null se a pergunta não cita um concurso específico")
    orgao: Optional[str]


def identificar_edital(state: AgentState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Catálogo de editais (edital_id | órgão | UF | número):\n{cat}\n\n"
                   "Se a pergunta citar um concurso/órgão deste catálogo (por nome ou sigla, ex.: TCE-SP, UFG, "
                   "SEE-MG), devolva o edital_id. Se citar um concurso que NÃO está no catálogo, ou nenhum, devolva null."),
        ("human", "{q}")])
    ref = (prompt | _llm().with_structured_output(EditalRef)).invoke({"cat": _catalog(), "q": state["question"]})
    valid = ref.edital_id if ref.edital_id and ref.edital_id in _catalog() else None
    return {"edital_id": valid, "orgao": ref.orgao if valid else None, "search_query": state["question"],
            "rewrites": 0, "regenerations": 0, "steps": [f"identificar_edital → {ref.orgao if valid else 'nenhum'}"]}


class Route(BaseModel):
    destino: Literal["sql", "rag", "fora_do_escopo"] = Field(description=(
        "sql: números, contagens, rankings, médias, listas e filtros sobre cargos, vagas, salários, taxas, datas "
        "ou órgãos (inclusive comparações entre editais). "
        "rag: regras e procedimentos escritos no edital (isenção, documentos, provas, cotas, recursos, critérios). "
        "fora_do_escopo: nada a ver com concursos públicos/editais."))


def rotear(state: AgentState) -> dict:
    prompt = ChatPromptTemplate.from_messages([("system", "Classifique a pergunta."), ("human", "{q}")])
    r = (prompt | _llm().with_structured_output(Route)).invoke({"q": state["question"]})
    return {"route": r.destino, "steps": [f"rotear → {r.destino}"]}


def consultar_sql(state: AgentState) -> dict:
    q = state["question"]
    if state.get("edital_id"):
        q += f"\n(edital_id identificado: {state['edital_id']})"
    try:
        out = ask_sql(q)
    except Exception as exc:  # SQL inválido/bloqueado após autocorreção
        return {"answer": "", "steps": [f"consultar_sql → falhou ({type(exc).__name__}), indo para o RAG"]}
    vazio = not out["rows"] or all(v is None for r in out["rows"] for v in r.values())
    if vazio:
        return {"answer": "", "sql": out["sql"], "steps": ["consultar_sql → vazio, indo para o RAG"]}
    return {"answer": out["answer"], "sql": out["sql"], "sources": ["BigQuery gold (SQL)"],
            "steps": [f"consultar_sql → {len(out['rows'])} linha(s)"]}


def recuperar(state: AgentState) -> dict:
    flt = {"edital_id": state["edital_id"]} if state.get("edital_id") else None
    docs = get_store().similarity_search(state["search_query"], k=TOP_K, filter=flt)
    return {"docs": docs, "steps": [f"recuperar → {len(docs)} trechos" + (" (filtrado pelo edital)" if flt else "")]}


class Relevantes(BaseModel):
    indices: list[int] = Field(description="Números dos trechos que ajudam a responder a pergunta")


def avaliar_documentos(state: AgentState) -> dict:
    """CRAG: uma única chamada avalia todos os trechos (mais barato que 1 chamada por trecho)."""
    numbered = "\n\n".join(f"[{i}] ({d.metadata.get('orgao')}, p. {d.metadata.get('pagina')})\n{d.page_content}"
                           for i, d in enumerate(state["docs"]))
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Indique quais trechos contêm informação útil para responder a pergunta. Seja rigoroso: "
                   "trechos de outro concurso, ou que só tangenciam o assunto, não são úteis."),
        ("human", "Pergunta: {q}\n\nTrechos:\n{t}")])
    r = (prompt | _llm().with_structured_output(Relevantes)).invoke({"q": state["question"], "t": numbered})
    keep = [state["docs"][i] for i in sorted(set(r.indices)) if 0 <= i < len(state["docs"])]
    return {"docs": keep, "steps": [f"avaliar_documentos → {len(keep)}/{len(state['docs'])} úteis"]}


class Reescrita(BaseModel):
    consulta: str = Field(description="Consulta reescrita para busca semântica em editais")


def reescrever(state: AgentState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "A busca não encontrou trechos úteis. Reescreva a pergunta como uma consulta de busca para "
                   "textos de editais: use os termos formais que um edital usaria (ex.: 'isenção' → 'isenção do "
                   "pagamento da taxa de inscrição'), sem perder o sentido."),
        ("human", "Pergunta original: {q}\nConsulta usada: {s}")])
    r = (prompt | _llm().with_structured_output(Reescrita)).invoke(
        {"q": state["question"], "s": state["search_query"]})
    return {"search_query": r.consulta, "rewrites": state["rewrites"] + 1,
            "steps": [f"reescrever → '{r.consulta}'"]}


GEN_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Você responde dúvidas sobre editais de concurso usando SOMENTE os trechos fornecidos.\n"
               "Cite a fonte de cada informação no formato [órgão, p. N]. Responda em português, de forma objetiva."
               "{rigor}"),
    ("human", "Trechos:\n{context}\n\nPergunta: {q}")])


def gerar(state: AgentState) -> dict:
    rigor = ("\nATENÇÃO: a resposta anterior trouxe informação que não estava nos trechos. Use apenas frases que "
             "possam ser verificadas literalmente nos trechos; se faltar dado, diga que o edital não informa."
             if state.get("regenerations") else "")
    ans = (GEN_PROMPT | _llm()).invoke({"context": format_docs(state["docs"]), "q": state["question"],
                                        "rigor": rigor}).content
    sources = sorted({f"{d.metadata.get('orgao')} p.{d.metadata.get('pagina')}" for d in state["docs"]})
    return {"answer": ans, "sources": sources, "steps": ["gerar"]}


class Fundamentacao(BaseModel):
    apoiada: bool = Field(description="True se TODAS as afirmações da resposta estão apoiadas nos trechos")
    problema: Optional[str]


def verificar_fundamentacao(state: AgentState) -> dict:
    """Self-RAG: a resposta está apoiada nos trechos?"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Verifique se cada afirmação da RESPOSTA está apoiada nos TRECHOS. Ignore as citações de fonte."),
        ("human", "TRECHOS:\n{context}\n\nRESPOSTA:\n{a}")])
    r = (prompt | _llm().with_structured_output(Fundamentacao)).invoke(
        {"context": format_docs(state["docs"]), "a": state["answer"]})
    upd = {"grounded": r.apoiada, "steps": [f"verificar_fundamentacao → {'apoiada' if r.apoiada else 'NÃO apoiada: ' + str(r.problema)}"]}
    if not r.apoiada:
        upd["regenerations"] = state["regenerations"] + 1
    return upd


def sem_resposta(state: AgentState) -> dict:
    return {"answer": NOT_FOUND, "sources": [], "steps": ["sem_resposta"]}


def fora_do_escopo(state: AgentState) -> dict:
    return {"answer": "Só consigo responder perguntas sobre os editais de concurso indexados.", "sources": [],
            "steps": ["fora_do_escopo"]}


# ---------------------------------------------------------------- arestas condicionais

def depois_de_rotear(state: AgentState) -> str:
    return {"sql": "consultar_sql", "rag": "recuperar"}.get(state["route"], "fora_do_escopo")


def depois_do_sql(state: AgentState) -> str:
    return END if state.get("answer") else "recuperar"


def depois_de_avaliar(state: AgentState) -> str:
    if state["docs"]:
        return "gerar"
    return "reescrever" if state["rewrites"] < MAX_REWRITES else "sem_resposta"


def depois_de_verificar(state: AgentState) -> str:
    if state["grounded"] or state["regenerations"] > MAX_REGENERATIONS:
        return END
    return "gerar"


@lru_cache
def build_agent():
    g = StateGraph(AgentState)
    for name, fn in [("identificar_edital", identificar_edital), ("rotear", rotear),
                     ("consultar_sql", consultar_sql), ("recuperar", recuperar),
                     ("avaliar_documentos", avaliar_documentos), ("reescrever", reescrever), ("gerar", gerar),
                     ("verificar_fundamentacao", verificar_fundamentacao), ("sem_resposta", sem_resposta),
                     ("fora_do_escopo", fora_do_escopo)]:
        g.add_node(name, fn)
    g.add_edge(START, "identificar_edital")
    g.add_edge("identificar_edital", "rotear")
    g.add_conditional_edges("rotear", depois_de_rotear, ["consultar_sql", "recuperar", "fora_do_escopo"])
    g.add_conditional_edges("consultar_sql", depois_do_sql, [END, "recuperar"])
    g.add_edge("recuperar", "avaliar_documentos")
    g.add_conditional_edges("avaliar_documentos", depois_de_avaliar, ["gerar", "reescrever", "sem_resposta"])
    g.add_edge("reescrever", "recuperar")
    g.add_edge("gerar", "verificar_fundamentacao")
    g.add_conditional_edges("verificar_fundamentacao", depois_de_verificar, [END, "gerar"])
    g.add_edge("sem_resposta", END)
    g.add_edge("fora_do_escopo", END)
    return g.compile()


def ask_agent(question: str) -> AgentState:
    return build_agent().invoke({"question": question, "steps": []}, config={"recursion_limit": 20})
