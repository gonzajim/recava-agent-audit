import os
from functools import lru_cache
from pinecone import Pinecone
import google.generativeai as genai
from src.config import logger

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

if not PINECONE_API_KEY:
    logger.warning("PINECONE_API_KEY no encontrada en variables de entorno.")

pc = Pinecone(api_key=PINECONE_API_KEY) if PINECONE_API_KEY else None
index_host = os.getenv("PINECONE_INDEX_HOST", "https://uclm-corpus-roma-dptaw1c.svc.aped-4627-b74a.pinecone.io")
index = pc.Index(host=index_host) if pc else None

@lru_cache(maxsize=100)
def hybrid_search_engine_cached(user_query: str, top_k: int = 10) -> str:
    """Retrieve context from Pinecone using serverless embeddings and hybrid search with cache."""
    if not index:
        return ""
    try:
        # Generar embeddings usando el modelo serverless text-embedding-004 de Google Gemini
        response = genai.embed_content(
            model="models/text-embedding-004",
            contents=user_query,
            task_type="retrieval_query"
        )
        query_emb = response['embedding']
        
        results = index.query(
            vector=query_emb,
            top_k=top_k,
            include_metadata=True
        )
        context = "\n\n".join([m['metadata'].get('text', '') for m in results.get('matches', [])])
        return context[:4000]  # Limit context size
    except Exception as e:
        logger.error(f"Error en búsqueda vectorial (Pinecone): {e}")
        return ""

def retrieve_context(query: str, top_k: int = 5) -> str:
    """Wrapper para recuperar el corpus legal experto de Pinecone."""
    return hybrid_search_engine_cached(query, top_k)
