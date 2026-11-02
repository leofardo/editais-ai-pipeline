"""Roteador simples (a versão com LangGraph vem na Fase 5): SQL ou RAG?"""

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from editais.rag import settings


class Route(BaseModel):
    destino: Literal["sql", "rag"] = Field(description=(
        "sql: perguntas sobre números, listas, comparações, rankings ou filtros de cargos, vagas, salários, "
        "datas, órgãos, UF. rag: perguntas sobre regras, procedimentos ou textos do edital (isenção, "
        "documentos, recursos, provas, critérios, cotas, requisitos detalhados)."))
    motivo: str


def route(question: str) -> Route:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Classifique para onde enviar a pergunta sobre concursos públicos."), ("human", "{q}")])
    return (prompt | ChatOpenAI(model=settings.CHAT_MODEL, temperature=0).with_structured_output(Route)).invoke({"q": question})
