"""API do assistente de editais (FastAPI).

  uvicorn editais.api.main:app --reload        # http://localhost:8000/docs (Swagger)

Endpoints: POST /api/ask · GET /api/editais · GET /api/stats · GET /api/health · /docs (Swagger)
A interface de chat (Fase 7) é o app Streamlit em streamlit_app/, que consome esta API.
Proteções: API key opcional (X-API-Key), limite de requisições por IP e limite de gasto diário.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from editais.api import service

API_KEY = os.getenv("API_KEY", "")  # vazio = sem autenticação (desenvolvimento local)
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))

app = FastAPI(
    title="Editais AI",
    version="1.0.0",
    description="Perguntas em linguagem natural sobre editais de concurso público (agente LangGraph: SQL + RAG).",
)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])

_hits: dict[str, deque] = defaultdict(deque)


def guard(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "API key inválida ou ausente (header X-API-Key)")
    ip = request.client.host if request.client else "?"
    now, q = time.monotonic(), _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, f"Limite de {RATE_LIMIT_PER_MIN} perguntas por minuto")
    q.append(now)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=3, max_length=500, examples=["Quais cargos de nível superior pagam mais de 5 mil?"])
    modo: Literal["agente", "sql", "rag"] = "agente"


class Resposta(BaseModel):
    resposta: str
    fontes: list[str]
    caminho: list[str]
    sql: Optional[str]
    edital: Optional[str]
    modo: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float
    latencia_ms: int


@app.post("/api/ask", response_model=Resposta, dependencies=[Depends(guard)])
def ask(body: Pergunta) -> dict:
    try:
        return service.answer(body.pergunta, body.modo)
    except service.BudgetExceeded as exc:
        raise HTTPException(429, str(exc))


@app.get("/api/editais")
def editais() -> list[dict]:
    return service.list_editais()


@app.get("/api/stats")
def stats() -> dict:
    return service.budget.snapshot()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "auth": bool(API_KEY), "limite_por_min": RATE_LIMIT_PER_MIN}



@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": "Editais AI", "docs": "/docs", "chat": "Streamlit em http://localhost:8501"}
