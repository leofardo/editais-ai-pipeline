"""Text-to-SQL seguro sobre a camada gold (BigQuery).

Defesas (o LLM nunca executa nada direto):
1. Structured output: o modelo devolve só {sql, explicacao}.
2. Validação: um único SELECT/WITH, sem DML/DDL, só tabelas permitidas da gold.
3. Dry-run no BigQuery: estima bytes antes de executar; aborta acima do limite.
4. maximum_bytes_billed + LIMIT na execução.
"""

from __future__ import annotations

import os
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from editais.rag import settings

ALLOWED_TABLES = ("dim_editais", "fct_cargos")
MAX_BYTES = int(os.getenv("SQL_MAX_BYTES", str(100 * 1024 * 1024)))  # 100 MB
MAX_ROWS = 50
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|call|execute|declare|set|export|load)\b",
    re.I)

SCHEMA_DOC = """
Tabela {dim} (1 linha por edital):
  edital_id STRING, orgao STRING, orgao_norm STRING (órgão em minúsculas e sem acento), numero_edital STRING, banca_organizadora STRING,
  esfera STRING ('municipal'|'estadual'|'federal'), uf STRING (sigla), municipio STRING,
  data_publicacao DATE, inscricao_inicio DATE, inscricao_fim DATE, data_prova DATE,
  status_inscricao STRING ('em_breve'|'aberta'|'encerrada'|'sem_data'),
  taxa_inscricao_min FLOAT64, taxa_inscricao_max FLOAT64, qtd_cargos INT64,
  vagas_total INT64 (total do edital), salario_min FLOAT64, salario_max FLOAT64

Tabela {fct} (1 linha por cargo):
  cargo_id STRING, edital_id STRING, orgao STRING, esfera STRING, uf STRING, banca_organizadora STRING,
  cargo STRING, cargo_norm STRING (cargo em minúsculas e sem acento), orgao_norm STRING, area STRING (ex.: 'educação','saúde','administrativa','ti','segurança','engenharia','outra'),
  escolaridade STRING ('fundamental'|'medio'|'tecnico'|'superior'|'nao_informado'),
  vagas_total INT64 (vagas do cargo; NULL quando o edital só informa o total de um grupo),
  vagas_de_grupo BOOL, vagas_total_grupo INT64 (total da carreira/grupo, repetido em cada especialidade:
  NUNCA some esta coluna entre cargos), cadastro_reserva BOOL, salario_inicial FLOAT64 (R$ mensal),
  faixa_salarial STRING, carga_horaria_semanal INT64, localidade STRING, requisitos STRING,
  inscricao_inicio DATE, inscricao_fim DATE, data_prova DATE
"""


class SQLQuery(BaseModel):
    sql: str = Field(description="Uma única consulta SELECT em GoogleSQL (BigQuery)")
    explicacao: str = Field(description="Uma frase explicando o que a consulta faz")


SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Você gera SQL (GoogleSQL/BigQuery) para responder perguntas sobre concursos públicos.\n"
     "Use SOMENTE estas tabelas, sempre com o nome completo entre crases:\n{schema}\n"
     "CATÁLOGO de editais disponíveis (edital_id | órgão | UF | número):\n{catalogo}\n"
     "Regras:\n"
     "- Apenas SELECT. Limite a {max_rows} linhas.\n"
     "- Quando a pergunta citar um concurso/órgão (inclusive por sigla, ex.: TCE-SP, UFG, SEE-MG), identifique-o"
     " no CATÁLOGO e filtre por edital_id = '...'. Não filtre órgão por texto.\n"
     "- Para cargos, use cargo_norm LIKE '%palavra%' com palavras em minúsculas e SEM acento.\n"
     "- Só filtre por termos que sejam nomes de cargos; descrições do concurso (ex.: 'técnico-administrativos')"
     " não são nomes de cargo.\n"
     "- Para o total de vagas de um edital use {dim}.vagas_total."),
    ("human", "{question}{feedback}"),
])

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Responda em português, de forma objetiva, usando SOMENTE o resultado da consulta. "
               "Se o resultado vier vazio, diga que não há dados para isso nos editais."),
    ("human", "Pergunta: {question}\nSQL executado: {sql}\nResultado ({n} linhas): {rows}"),
])


def _tables():
    return settings.gold_table("dim_editais"), settings.gold_table("fct_cargos")


def validate_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Mais de um comando SQL")
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ValueError("Só consultas SELECT são permitidas")
    if FORBIDDEN.search(sql):
        raise ValueError("Comando proibido no SQL")
    refs = re.findall(r"`([^`]+)`", sql)
    allowed = {t.strip("`") for t in _tables()}
    if not refs or any(r not in allowed for r in refs):
        raise ValueError(f"Tabelas fora da lista permitida: {sorted(set(refs) - allowed)}")
    if not re.search(r"\blimit\s+\d+\s*$", sql, re.I):
        sql = f"{sql}\nLIMIT {MAX_ROWS}"
    return sql


def run_sql(sql: str) -> list[dict]:
    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location=os.getenv("BQ_LOCATION", "US"))
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    if dry.total_bytes_processed > MAX_BYTES:
        raise ValueError(f"Consulta leria {dry.total_bytes_processed:,} bytes (limite {MAX_BYTES:,})")
    job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES))
    return [{k: (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
             for k, v in dict(r).items()} for r in job.result(max_results=MAX_ROWS)]


def catalog() -> str:
    dim, _ = _tables()
    rows = run_sql(f"SELECT edital_id, orgao, uf, numero_edital FROM {dim} ORDER BY orgao")
    return "\n".join(f"{r['edital_id']} | {r['orgao']} | {r['uf']} | {r['numero_edital']}" for r in rows)


def ask_sql(question: str, max_attempts: int = 2) -> dict:
    """Gera, valida e executa o SQL. Se der erro ou vier vazio, tenta UMA vez com o feedback."""
    dim, fct = _tables()
    llm = ChatOpenAI(model=settings.CHAT_MODEL, temperature=0)
    gen = SQL_PROMPT | llm.with_structured_output(SQLQuery)
    base = {"schema": SCHEMA_DOC.format(dim=dim, fct=fct), "dim": dim, "max_rows": MAX_ROWS,
            "question": question, "catalogo": catalog()}
    feedback, attempts = "", []
    for _ in range(max_attempts):
        q = gen.invoke({**base, "feedback": feedback})
        try:
            sql = validate_sql(q.sql)
            rows = run_sql(sql)
        except Exception as exc:  # validação ou erro do BigQuery
            attempts.append({"sql": q.sql, "erro": str(exc)[:300]})
            feedback = f"\n\n[Tentativa anterior falhou]\nSQL: {q.sql}\nErro: {str(exc)[:300]}\nCorrija."
            continue
        vazio = not rows or all(v is None for r in rows for v in r.values())
        attempts.append({"sql": sql, "linhas": len(rows), "vazio": vazio})
        if not vazio:
            break
        feedback = (f"\n\n[Tentativa anterior voltou VAZIA]\nSQL: {sql}\n"
                    "Revise os filtros (use edital_id do catálogo; cargos sem acento; menos restrições).")
    else:
        if not attempts or "erro" in attempts[-1]:
            raise RuntimeError(f"Text-to-SQL falhou: {attempts}")
    answer = (ANSWER_PROMPT | llm).invoke(
        {"question": question, "sql": sql, "n": len(rows), "rows": rows}).content
    return {"sql": sql, "explicacao": q.explicacao, "rows": rows, "answer": answer, "tentativas": attempts}
