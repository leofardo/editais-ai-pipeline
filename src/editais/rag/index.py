"""Indexação: silver.edital_paginas (BigQuery) -> chunks por tokens -> embeddings -> pgvector.

- Chunking por TOKENS (tiktoken, mesmo tokenizer dos embeddings da OpenAI), com overlap.
- IDs determinísticos (<sha256>-p<página>-c<n>): reexecutar não duplica nem paga de novo.
- Metadados por chunk (órgão, UF, página) para filtrar e citar a fonte na resposta.

Uso:  python -m editais.rag.index [--dry-run]
"""

from __future__ import annotations

import argparse

import tiktoken
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from editais import warehouse as wh
from editais.rag import settings
from editais.rag.store import get_store

ENCODING = "cl100k_base"  # tokenizer dos text-embedding-3-*


def load_pages() -> list[dict]:
    return wh.query(
        f"""
        SELECT p.sha256, p.page_number, p.text_clean, d.orgao, d.uf, d.numero_edital, d.original_filename
        FROM `{wh.table_id(wh.SILVER_PAGES)}` p
        JOIN {settings.gold_table('dim_editais')} d ON d.edital_id = p.sha256
        WHERE p.char_count > 0
        ORDER BY p.sha256, p.page_number
        """
    )


def build_chunks(pages: list[dict]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=ENCODING, chunk_size=settings.CHUNK_TOKENS, chunk_overlap=settings.CHUNK_OVERLAP
    )
    docs = []
    for p in pages:
        for i, text in enumerate(splitter.split_text(p["text_clean"])):
            docs.append(Document(
                id=f"{p['sha256'][:16]}-p{p['page_number']}-c{i}",
                page_content=text,
                metadata={"edital_id": p["sha256"], "orgao": p["orgao"], "uf": p["uf"],
                          "numero_edital": p["numero_edital"], "arquivo": p["original_filename"],
                          "pagina": p["page_number"], "chunk": i},
            ))
    return docs


def existing_ids(store) -> set[str]:
    from sqlalchemy import text

    with store.session_maker() as s:
        rows = s.execute(text(
            "SELECT e.id FROM langchain_pg_embedding e JOIN langchain_pg_collection c "
            "ON e.collection_id = c.uuid WHERE c.name = :n"), {"n": settings.COLLECTION})
        return {r[0] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="só conta chunks/tokens, sem chamar a OpenAI")
    args = ap.parse_args()

    docs = build_chunks(load_pages())
    store = get_store()
    done = existing_ids(store)
    todo = [d for d in docs if d.id not in done]

    enc = tiktoken.get_encoding(ENCODING)
    tokens = sum(len(enc.encode(d.page_content)) for d in todo)
    print(f"chunks: {len(docs)} total | {len(done)} já indexados | {len(todo)} novos | {tokens:,} tokens a embutir "
          f"(chunk={settings.CHUNK_TOKENS} overlap={settings.CHUNK_OVERLAP} modelo={settings.EMBEDDING_MODEL})")

    if args.dry_run or not todo:
        return
    if tokens > settings.MAX_EMBED_TOKENS:
        raise SystemExit(f"Abortado: {tokens:,} tokens > RAG_MAX_EMBED_TOKENS={settings.MAX_EMBED_TOKENS:,}")

    batch = 200
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        store.add_documents(part, ids=[d.id for d in part])
        print(f"  indexados {min(i + batch, len(todo))}/{len(todo)}")


if __name__ == "__main__":
    main()
