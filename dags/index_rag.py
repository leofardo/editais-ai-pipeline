"""DAG de indexação do RAG: silver.edital_paginas -> chunks por tokens -> embeddings -> pgvector.

Idempotente (IDs determinísticos por edital/página/chunk): só paga embeddings de páginas novas.
Roda no virtualenv isolado com LangChain (/opt/airflow/rag-venv), como o dbt.
"""

from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

PY = "/opt/airflow/rag-venv/bin/python"


@dag(
    dag_id="index_rag",
    start_date=datetime(2026, 1, 1),
    schedule=None,  # depois: disparar após gold_dbt (os metadados vêm da dim_editais)
    catchup=False,
    tags=["editais", "rag", "pgvector"],
    doc_md=__doc__,
)
def index_rag():
    dry = BashOperator(task_id="estimar_custo", bash_command=f"cd /opt/airflow && {PY} -m editais.rag.index --dry-run")
    run = BashOperator(task_id="indexar", bash_command=f"cd /opt/airflow && {PY} -m editais.rag.index")
    dry >> run


index_rag()
