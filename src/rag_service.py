# src/rag_service.py
# Embedding uses sentence-transformers/all-MiniLM-L6-v2 (384 dims)
# to match the existing Pinecone corpus (uclm-corpus-roma).
# The embed_model instance is created once in config.py and passed here.
#
# Migration path (when ready to re-index corpus):
#   Set EMBEDDING_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2 (still 384 dims,
#   multilingual, better Spanish quality) and re-run the ingestion pipeline.
import uuid
from src.config import logger


def generate_embedding(embed_model, text: str) -> list[float]:
    """Encodes text using the pre-loaded SentenceTransformer model."""
    vector = embed_model.encode(text, normalize_embeddings=True)
    return vector.tolist()


_MIN_SCORE = 0.55      # Discard chunks below this cosine similarity
_CANDIDATE_K = 12     # Retrieve this many candidates before score-filtering
_MAX_RESULTS = 6      # Cap on chunks passed to the LLM after filtering


def search_documents(
    pinecone_index,
    query_embedding: list[float],
    top_k: int = _CANDIDATE_K,
    metadata_filter: dict | None = None,
    min_score: float = _MIN_SCORE,
) -> list[dict]:
    """
    Queries Pinecone and returns matching document excerpts.

    Corpus categories: 'CSDDD', 'GRI', 'general' (includes CSRD/NEIS/OCDE docs).
    Pass metadata_filter to narrow by category, e.g.:
      {"primary_category": {"$in": ["CSDDD", "general"]}}
    Returns [] if pinecone_index is None or on any exception.
    """
    if pinecone_index is None:
        return []
    try:
        query_kwargs = dict(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )
        if metadata_filter:
            query_kwargs["filter"] = metadata_filter

        response = pinecone_index.query(**query_kwargs)

        results = []
        for match in response.get("matches", []):
            score = match.get("score", 0.0)
            if score < min_score:
                continue
            meta = match.get("metadata", {})
            results.append({
                "content": meta.get("text") or meta.get("content", ""),
                "title": meta.get("source") or meta.get("title", ""),
                "category": meta.get("primary_category", ""),
                "score": score,
            })

        return results[:_MAX_RESULTS]
    except Exception:
        logger.error("Pinecone search failed", exc_info=True)
        return []


def ingest_document(
    embed_model,
    pinecone_index,
    doc_id: str | None,
    content: str,
    title: str = "",
    source_url: str = "",
    doc_type: str = "",
) -> str:
    """
    Generates an embedding for content and upserts it to Pinecone
    using the same metadata schema as the existing corpus.
    Returns the doc_id used (auto-generated UUID if not supplied).
    """
    if pinecone_index is None:
        raise RuntimeError("Pinecone index is not configured.")

    doc_id = doc_id or str(uuid.uuid4())
    embedding = generate_embedding(embed_model, content)
    pinecone_index.upsert(vectors=[{
        "id": doc_id,
        "values": embedding,
        "metadata": {
            "text": content,
            "source": source_url or title,
            "primary_category": doc_type,
            "block_type": "text",
            "entities": [],
            "triplets": [],
            "graph_importance": 0,
        },
    }])
    logger.info("Ingested document '%s' into Pinecone.", doc_id)
    return doc_id
