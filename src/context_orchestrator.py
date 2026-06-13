"""
Hybrid RAG orchestrator — Pinecone and FAISS search run concurrently.

A module-level ThreadPoolExecutor reuses threads across requests (no cold-start
overhead per call). Both searches receive the same query embedding, which is
computed once before the fan-out.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from src.rag_service import detect_category_filter, generate_embedding, search_documents

logger = logging.getLogger(__name__)

_WORKERS = int(os.getenv("RAG_SEARCH_WORKERS", "4"))
_executor = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="rag_worker")

_TOP_K_LOCAL = 6
_MIN_SCORE_LOCAL = 0.30
_MAX_EACH = 6       # cap on results from each source before merge


def search_hybrid(
    thread_id: str,
    user_message: str,
    embed_model,
    pinecone_index,
    local_store,
) -> tuple[list[dict], list[dict]]:
    """
    Embeds user_message once, then fans out to Pinecone and FAISS concurrently.
    Returns (pinecone_docs, local_docs) — caller merges and numbers them.
    Either list can be empty if the source has no data or fails.
    """
    query_embedding = generate_embedding(embed_model, user_message)
    cat_filter = detect_category_filter(user_message)

    futures: dict[str, object] = {}

    if pinecone_index is not None:
        futures["pinecone"] = _executor.submit(_pine_search, pinecone_index, query_embedding, cat_filter)

    if local_store is not None and local_store.chunk_count(thread_id) > 0:
        futures["local"] = _executor.submit(
            local_store.search, thread_id, query_embedding, _TOP_K_LOCAL, _MIN_SCORE_LOCAL
        )

    pinecone_docs: list[dict] = []
    local_docs: list[dict] = []

    for key, fut in futures.items():
        try:
            result = fut.result(timeout=12)
            if key == "pinecone":
                pinecone_docs = result
            else:
                local_docs = result
        except Exception:
            logger.error("Hybrid RAG: %s search failed", key, exc_info=True)

    return pinecone_docs[:_MAX_EACH], local_docs[:_MAX_EACH]


def _pine_search(pinecone_index, query_embedding, cat_filter):
    docs = search_documents(pinecone_index, query_embedding, metadata_filter=cat_filter)
    if cat_filter and not docs:
        logger.info("Hybrid RAG: category filter empty, retrying without filter")
        docs = search_documents(pinecone_index, query_embedding, metadata_filter=None)
    return docs
