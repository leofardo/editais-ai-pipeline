"""Configuração da camada de consulta (lida do .env)."""

import os

COLLECTION = os.getenv("RAG_COLLECTION", "editais")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

# Tamanho do chunk em TOKENS (mesma unidade do modelo de embeddings) e sobreposição.
CHUNK_TOKENS = int(os.getenv("RAG_CHUNK_TOKENS", "500"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))

# Trava de custo: a indexação aborta se for embutir mais tokens que isso numa execução.
MAX_EMBED_TOKENS = int(os.getenv("RAG_MAX_EMBED_TOKENS", "800000"))


def pg_connection() -> str:
    user = os.getenv("PGVECTOR_USER", "editais")
    pwd = os.getenv("PGVECTOR_PASSWORD", "editais")
    host = os.getenv("PGVECTOR_HOST", "localhost")
    port = os.getenv("PGVECTOR_PORT", "5433")
    db = os.getenv("PGVECTOR_DB", "editais")
    return f"postgresql+psycopg://{user}:{pwd}@{host}:{port}/{db}"


def gold_table(name: str) -> str:
    return f"`{os.environ['GCP_PROJECT_ID']}.{os.getenv('BQ_DATASET_GOLD', 'editais_gold')}.{name}`"


# Preços de referência (US$ por 1M de tokens) para estimar custo. Confira em openai.com/api/pricing
# e ajuste pelo .env se mudarem.
PRICE_IN = float(os.getenv("OPENAI_PRICE_INPUT_PER_M", "0.40"))     # gpt-4.1-mini entrada
PRICE_OUT = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_M", "1.60"))   # gpt-4.1-mini saída
PRICE_EMBED = float(os.getenv("OPENAI_PRICE_EMBED_PER_M", "0.02"))  # text-embedding-3-small


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT
