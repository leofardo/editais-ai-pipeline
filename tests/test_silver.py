import json

import pytest

from editais import llm_extraction
from editais.cleaning import clean_page_text
from editais.extraction_schema import Cargo, Edital
from editais.page_selection import select_pages
from editais.storage import LocalStorage


# ---------------- limpeza ----------------

def test_limpeza_remove_ruido_e_junta_hifenizacao():
    bruto = (
        "pcimarkpci MjgwNDox:RnJp\nwww.pciconcursos.com.br\nPágina 3 de 46\n"
        "Período de inscri-\nção:   01/12/2026\n__________\n\n\n\nCargo: Analista"
    )
    limpo = clean_page_text(bruto)
    assert "pcimark" not in limpo and "pciconcursos" not in limpo and "Página 3" not in limpo
    assert "inscrição: 01/12/2026" in limpo
    assert "\n\n\n" not in limpo and "____" not in limpo


def test_limpeza_preserva_numeros_de_tabela_e_remove_numero_de_pagina():
    pagina = "7\nCargo\nVagas\nAUDITOR\nR$ 17.743,05\n59\nANALISTA\n4\n12"
    linhas = clean_page_text(pagina).split("\n")
    assert linhas[0] == "Cargo"  # "7" no topo = número de página
    assert "59" in linhas  # dado da tabela preservado
    assert linhas[-1] == "4"  # "12" no rodapé = número de página


def test_cache_invalida_quando_texto_muda(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(llm_extraction, "call_llm",
                        lambda p, m: (chamadas.append(1) or _edital_fake(), {"input_tokens": 1, "output_tokens": 1}))
    st = LocalStorage(tmp_path)
    llm_extraction.extract_with_cache("sha1", [_p(1, "texto A")], st, model="m")
    llm_extraction.extract_with_cache("sha1", [_p(1, "texto B")], st, model="m")
    assert len(chamadas) == 2


def test_limpeza_texto_vazio():
    assert clean_page_text(None) == "" and clean_page_text("   ") == ""


# ---------------- seleção de páginas ----------------

def _p(n, text):
    return {"page_number": n, "text_clean": text}


def test_selecao_prioriza_paginas_de_vagas_e_respeita_teto():
    paginas = [_p(1, "EDITAL 01/2026 abertura"), _p(2, "disposições gerais")]
    paginas += [_p(i, "texto irrelevante " * 50) for i in range(3, 20)]
    paginas.append(_p(20, "Quadro de vagas: Cargo Analista, vagas 12, remuneração R$ 8.500,00"))
    escolhidas = select_pages(paginas, max_tokens=200)
    numeros = [p["page_number"] for p in escolhidas]
    assert numeros == [1, 2, 20]  # capa + a página com vagas; irrelevantes ficam de fora


def test_selecao_nunca_passa_do_teto():
    paginas = [_p(i, "vagas remuneração R$ 1.000 " * 400) for i in range(1, 30)]
    escolhidas = select_pages(paginas, max_tokens=5000)
    total = sum(len(p["text_clean"]) / 3.5 for p in escolhidas)
    assert total <= 5000 + len(escolhidas)


# ---------------- extração com cache (LLM simulado) ----------------

def _edital_fake():
    return Edital(
        orgao="Tribunal X", numero_edital="01/2026", banca_organizadora="Banca Y", esfera="estadual",
        uf="SP", municipio=None, data_publicacao="2026-03-10", inscricao_inicio="2026-03-11",
        inscricao_fim="data inválida", data_prova=None, taxa_inscricao_min=100.0, taxa_inscricao_max=130.0,
        documento_completo=True, observacoes=None,
        cargos=[Cargo(nome="Analista", area="TI", escolaridade="superior", vagas_ampla_concorrencia=10,
                      vagas_total=12, vagas_referem_se_ao_grupo=False, cadastro_reserva=True, salario_inicial=8500.0, carga_horaria_semanal=40,
                      localidade="São Paulo", requisitos="Superior em TI", pagina_fonte=2)],
    )


def test_cache_evita_segunda_chamada(tmp_path, monkeypatch):
    chamadas = []

    def fake_call(pages, model):
        chamadas.append(model)
        return _edital_fake(), {"input_tokens": 1000, "output_tokens": 200}

    monkeypatch.setattr(llm_extraction, "call_llm", fake_call)
    storage = LocalStorage(tmp_path)
    pages = [_p(1, "texto")]

    p1 = llm_extraction.extract_with_cache("sha1", pages, storage, model="m")
    p2 = llm_extraction.extract_with_cache("sha1", pages, storage, model="m")
    assert chamadas == ["m"]  # o LLM foi chamado UMA vez
    assert p1["from_cache"] is False and p2["from_cache"] is True
    assert json.loads(storage.read_text(llm_extraction.cache_key("sha1", "m", pages)))["edital"]["orgao"] == "Tribunal X"


def test_payload_vira_linhas_da_silver(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_extraction, "call_llm", lambda p, m: (_edital_fake(), {"input_tokens": 1, "output_tokens": 1}))
    payload = llm_extraction.extract_with_cache("sha1", [_p(1, "x")], LocalStorage(tmp_path), model="m")
    edital, cargos = llm_extraction.payload_to_rows(payload, "tce.pdf")
    assert edital["qtd_cargos"] == 1 and edital["original_filename"] == "tce.pdf"
    assert edital["data_publicacao"] == "2026-03-10"
    assert edital["inscricao_fim"] is None  # data malformada não quebra a carga
    assert cargos[0]["nome"] == "Analista" and cargos[0]["cargo_idx"] == 0 and cargos[0]["sha256"] == "sha1"


def test_schema_rejeita_escolaridade_invalida():
    with pytest.raises(Exception):
        Cargo(nome="X", area=None, escolaridade="doutorado", vagas_ampla_concorrencia=None, vagas_total=None, vagas_referem_se_ao_grupo=False,
              cadastro_reserva=False, salario_inicial=None, carga_horaria_semanal=None, localidade=None,
              requisitos=None, pagina_fonte=None)


def test_vagas_de_grupo_viram_vagas_total_grupo(tmp_path, monkeypatch):
    ed = _edital_fake()
    base = ed.cargos[0].model_dump()
    ed.cargos = [Cargo(**{**base, "nome": n, "vagas_total": 10170, "vagas_referem_se_ao_grupo": True})
                 for n in ("Professor - Arte", "Professor - Física")]
    monkeypatch.setattr(llm_extraction, "call_llm", lambda p, m: (ed, {"input_tokens": 1, "output_tokens": 1}))
    payload = llm_extraction.extract_with_cache("sha9", [_p(1, "x")], LocalStorage(tmp_path), model="m")
    _, cargos = llm_extraction.payload_to_rows(payload, "mg.pdf")
    assert all(c["vagas_total"] is None and c["vagas_total_grupo"] == 10170 for c in cargos)
    assert all(c["vagas_referem_se_ao_grupo"] is True for c in cargos)
