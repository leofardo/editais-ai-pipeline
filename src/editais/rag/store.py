"""Vector store (pgvector via langchain-postgres)."""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from editais.rag import settings


@lru_cache
def get_store() -> PGVector:
    return PGVector(
        embeddings=OpenAIEmbeddings(model=settings.EMBEDDING_MODEL),
        collection_name=settings.COLLECTION,
        connection=settings.pg_connection(),
        use_jsonb=True,  # metadados em JSONB: permite filtrar por órgão/UF
    )
