"""API e MCP com o agente simulado (sem chamar OpenAI/BigQuery)."""
import asyncio
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient  # noqa: E402

FAKE = {"resposta": "R$ 82,00 [TCE-SP, p. 2]", "fontes": ["TCE-SP p.2"], "caminho": ["rotear → rag"], "sql": None,
        "edital": "TCE-SP", "modo": "agente", "tokens_entrada": 100, "tokens_saida": 10, "custo_usd": 0.0001,
        "latencia_ms": 5}


def _app(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from editais.api import main, service

    importlib.reload(main)
    monkeypatch.setattr(service, "answer", lambda q, m="agente": {**FAKE, "modo": m})
    monkeypatch.setattr(service, "list_editais", lambda: [{"orgao": "TCE-SP"}])
    return TestClient(main.app)


def test_ask_ok(monkeypatch):
    c = _app(monkeypatch, API_KEY="", RATE_LIMIT_PER_MIN="20")
    r = c.post("/api/ask", json={"pergunta": "Qual a taxa do TCE-SP?"})
    assert r.status_code == 200 and r.json()["resposta"].startswith("R$ 82")


def test_validacao_da_pergunta(monkeypatch):
    c = _app(monkeypatch, API_KEY="")
    assert c.post("/api/ask", json={"pergunta": "oi"}).status_code == 422          # curta demais
    assert c.post("/api/ask", json={"pergunta": "x" * 501}).status_code == 422     # longa demais
    assert c.post("/api/ask", json={"pergunta": "abc?", "modo": "hack"}).status_code == 422


def test_api_key(monkeypatch):
    c = _app(monkeypatch, API_KEY="segredo")
    body = {"pergunta": "Qual a taxa?"}
    assert c.post("/api/ask", json=body).status_code == 401
    assert c.post("/api/ask", json=body, headers={"X-API-Key": "segredo"}).status_code == 200


def test_rate_limit(monkeypatch):
    c = _app(monkeypatch, API_KEY="", RATE_LIMIT_PER_MIN="2")
    codes = [c.post("/api/ask", json={"pergunta": "Qual a taxa?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_trava_de_gasto_diario(monkeypatch):
    from editais.api import service

    b = service._Budget()
    monkeypatch.setattr(service, "DAILY_BUDGET_USD", 0.01)
    b.add(0.02)
    with pytest.raises(service.BudgetExceeded):
        b.check()


def test_mcp_expoe_ferramentas(monkeypatch):
    from editais.api import mcp_server, service

    monkeypatch.setattr(service, "answer", lambda q, m="agente": FAKE)
    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert tools == {"perguntar_editais", "listar_editais"}
    res = asyncio.run(mcp_server.mcp.call_tool("perguntar_editais", {"pergunta": "Qual a taxa do TCE-SP?"}))
    assert "R$ 82,00" in str(res)
