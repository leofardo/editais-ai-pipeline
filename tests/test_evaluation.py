from editais.evaluation import compare_value, evaluate, match_cargos


def test_compare_value_status():
    assert compare_value("banca_organizadora", "FUNDAÇÃO VUNESP", "Fundação VUNESP") == "ok"
    assert compare_value("orgao", "Tribunal de Contas do Estado de São Paulo - TCESP",
                         "Tribunal de Contas do Estado de São Paulo") == "ok"
    assert compare_value("numero_edital", "1/2025", "001/2025") == "ok"
    assert compare_value("salario_inicial", 17743.05, 17743.05) == "ok"
    assert compare_value("vagas_total", 3, 59) == "erro"
    assert compare_value("vagas_total", 10, None) == "alucinacao"
    assert compare_value("data_prova", None, "2025-06-15") == "omissao"
    assert compare_value("escolaridade", "tecnico", ["medio", "tecnico"]) == "ok"


def test_match_cargos_por_similaridade():
    pred = [{"nome": "AUDITOR DE CONTROLE EXTERNO - ADMINISTRACAO"}, {"nome": "Auditor de Controle Externo"}]
    true = [{"nome": "Auditor de Controle Externo"}, {"nome": "Auditor de Controle Externo - Administração"},
            {"nome": "Analista"}]
    pairs = match_cargos(pred, true)
    assert pairs[0][1]["nome"] == "Auditor de Controle Externo"
    assert "ADMINISTRACAO" in pairs[1][1]["nome"]
    assert pairs[2][1] is None


def test_evaluate_conta_recall_precisao_e_alucinacao():
    gab = {"edital": {"uf": "SP"},
           "cargos": [{"nome": "Analista", "vagas_total": None}, {"nome": "Técnico", "vagas_total": 2}]}
    res = evaluate({"uf": "SP"}, [{"nome": "Analista", "vagas_total": 5}, {"nome": "Motorista", "vagas_total": 1}], gab)
    assert res["cargos_recall"] == 0.5 and res["cargos_precisao"] == 0.5
    assert res["cargos_extras"] == ["Motorista"]
    assert res["alucinacoes"] == 1  # vagas=5 onde o documento não informa
