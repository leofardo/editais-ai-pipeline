"""URIs dos Datasets do Airflow que encadeiam as DAGs:

    ingest_editais ──► silver_editais ──► gold_dbt ──► index_rag

Cada DAG só dispara a seguinte quando a sua última task termina com sucesso.
Task pulada (nada novo) ou que falhou não dispara nada.
"""

BRONZE_PAGINAS = "editais://bronze/edital_paginas"
SILVER_AVALIADA = "editais://silver/extracao_avaliada"
GOLD_MODELOS = "editais://gold/modelos"
