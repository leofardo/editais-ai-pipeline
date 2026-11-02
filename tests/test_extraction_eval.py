import json

import pytest

from editais import warehouse as wh
from editais.extraction_eval import run_evaluation


@pytest.fixture
def gabaritos(tmp_path):
    gab = {"original_filename": "a.pdf", "edital": {"uf": "SP"}, "cargos": [{"nome": "Analista", "vagas_total": 2}]}
    (tmp_path / "a.json").write_text(json.dumps(gab), encoding="utf-8")
    return tmp_path


@pytest.fixture
def silver(monkeypatch):
    """Silver falsa: devolve um edital correto e guarda o que seria gravado."""
    monkeypatch.setenv("GCP_PROJECT_ID", "projeto")
    saved = []

    def fake_query(sql, params=None):
        if "cargos" in sql:
            return [{"nome": "Analista", "vagas_total": 2}]
        return [{"sha256": "abc", "uf": "SP"}]

    monkeypatch.setattr(wh, "query", fake_query)
    monkeypatch.setattr(wh, "load_rows", lambda table, rows: saved.extend(rows) or len(rows))
    return saved


def test_grava_as_linhas_com_a_versao_avaliada(gabaritos, silver):
    res = run_evaluation("modelo-x", "v9", gabaritos)
    assert (res["arquivos"], res["acertos"], res["avaliacoes"]) == (1, 2, 2)
    assert res["linhas_salvas"] == len(silver) == 2
    assert {(r["model"], r["prompt_version"]) for r in silver} == {("modelo-x", "v9")}


def test_no_save_nao_grava(gabaritos, silver):
    res = run_evaluation("modelo-x", "v9", gabaritos, save=False)
    assert res["linhas_salvas"] == 0 and silver == []


def test_versao_sem_extracao_nao_grava_nada(gabaritos, silver, monkeypatch):
    monkeypatch.setattr(wh, "query", lambda sql, params=None: [])
    res = run_evaluation("modelo-x", "v9", gabaritos)
    assert (res["arquivos"], res["avaliacoes"], res["linhas_salvas"]) == (0, 0, 0)
    assert silver == []


def test_pasta_sem_gabarito_falha(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_evaluation("modelo-x", "v9", tmp_path)
