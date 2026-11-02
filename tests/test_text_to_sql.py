"""Segurança do Text-to-SQL: o SQL gerado pelo LLM só roda se passar na validação."""
import pytest

pytest.importorskip("langchain_openai")

from editais.rag import text_to_sql as t2s  # noqa: E402

GOLD = "`proj.editais_gold.fct_cargos`"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BQ_DATASET_GOLD", "editais_gold")


def test_select_valido_ganha_limit():
    sql = t2s.validate_sql(f"SELECT cargo FROM {GOLD} WHERE salario_inicial > 5000;")
    assert sql.endswith("LIMIT 50")


@pytest.mark.parametrize("sql", [
    f"DELETE FROM {GOLD} WHERE true",
    f"SELECT 1 FROM {GOLD}; DROP TABLE {GOLD}",
    f"WITH x AS (SELECT 1) INSERT INTO {GOLD} SELECT * FROM x",
    "SELECT * FROM `proj.editais_silver.cargos`",            # fora da gold
    "SELECT * FROM `outro-projeto.dataset.tabela`",          # outro projeto
    "SELECT 1",                                              # sem tabela permitida
    f"SELECT * FROM {GOLD} UNION ALL SELECT * FROM `proj.editais_bronze.edital_paginas`",
])
def test_bloqueia_sql_perigoso_ou_fora_da_gold(sql):
    with pytest.raises(ValueError):
        t2s.validate_sql(sql)
