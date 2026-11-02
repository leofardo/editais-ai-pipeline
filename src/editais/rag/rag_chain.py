"""RAG: pergunta -> pgvector (top-k chunks) -> LLM responde citando órgão e página.

Mesma estrutura LCEL da aula: {context: retriever | formatar, question} | prompt | llm | parser
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnablePassthrough
from langchain_openai import ChatOpenAI

from editais.rag import settings
from editais.rag.store import get_store

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Você responde dúvidas sobre editais de concurso público usando SOMENTE os trechos fornecidos.\n"
     "- Se a resposta não estiver nos trechos, diga que não encontrou nos editais indexados.\n"
     "- Cite a fonte de cada informação no formato [órgão, p. N].\n"
     "- Seja objetivo e responda em português."),
    ("human", "Trechos dos editais:\n{context}\n\nPergunta: {question}"),
])


def format_docs(docs) -> str:
    return "\n\n".join(
        f"[{d.metadata.get('orgao')}, p. {d.metadata.get('pagina')}]\n{d.page_content}" for d in docs
    )


def build_rag_chain(k: int = 6, edital_id: str | None = None):
    search_kwargs = {"k": k}
    if edital_id:
        search_kwargs["filter"] = {"edital_id": edital_id}
    retriever = get_store().as_retriever(search_kwargs=search_kwargs)
    llm = ChatOpenAI(model=settings.CHAT_MODEL, temperature=0)

    # Devolve resposta + documentos (para mostrar as fontes e avaliar).
    return RunnableParallel(docs=retriever, question=RunnablePassthrough()).assign(
        answer=RunnableLambda(lambda x: {"context": format_docs(x["docs"]), "question": x["question"]})
        | PROMPT | llm | StrOutputParser()
    )


def build_no_rag_chain():
    """Baseline da aula: o mesmo LLM respondendo sem nenhum contexto."""
    prompt = ChatPromptTemplate.from_template(
        "Responda em português, de forma objetiva, sobre editais de concurso público: {question}")
    return prompt | ChatOpenAI(model=settings.CHAT_MODEL, temperature=0) | StrOutputParser()
