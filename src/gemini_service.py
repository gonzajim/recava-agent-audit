# src/gemini_service.py
from google.genai import types
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from src.config import logger
from src.assistant_instructions import AUDITOR_SYSTEM_PROMPT, EXPERT_SYSTEM_PROMPT
from src.rag_service import generate_embedding, search_documents

_GEMINI_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Tool declarations for the auditor
# ---------------------------------------------------------------------------

AUDITOR_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="invoke_sustainability_expert",
            description=(
                "Consulta al experto en sostenibilidad cuando el usuario formula "
                "una pregunta técnica o normativa (CSRD, CSDDD, NEIS, OCDE, "
                "diligencia debida, reporting, etc.). "
                "Devuelve una respuesta precisa y fundamentada."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Pregunta concreta que debe responder el experto en sostenibilidad.",
                    )
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="complete_audit_block",
            description=(
                "Marca el bloque de auditoría activo como completado. "
                "Llama SOLO cuando hayas recogido información suficiente sobre los "
                "aspectos fundamentales del bloque. Tras llamarla, anuncia el siguiente bloque."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "block_id": types.Schema(
                        type=types.Type.STRING,
                        description="ID del bloque a marcar como completado: block_1 a block_8.",
                    ),
                    "summary": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Resumen de 2-4 frases con los hallazgos principales del bloque: "
                            "qué información se ha recogido, qué fortalezas y qué brechas se han detectado."
                        ),
                    ),
                },
                required=["block_id", "summary"],
            ),
        ),
    ]
)

_AUDITOR_TOOL_CONFIG = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(mode="AUTO")
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chat_with_auditor(
    genai_client,
    embed_model,
    firestore_db,
    pinecone_index,
    history: list[dict],
    user_message: str,
    thread_id: str,
    audit_context: str,
) -> str:
    """
    Runs one auditor turn with tool-call looping.
    Handles: invoke_sustainability_expert and complete_audit_block.
    Returns the final text response.
    """
    system = AUDITOR_SYSTEM_PROMPT.replace("{audit_context}", audit_context)

    contents: list = list(history) + [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[AUDITOR_TOOLS],
        tool_config=_AUDITOR_TOOL_CONFIG,
    )

    max_rounds = 6  # safety cap on tool-call rounds
    for _ in range(max_rounds):
        response = genai_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=contents,
            config=config,
        )

        if not response.function_calls:
            break

        function_responses = []
        for fc in response.function_calls:
            result = _dispatch_tool(
                fc, genai_client, embed_model, firestore_db, pinecone_index, thread_id
            )
            function_responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            )

        contents.append(response.candidates[0].content)
        contents.append(types.Content(role="user", parts=function_responses))

    return _extract_text(response)


def chat_with_expert(
    genai_client,
    embed_model,
    pinecone_index,
    history: list[dict],
    user_message: str,
) -> str:
    """
    Runs one advisor turn with optional RAG augmentation from Pinecone.
    embed_model is a SentenceTransformer instance used to embed the query.
    """
    augmented_message = _build_rag_message(embed_model, pinecone_index, user_message)

    contents: list = list(history) + [
        types.Content(role="user", parts=[types.Part(text=augmented_message)])
    ]

    config = types.GenerateContentConfig(system_instruction=EXPERT_SYSTEM_PROMPT)

    response = genai_client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    return _extract_text(response)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dispatch_tool(
    fc, genai_client, embed_model, firestore_db, pinecone_index, thread_id: str
) -> str:
    name = fc.name
    args = dict(fc.args) if fc.args else {}

    if name == "invoke_sustainability_expert":
        query = args.get("query", "")
        logger.info("Tool invoke_sustainability_expert: thread=%s query=%r", thread_id, query[:80])
        try:
            return chat_with_expert(genai_client, embed_model, pinecone_index, [], query)
        except Exception:
            logger.error("invoke_sustainability_expert failed", exc_info=True)
            return "El experto no pudo procesar la consulta en este momento."

    if name == "complete_audit_block":
        block_id = args.get("block_id", "")
        summary = args.get("summary", "")
        logger.info("Tool complete_audit_block: thread=%s block=%s", thread_id, block_id)
        return _update_audit_progress(firestore_db, thread_id, block_id, summary)

    logger.warning("Unknown tool called: %s", name)
    return f"Herramienta desconocida: {name}"


