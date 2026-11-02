"""DAG da Gold: roda o dbt (modelos + testes de qualidade) sobre a silver.

    dbt_deps_check ──► dbt_build (run + test na ordem do grafo)

`dbt build` para no primeiro teste com severidade error que falhar, então dado
ruim (ex.: vagas replicadas, regressão no gabarito) não chega à gold.
"""

from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

DBT = "/opt/airflow/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/dbt"
DBT_ARGS = f"--project-dir {DBT_DIR} --profiles-dir {DBT_DIR}"
# artefatos fora da pasta montada (o container não precisa escrever em ./dbt)
BUILD_ARGS = f"{DBT_ARGS} --target-path /tmp/dbt-target --log-path /tmp/dbt-logs"


@dag(
    dag_id="gold_dbt",
    start_date=datetime(2026, 1, 1),
    schedule=None,  # depois: disparar quando silver_editais terminar (Datasets do Airflow)
    catchup=False,
    tags=["editais", "gold", "dbt"],
    doc_md=__doc__,
)
def gold_dbt():
    debug = BashOperator(task_id="dbt_debug", bash_command=f"{DBT} debug --connection {DBT_ARGS}")  # só a conexão (sem git/pacotes)
    build = BashOperator(task_id="dbt_build", bash_command=f"{DBT} build {BUILD_ARGS}")
    debug >> build


gold_dbt()
