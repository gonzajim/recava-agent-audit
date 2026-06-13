# src/rag_service.py
# Embedding uses sentence-transformers/all-MiniLM-L6-v2 (384 dims)
# to match the existing Pinecone corpus (uclm-corpus-roma).
# The embed_model instance is created once in config.py and passed here.
#
# Migration path (when ready to re-index corpus):
#   Set EMBEDDING_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2 (still 384 dims,
#   multilingual, better Spanish quality) and re-run the ingestion pipeline.
import io
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
                "page": meta.get("page"),
                "total_pages": meta.get("total_pages"),
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


# ---------------------------------------------------------------------------
# Category filter (shared with context_orchestrator to avoid circular import)
# ---------------------------------------------------------------------------

_CSDDD_TERMS = {
    "csddd", "diligencia debida", "cadena de actividades", "impactos adversos",
    "impacto adverso", "reparación", "reclamacion", "reclamación", "socio comercial",
    "due diligence", "conducta empresarial responsable",
}
_GRI_TERMS = {
    "gri", "global reporting initiative", "estándar gri", "estandar gri",
    "contenido gri", "indicador gri",
}


def detect_category_filter(query: str) -> dict | None:
    """
    Returns a Pinecone metadata filter based on keyword signals.
    Corpus categories: 'CSDDD', 'GRI', 'general'.

    - Clear GRI query → ['GRI', 'general']
    - Clear CSDDD query (≥2 hits) → ['CSDDD', 'general']
    - Mixed/CSRD/unknown → None (search all)
    """
    q = query.lower()
    hits_csddd = sum(1 for t in _CSDDD_TERMS if t in q)
    hits_gri = sum(1 for t in _GRI_TERMS if t in q)
    if hits_gri >= 1 and hits_csddd == 0:
        return {"primary_category": {"$in": ["GRI", "general"]}}
    if hits_csddd >= 2 and hits_gri == 0:
        return {"primary_category": {"$in": ["CSDDD", "general"]}}
    return None


# ---------------------------------------------------------------------------
# PDF extraction + chunking (for /upload_document endpoint)
# ---------------------------------------------------------------------------

_CHUNK_WORDS = 400
_CHUNK_OVERLAP = 50
_MAX_CHUNKS = 500   # guard against very large PDFs


def extract_pdf_chunks(file_bytes: bytes, chunk_words: int = _CHUNK_WORDS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """
    Extracts text from a PDF byte string and splits it into overlapping chunks.
    Uses pypdf (pure Python, no system deps).
    Returns a list of non-empty text strings (up to _MAX_CHUNKS).
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    all_words: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        all_words.extend(text.split())

    if not all_words:
        return []

    chunks = []
    step = chunk_words - overlap
    for start in range(0, len(all_words), step):
        chunk = " ".join(all_words[start : start + chunk_words])
        if chunk.strip():
            chunks.append(chunk)
        if len(chunks) >= _MAX_CHUNKS:
            break

    return chunks
