"""Servidor MCP: expõe o assistente de editais como ferramentas para Claude, Cursor etc.

  python -m editais.api.mcp_server                 # stdio (Claude Desktop / Claude Code)
  python -m editais.api.mcp_server --http          # streamable-http em http://localhost:8001/mcp

Só ferramentas de LEITURA e com o mesmo limite de gasto diário da API.
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from editais.api import service

mcp = MCPServer(
    name="editais-concursos",
    instructions=("Responde perguntas sobre editais de concurso público indexados (vagas, salários, datas, "
                  "regras). Use listar_editais para ver quais concursos existem antes de perguntar."),
)


@mcp.tool(description="Pergunta em linguagem natural sobre os editais. Retorna a resposta com as fontes.")
def perguntar_editais(pergunta: str) -> str:
    r = service.answer(pergunta, "agente")
    fontes = ", ".join(r["fontes"]) or "-"
    sql = f"\n\nSQL usado:\n{r['sql']}" if r.get("sql") else ""
    return f"{r['resposta']}\n\nFontes: {fontes}{sql}"


@mcp.tool(description="Lista os editais disponíveis (órgão, UF, banca, vagas, faixa salarial, status).")
def listar_editais() -> list[dict]:
    return service.list_editais()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="usa streamable-http em vez de stdio")
    ap.add_argument("--port", type=int, default=8001)
    a = ap.parse_args()
    if a.http:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=a.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
