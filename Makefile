.PHONY: setup init up down logs test ps ask eval-qa api ui chat mcp

setup:            ## cria o .env a partir do exemplo
	@test -f .env || cp .env.example .env && echo ".env pronto"

init: setup       ## builda a imagem e inicializa o banco do Airflow + usuário admin
	docker compose build
	docker compose up airflow-init

up:               ## sobe a stack
	docker compose up -d

down:             ## derruba a stack (mantém os volumes)
	docker compose down

logs:
	docker compose logs -f airflow-scheduler

ps:
	docker compose ps

test:             ## roda os testes localmente (pip install pypdf pytest reportlab)
	python -m pytest -q

ask:              ## make ask Q="sua pergunta"
	PYTHONPATH=src python scripts/ask.py "$(Q)"

eval-qa:          ## avaliação das respostas com QAEvalChain
	python scripts/evaluate_qa.py

api:              ## API local (http://localhost:8000/docs)
	PYTHONPATH=src uvicorn editais.api.main:app --reload

ui:               ## chat Streamlit local (http://localhost:8501), precisa da API no ar
	cd streamlit_app && streamlit run app.py

chat:             ## sobe pgvector + API + chat em containers
	docker compose up -d pgvector api ui

mcp:              ## servidor MCP via stdio (Claude Desktop / Claude Code)
	PYTHONPATH=src python -m editais.api.mcp_server
