"""
Thread-safe per-session FAISS vector store with LRU eviction.

Uses IndexFlatIP with L2-normalised vectors, which gives cosine similarity.
No disk persistence — lives in RAM only. Cloud Run session stickiness keeps
the index alive across requests from the same user on the same instance.
If the instance restarts, the user must re-upload their document.
"""
import logging
import os
import threading
from collections import OrderedDict

import faiss
import numpy as np

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 384            # all-MiniLM-L6-v2
_MAX_SESSIONS = int(os.getenv("FAISS_MAX_SESSIONS", "50"))


class LocalVectorStore:
    """Per-session FAISS IndexFlatIP (inner-product = cosine on L2-normed vecs) with LRU eviction."""

    def __init__(self, dim: int = _EMBEDDING_DIM, max_sessions: int = _MAX_SESSIONS):
        self._dim = dim
        self._max = max_sessions
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, dict] = OrderedDict()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_chunks(self, thread_id: str, texts: list[str], embeddings: list[list[float]]) -> int:
        """
        Adds text chunks with pre-computed embeddings to the session index.
        L2-normalises the vectors before insertion so inner product == cosine.
        Returns total chunk count for the session after insertion.
        """
        vecs = np.array(embeddings, dtype="float32")
        faiss.normalize_L2(vecs)

        with self._lock:
            if thread_id not in self._sessions:
                if len(self._sessions) >= self._max:
                    evicted = next(iter(self._sessions))
                    del self._sessions[evicted]
                    logger.info("FAISS LRU evicted session %s", evicted)
                self._sessions[thread_id] = {
                    "index": faiss.IndexFlatIP(self._dim),
                    "chunks": [],
                }

            session = self._sessions[thread_id]
            session["index"].add(vecs)
            session["chunks"].extend(texts)
            self._sessions.move_to_end(thread_id)
            count = session["index"].ntotal

        return count

    def clear(self, thread_id: str) -> None:
        with self._lock:
            self._sessions.pop(thread_id, None)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        thread_id: str,
        query_embedding: list[float],
        top_k: int = 6,
        min_score: float = 0.30,
    ) -> list[dict]:
        """
        Searches the session FAISS index.
        Returns dicts with the same keys as Pinecone results so they merge cleanly.
        """
        with self._lock:
            if thread_id not in self._sessions:
                return []
            session = self._sessions[thread_id]
            self._sessions.move_to_end(thread_id)
            index = session["index"]
            chunks = list(session["chunks"])   # snapshot for reading outside lock

        if index.ntotal == 0:
            return []

        q = np.array([query_embedding], dtype="float32")
        faiss.normalize_L2(q)

        k = min(top_k, index.ntotal)
        scores, indices = index.search(q, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or float(score) < min_score:
                continue
            results.append({
                "content": chunks[idx],
                "title": "Documento adjunto",
                "category": "uploaded",
                "score": float(score),
                "page": None,
                "total_pages": None,
            })
        return results

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def chunk_count(self, thread_id: str) -> int:
        with self._lock:
            s = self._sessions.get(thread_id)
            return s["index"].ntotal if s else 0

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)
