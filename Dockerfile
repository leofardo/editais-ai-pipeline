FROM apache/airflow:2.10.5-python3.11

# A imagem oficial já traz o provider do Google (GCS/BigQuery).
# Instalamos só o que falta, respeitando as constraints da versão do Airflow.
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.11.txt"

# dbt em um virtualenv isolado: as dependências do dbt conflitam com as do Airflow.
# A DAG chama /opt/airflow/dbt-venv/bin/dbt diretamente.
RUN python -m venv /opt/airflow/dbt-venv \
    && /opt/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core==1.9.*" "dbt-bigquery==1.9.*"

# Camada de consulta (RAG/Text-to-SQL com LangChain) em outro virtualenv isolado.
COPY requirements-rag.txt /requirements-rag.txt
RUN python -m venv /opt/airflow/rag-venv \
    && /opt/airflow/rag-venv/bin/pip install --no-cache-dir -r /requirements-rag.txt
