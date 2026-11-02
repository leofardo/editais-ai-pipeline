"""Acesso ao BigQuery (bronze e silver).

Princípios:
- Cargas via *load job* (gratuito, funciona no Sandbox), nunca streaming insert.
- O Sandbox não aceita DELETE/MERGE: a idempotência é garantida consultando
  o que já existe antes de carregar (consultas baratas, só colunas-chave).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Definição das tabelas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableDef:
    layer: str  # "bronze" | "silver" | "gold"
    name: str
    schema: list[tuple[str, str, str]]  # (coluna, tipo, modo)
    partition_field: str
    cluster_fields: tuple[str, ...] = ()


BRONZE_MANIFEST = TableDef(
    "bronze",
    "ingestion_manifest",
    [
        ("original_filename", "STRING", "REQUIRED"),
        ("sha256", "STRING", "REQUIRED"),
        ("size_bytes", "INT64", "REQUIRED"),
        ("num_pages", "INT64", "NULLABLE"),
        ("status", "STRING", "REQUIRED"),
        ("lake_uri", "STRING", "NULLABLE"),
        ("error", "STRING", "NULLABLE"),
        ("processed_at", "TIMESTAMP", "REQUIRED"),
        ("run_id", "STRING", "NULLABLE"),
    ],
    "processed_at",
    ("status",),
)

BRONZE_PAGES = TableDef(
    "bronze",
    "edital_paginas",
    [
        ("sha256", "STRING", "REQUIRED"),
        ("original_filename", "STRING", "NULLABLE"),
        ("page_number", "INT64", "REQUIRED"),
        ("text", "STRING", "NULLABLE"),
        ("char_count", "INT64", "REQUIRED"),
        ("needs_ocr", "BOOL", "REQUIRED"),
        ("extractor", "STRING", "NULLABLE"),
        ("loaded_at", "TIMESTAMP", "REQUIRED"),
    ],
    "loaded_at",
    ("sha256",),
)

SILVER_PAGES = TableDef(
    "silver",
    "edital_paginas",
    [
        ("sha256", "STRING", "REQUIRED"),
        ("original_filename", "STRING", "NULLABLE"),
        ("page_number", "INT64", "REQUIRED"),
        ("text_clean", "STRING", "NULLABLE"),
        ("char_count", "INT64", "REQUIRED"),
        ("cleaned_at", "TIMESTAMP", "REQUIRED"),
    ],
    "cleaned_at",
    ("sha256",),
)

SILVER_EDITAIS = TableDef(
    "silver",
    "editais",
    [
        ("sha256", "STRING", "REQUIRED"),
        ("original_filename", "STRING", "NULLABLE"),
        ("orgao", "STRING", "NULLABLE"),
        ("numero_edital", "STRING", "NULLABLE"),
        ("banca_organizadora", "STRING", "NULLABLE"),
        ("esfera", "STRING", "NULLABLE"),
        ("uf", "STRING", "NULLABLE"),
        ("municipio", "STRING", "NULLABLE"),
        ("data_publicacao", "DATE", "NULLABLE"),
        ("inscricao_inicio", "DATE", "NULLABLE"),
        ("inscricao_fim", "DATE", "NULLABLE"),
        ("data_prova", "DATE", "NULLABLE"),
        ("taxa_inscricao_min", "NUMERIC", "NULLABLE"),
        ("taxa_inscricao_max", "NUMERIC", "NULLABLE"),
        ("documento_completo", "BOOL", "NULLABLE"),
        ("qtd_cargos", "INT64", "NULLABLE"),
        ("observacoes", "STRING", "NULLABLE"),
        ("model", "STRING", "REQUIRED"),
        ("prompt_version", "STRING", "REQUIRED"),
        ("pages_used", "INT64", "REPEATED"),
        ("input_tokens", "INT64", "NULLABLE"),
        ("output_tokens", "INT64", "NULLABLE"),
        ("extracted_at", "TIMESTAMP", "REQUIRED"),
    ],
    "extracted_at",
    ("sha256",),
)

SILVER_CARGOS = TableDef(
    "silver",
    "cargos",
    [
        ("sha256", "STRING", "REQUIRED"),
        ("cargo_idx", "INT64", "REQUIRED"),
        ("nome", "STRING", "REQUIRED"),
        ("area", "STRING", "NULLABLE"),
        ("escolaridade", "STRING", "NULLABLE"),
        ("vagas_ampla_concorrencia", "INT64", "NULLABLE"),
        ("vagas_total", "INT64", "NULLABLE"),
        ("cadastro_reserva", "BOOL", "NULLABLE"),
        ("salario_inicial", "NUMERIC", "NULLABLE"),
        ("carga_horaria_semanal", "INT64", "NULLABLE"),
        ("localidade", "STRING", "NULLABLE"),
        ("requisitos", "STRING", "NULLABLE"),
        ("pagina_fonte", "INT64", "NULLABLE"),
        ("model", "STRING", "REQUIRED"),
        ("prompt_version", "STRING", "REQUIRED"),
        ("extracted_at", "TIMESTAMP", "REQUIRED"),
        # adicionadas no prompt v4 (evolução de schema: colunas novas NULLABLE no fim)
        ("vagas_referem_se_ao_grupo", "BOOL", "NULLABLE"),
        ("vagas_total_grupo", "INT64", "NULLABLE"),
        # ancoragem (o número aparece no texto enviado ao modelo?)
        ("vagas_no_texto", "BOOL", "NULLABLE"),
        ("salario_no_texto", "BOOL", "NULLABLE"),
    ],
    "extracted_at",
    ("sha256",),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def bq_enabled() -> bool:
    return bool(os.getenv("GCP_PROJECT_ID"))


def _client():
    from google.cloud import bigquery

    return bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location=os.getenv("BQ_LOCATION", "US"))


def table_id(t: TableDef) -> str:
    dataset = os.getenv(f"BQ_DATASET_{t.layer.upper()}", f"editais_{t.layer}")
    return f"{os.environ['GCP_PROJECT_ID']}.{dataset}.{t.name}"


def ensure_dataset(layer: str) -> None:
    from google.cloud import bigquery

    dataset = os.getenv(f"BQ_DATASET_{layer.upper()}", f"editais_{layer}")
    ds = bigquery.Dataset(f"{os.environ['GCP_PROJECT_ID']}.{dataset}")
    ds.location = os.getenv("BQ_LOCATION", "US")
    _client().create_dataset(ds, exists_ok=True)


def table_exists(t: TableDef) -> bool:
    from google.api_core.exceptions import NotFound

    try:
        _client().get_table(table_id(t))
        return True
    except NotFound:
        return False


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Executa SQL. Use {table_name} com format antes, e @param para valores."""
    from google.cloud import bigquery

    job_config = None
    if params:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(k, "INT64" if isinstance(v, int) else "STRING", v)
                for k, v in params.items()
            ]
        )
    return [dict(r) for r in _client().query(sql, job_config=job_config).result()]


