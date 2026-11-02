from editais.grounding import ground_cargos, int_in_text, money_in_text

TEXTO = "AUDITOR 40h R$ 17.743,05 59 | ADMINISTRAÇÃO 40h R$ 17.743,05 4 | sendo 10.170 vagas para Professor"


def test_int_in_text():
    assert int_in_text(59, TEXTO) is True
    assert int_in_text(10170, TEXTO) is True  # formato com ponto de milhar
    assert int_in_text(63, TEXTO) is False  # 59 + 4: conta feita pelo modelo
    assert int_in_text(17, TEXTO) is False  # não casa dentro de "17.743,05"
    assert int_in_text(None, TEXTO) is None


def test_money_in_text():
    assert money_in_text(17743.05, TEXTO) is True
    assert money_in_text(17743.5, TEXTO) is False


def test_ground_cargos_marca_suspeitos():
    rows = ground_cargos([{"vagas_total": 63, "salario_inicial": 17743.05},
                          {"vagas_total": None, "vagas_total_grupo": 10170, "salario_inicial": None}], TEXTO)
    assert rows[0]["vagas_no_texto"] is False and rows[0]["salario_no_texto"] is True
    assert rows[1]["vagas_no_texto"] is True and rows[1]["salario_no_texto"] is None
