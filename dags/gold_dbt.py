"""DAG da Gold: roda o dbt (modelos + testes de qualidade) sobre a silver.

    dbt_deps_check ──► dbt_build (run + test na ordem do grafo)

Disparada quando a silver termina a avaliação; ao terminar com sucesso, dispara o índice do RAG.

`dbt build` pula o que depende de um teste que falhou. Versão de prompt sem avaliação ou com
regressão no gabarito reprova antes de dim_editais e fct_cargos. Os demais testes rodam sobre as
tabelas já construídas: falham a DAG e seguram o índice, mas essas tabelas já foram substituídas.
"""

from __future__ import annotations

from datetime import datetime

from airflow.datasets import Dataset
from airflow.decorators import dag
from airflow.operators.bash import BashOperator

from editais.pipeline_datasets import GOLD_MODELOS, SILVER_AVALIADA

DBT = "/opt/airflow/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/dbt"
DBT_ARGS = f"--project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"
# artefatos fora da pasta montada (o container não precisa escrever em ./dbt)
BUILD_ARGS = f"{DBT_ARGS} --target-path /tmp/dbt-target --log-path /tmp/dbt-logs"
# Pelo scheduler, o PYTHONPATH da task aponta para os pacotes do Airflow e quebra o dbt no venv.
# `airflow dags test` não mostra esse erro: ele roda tudo no mesmo processo.
ENV = {"PYTHONPATH": ""}


@dag(
    dag_id="gold_dbt",
    start_date=datetime(2026, 1, 1),
    schedule=[Dataset(SILVER_AVALIADA)],
    catchup=False,
    tags=["editais", "gold", "dbt"],
    doc_md=__doc__,
)
def gold_dbt():
    debug = BashOperator(task_id="dbt_debug", bash_command=f"{DBT} debug --connection {DBT_ARGS}",  # só a conexão (sem git/pacotes)
                         env=ENV, append_env=True)
    build = BashOperator(task_id="dbt_build", bash_command=f"{DBT} build {BUILD_ARGS}", env=ENV, append_env=True,
                         outlets=[Dataset(GOLD_MODELOS)])
    debug >> build


gold_dbt()
