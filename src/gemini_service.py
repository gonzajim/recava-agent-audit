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
                "Marca el bloque de auditoría activo como completado y guarda el resumen de hallazgos. "
                "REQUISITO ESTRICTO: llama a esta función ÚNICAMENTE cuando hayas obtenido respuesta "
                "explícita a TODAS las preguntas marcadas [M] del bloque activo. "
                "Si queda alguna pregunta [M] sin responder, formula esa pregunta primero — NO llames a esta función. "
                "Una respuesta monosílaba ('sí', 'no', 'ya') no cubre una pregunta [M] que requiera detalle "
                "(excepción: cuando la respuesta real es 'no tenemos eso' o 'no aplica'). "
                "Cada bloque tiene entre 4 y 9 preguntas [M]; si llevas menos de 4 intercambios "
                "en el bloque activo es casi seguro que aún no está cubierto."
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
                            "Resumen de 3-5 frases con los hallazgos principales del bloque: "
                            "qué información se ha recogido, qué fortalezas y qué brechas se han detectado, "
                            "y clasificación de brechas (Crítico / Alto / Medio) si las hay."
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
) -> tuple[str, list[dict]]:
    """
    Runs one advisor turn with RAG augmentation from Pinecone.
    Returns (response_text, sources) where sources is the list of retrieved chunks
    with index, title, category, score, excerpt, page.
    """
    augmented_message, sources = _build_rag_message(embed_model, pinecone_index, user_message)

    contents: list = list(history) + [
        types.Content(role="user", parts=[types.Part(text=augmented_message)])
    ]

    config = types.GenerateContentConfig(system_instruction=EXPERT_SYSTEM_PROMPT)

    response = genai_client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    return _extract_text(response), sources


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
            text, _ = chat_with_expert(genai_client, embed_model, pinecone_index, [], query)
            return text
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


def _build_rag_message(
    embed_model, pinecone_index, user_message: str
) -> tuple[str, list[dict]]:
    """
    Embeds user_message, retrieves up to 6 scored chunks from Pinecone,
    and returns (augmented_message, sources).

    augmented_message prepends numbered excerpts so the model can cite [1]…[N].
    sources is a list of dicts: {index, title, category, score, excerpt, page}.
    """
    if pinecone_index is None:
        return user_message, []
    try:
        embedding = generate_embedding(embed_model, user_message)
        cat_filter = _detect_category_filter(user_message)
        docs = search_documents(pinecone_index, embedding, metadata_filter=cat_filter)
        if cat_filter and not docs:
            logger.info("RAG: category filter returned 0 results, retrying without filter")
            docs = search_documents(pinecone_index, embedding, metadata_filter=None)
    except Exception:
        logger.error("RAG retrieval failed", exc_info=True)
        return user_message, []

    if not docs:
        return user_message, []

    context_parts = []
    sources = []
    for i, doc in enumerate(docs, 1):
        title = doc.get("title") or "Documento"
        category = doc.get("category", "")
        score = doc.get("score", 0.0)
        page = doc.get("page")
        total_pages = doc.get("total_pages")
        content = doc.get("content", "").strip()

        meta_parts = [category] if category else []
        if page is not None:
            meta_parts.append(f"p.{page}/{total_pages}" if total_pages else f"p.{page}")
        meta_parts.append(f"relevancia={score:.2f}")
        header = f"[{i}] {title} ({', '.join(meta_parts)})"

        if content:
            context_parts.append(f"{header}\n{content}")

        sources.append({
            "index": i,
            "title": title,
            "category": category,
            "score": round(score, 3),
            "excerpt": content[:220] + ("…" if len(content) > 220 else ""),
            "page": page,
            "total_pages": total_pages,
        })

    if not context_parts:
        return user_message, []

    context_block = "\n\n".join(context_parts)
    augmented = (
        f"Fragmentos relevantes de la base documental "
        f"(cítalos inline como [1], [2]… cuando los uses en tu respuesta):\n\n"
        f"{context_block}\n\n"
        f"---\n\n"
        f"Pregunta: {user_message}"
    )
    return augmented, sources


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