def existing_keys(t: TableDef, column: str, where: str = "", params: dict | None = None) -> set:
    if not table_exists(t):
        return set()
    sql = f"SELECT DISTINCT {column} AS k FROM `{table_id(t)}` {('WHERE ' + where) if where else ''}"
    return {r["k"] for r in query(sql, params)}


def load_rows(t: TableDef, rows: list[dict]) -> int:
    from google.cloud import bigquery

    if not rows:
        return 0
    ensure_dataset(t.layer)
    job_config = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(n, ty, mode=m) for n, ty, m in t.schema],
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        time_partitioning=bigquery.TimePartitioning(field=t.partition_field),
        clustering_fields=list(t.cluster_fields) or None,
        # Evolução de schema: permite adicionar colunas NULLABLE em tabelas existentes.
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )
    _client().load_table_from_json(rows, table_id(t), job_config=job_config).result()
    return len(rows)


# ---------------------------------------------------------------------------
# Atalhos usados pela DAG de ingestão (bronze)
# ---------------------------------------------------------------------------


def load_manifest(records: list[dict], run_id: str) -> int:
    return load_rows(BRONZE_MANIFEST, [{**r, "run_id": run_id} for r in records])


def loaded_page_hashes() -> set[str]:
    return existing_keys(BRONZE_PAGES, "sha256")


def load_pages(rows: list[dict]) -> int:
    return load_rows(BRONZE_PAGES, rows)
