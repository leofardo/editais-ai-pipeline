"""Decisões do grafo (arestas condicionais): testáveis sem chamar o LLM."""
import pytest

pytest.importorskip("langgraph")

from langgraph.graph import END  # noqa: E402

from editais.rag import agent  # noqa: E402


def test_rotas():
    assert agent.depois_de_rotear({"route": "sql"}) == "consultar_sql"
    assert agent.depois_de_rotear({"route": "rag"}) == "recuperar"
    assert agent.depois_de_rotear({"route": "fora_do_escopo"}) == "fora_do_escopo"


def test_sql_vazio_cai_para_rag():
    assert agent.depois_do_sql({"answer": ""}) == "recuperar"
    assert agent.depois_do_sql({"answer": "R$ 82,00"}) == END


def test_crag_reescreve_uma_vez_e_desiste():
    assert agent.depois_de_avaliar({"docs": ["x"], "rewrites": 0}) == "gerar"
    assert agent.depois_de_avaliar({"docs": [], "rewrites": 0}) == "reescrever"
    assert agent.depois_de_avaliar({"docs": [], "rewrites": agent.MAX_REWRITES}) == "sem_resposta"


def test_self_rag_regenera_com_limite():
    assert agent.depois_de_verificar({"grounded": True, "regenerations": 0}) == END
    assert agent.depois_de_verificar({"grounded": False, "regenerations": 1}) == "gerar"
    assert agent.depois_de_verificar({"grounded": False, "regenerations": agent.MAX_REGENERATIONS + 1}) == END


def test_grafo_compila_com_todos_os_nos():
    nodes = set(agent.build_agent().get_graph().nodes)
    assert {"identificar_edital", "rotear", "consultar_sql", "recuperar", "avaliar_documentos",
            "reescrever", "gerar", "verificar_fundamentacao", "sem_resposta", "fora_do_escopo"} <= nodes