def _update_audit_progress(
    firestore_db, thread_id: str, block_id: str, summary: str
) -> str:
    try:
        doc_ref = firestore_db.collection("audit_progress").document(thread_id)
        doc_ref.set(
            {
                "blocks": {
                    block_id: {
                        "status": "completed",
                        "summary": summary,
                        "completed_at": SERVER_TIMESTAMP,
                        "updated_at": SERVER_TIMESTAMP,
                    }
                },
                "updated_at": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return f"Bloque {block_id} marcado como completado."
    except Exception:
        logger.error(
            "Failed to update audit progress thread=%s block=%s", thread_id, block_id, exc_info=True
        )
        return f"Bloque {block_id} procesado (no se pudo persistir el estado)."


_CSDDD_TERMS = {
    "csddd", "diligencia debida", "cadena de actividades", "impactos adversos",
    "impacto adverso", "reparación", "reclamacion", "reclamación", "socio comercial",
    "due diligence", "conducta empresarial responsable",
}
_GRI_TERMS = {
    "gri", "global reporting initiative", "estándar gri", "estandar gri",
    "contenido gri", "indicador gri",
}


def _detect_category_filter(query: str) -> dict | None:
    """
    Returns a Pinecone metadata filter based on keyword signals in the query.
    Corpus categories: 'CSDDD', 'GRI', 'general' (CSRD/NEIS/OCDE/marco teórico).

    Strategy:
    - Clear CSDDD query → ['CSDDD', 'general']  (exclude GRI-only chunks)
    - Clear GRI query   → ['GRI', 'general']    (exclude CSDDD-only chunks)
    - Mixed / CSRD / unknown → None (search all categories)
    """
    q = query.lower()
    hits_csddd = sum(1 for t in _CSDDD_TERMS if t in q)
    hits_gri = sum(1 for t in _GRI_TERMS if t in q)

    if hits_gri >= 1 and hits_csddd == 0:
        return {"primary_category": {"$in": ["GRI", "general"]}}
    if hits_csddd >= 2 and hits_gri == 0:
        return {"primary_category": {"$in": ["CSDDD", "general"]}}
    return None  # search all — CSRD/NEIS/OCDE live in 'general'


def _build_rag_message(embed_model, pinecone_index, user_message: str) -> str:
    """
    Embeds user_message with SentenceTransformer, applies category filtering,
    retrieves candidates (top_k=12), drops chunks below score 0.55,
    and prepends up to 6 relevant excerpts to the message.
    """
    if pinecone_index is None:
        return user_message
    try:
        embedding = generate_embedding(embed_model, user_message)
        cat_filter = _detect_category_filter(user_message)
        docs = search_documents(pinecone_index, embedding, metadata_filter=cat_filter)
        if cat_filter and not docs:
            # Fallback: retry without filter if category narrowing returned nothing
            logger.info("RAG: category filter returned 0 results, retrying without filter")
            docs = search_documents(pinecone_index, embedding, metadata_filter=None)
    except Exception:
        logger.error("RAG retrieval failed", exc_info=True)
        return user_message

    if not docs:
        return user_message

    context_parts = []
    for i, doc in enumerate(docs, 1):
        title = doc.get("title") or "Documento"
        category = doc.get("category", "")
        score = doc.get("score", 0.0)
        header = f"[{i}] {title}" + (f" ({category}, score={score:.2f})" if category else "")
        content = doc.get("content", "").strip()
        if content:
            context_parts.append(f"{header}\n{content}")

    if not context_parts:
        return user_message

    context_block = "\n\n".join(context_parts)
    return (
        f"Contexto de la base documental de sostenibilidad:\n\n"
        f"{context_block}\n\n"
        f"---\n\n"
        f"Pregunta del usuario: {user_message}"
    )


def _extract_text(response) -> str:
    try:
        text = response.text
        if text:
            return text.strip()
    except Exception:
        pass
    try:
        parts = response.candidates[0].content.parts
        return "\n".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()
    except Exception:
        logger.error("Could not extract text from Gemini response", exc_info=True)
        return "No se pudo obtener una respuesta del modelo."
