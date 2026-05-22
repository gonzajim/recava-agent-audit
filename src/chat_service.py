# src/chat_service.py
"""
Servicio de chat conversacional (Modo Auditor y Modo Asesor) basado en Gemini.
Reemplaza la integración anterior con OpenAI Assistants.
Persiste el historial en Firestore (colección 'conversations').
"""
import uuid
import datetime
from src.config import logger, firestore_db
from src.vector_service import retrieve_context
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
import google.generativeai as genai

CONVERSATIONS_COLLECTION = "conversations"

# ── System Prompts ────────────────────────────────────────────────────────────

AUDITOR_SYSTEM_PROMPT = """Eres un auditor digital experto en diligencia debida en sostenibilidad \
(CSDDD, ESRS, OIT, OCDE) y Derechos Humanos. Guías a empresas a través de una \
autoauditoría estructurada por bloques temáticos.

MODO ACTUAL: AUDITOR
- Conduce la conversación de forma estructurada, bloque a bloque.
- Analiza las respuestas del usuario para identificar brechas de cumplimiento.
- Emite hallazgos clasificados (Crítico/Alto/Medio/Bajo) al completar cada bloque.
- Solicita aclaraciones si la respuesta es incompleta o ambigua.
- Cuando detectes que el usuario ha completado un bloque, infórmale explícitamente.
- Corpus de referencia: CSDDD, EUDR, OIT, ISO 26000, OCDE, GRI.
- Responde siempre en español."""

ADVISOR_SYSTEM_PROMPT = """Eres un asesor experto en sostenibilidad, Derechos Humanos y \
cumplimiento normativo (CSDDD, ESRS, GRI, OIT, OCDE, ISO 26000).

MODO ACTUAL: ASESOR
- Responde preguntas técnicas de forma didáctica y adaptada al sector empresarial.
- Basate en los fragmentos del corpus legal y normativo proporcionados (RAG).
- Sé conciso, práctico y orientado a la acción empresarial.
- Proporciona ejemplos de evidencias o documentos que el usuario debería tener.
- Responde siempre en español."""


# ── Helpers de Firestore ──────────────────────────────────────────────────────

def _get_conversation_ref(thread_id: str):
    return firestore_db.collection(CONVERSATIONS_COLLECTION).document(thread_id)


def _create_thread(uid: str, endpoint_source: str) -> str:
    """Crea un nuevo hilo en Firestore y devuelve el thread_id."""
    thread_id = f"conv_{uuid.uuid4().hex}"
    _get_conversation_ref(thread_id).set({
        "thread_id": thread_id,
        "uid": uid,
        "endpoint_source": endpoint_source,
        "messages": [],
        "created_at": SERVER_TIMESTAMP,
        "updated_at": SERVER_TIMESTAMP,
        "summary": "",
        "last_timestamp": SERVER_TIMESTAMP,
    })
    return thread_id


def _load_history(thread_id: str) -> list[dict]:
    """Carga los mensajes de un hilo. Devuelve lista de dicts {role, content}."""
    doc = _get_conversation_ref(thread_id).get()
    if not doc.exists:
        return []
    messages = doc.to_dict().get("messages", [])
    # Formato esperado por Gemini: [{role: "user"/"model", parts: [text]}]
    history = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        history.append({"role": role, "parts": [m.get("text", "")]})
    return history


def _save_turn(thread_id: str, user_text: str, assistant_text: str, endpoint_source: str, uid: str):
    """Añade el turno (user + assistant) al historial del documento de Firestore."""
    ref = _get_conversation_ref(thread_id)
    doc = ref.get()
    if not doc.exists:
        ref.set({
            "thread_id": thread_id,
            "uid": uid,
            "endpoint_source": endpoint_source,
            "messages": [],
            "created_at": SERVER_TIMESTAMP,
            "updated_at": SERVER_TIMESTAMP,
            "summary": "",
            "last_timestamp": SERVER_TIMESTAMP,
        })

    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    # Usamos update con ArrayUnion para añadir ambos mensajes de forma atómica
    from google.cloud.firestore_v1 import ArrayUnion
    summary = user_text[:100]  # Preview para el historial
    ref.update({
        "messages": ArrayUnion([
            {"role": "user", "text": user_text, "timestamp": now_iso},
            {"role": "assistant", "text": assistant_text, "timestamp": now_iso},
        ]),
        "summary": summary,
        "last_timestamp": now_iso,
        "updated_at": SERVER_TIMESTAMP,
    })


# ── Generación de Respuesta Gemini ────────────────────────────────────────────

def _call_gemini(system_prompt: str, history: list[dict], user_message: str, rag_context: str = "") -> str:
    """Construye el prompt con el contexto RAG y genera la respuesta con Gemini."""
    enriched_system = system_prompt
    if rag_context:
        enriched_system += f"\n\n[CORPUS LEGAL DE REFERENCIA]\n{rag_context}"

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=genai.GenerationConfig(temperature=0.2),
            system_instruction=enriched_system,
        )
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error en llamada Gemini: {e}", exc_info=True)
        raise


# ── API Pública del Servicio ──────────────────────────────────────────────────

def handle_chat_auditor(user_message: str, thread_id: str | None, uid: str) -> dict:
    """
    Gestiona un turno del Modo Auditor.
    Crea el hilo si no existe, carga el historial, llama a Gemini y persiste.
    Devuelve: { response, thread_id, run_status }
    """
    endpoint_source = "/chat_auditor"
    if not thread_id:
        thread_id = _create_thread(uid, endpoint_source)

    history = _load_history(thread_id)
    rag_context = retrieve_context(user_message, top_k=3)
    response_text = _call_gemini(AUDITOR_SYSTEM_PROMPT, history, user_message, rag_context)
    _save_turn(thread_id, user_message, response_text, endpoint_source, uid)

    return {
        "response": response_text,
        "thread_id": thread_id,
        "run_status": "completed",
    }


def handle_chat_advisor(user_message: str, thread_id: str | None, uid: str) -> dict:
    """
    Gestiona un turno del Modo Asesor.
    Crea el hilo si no existe, carga el historial, llama a Gemini y persiste.
    Devuelve: { response, thread_id, run_status }
    """
    endpoint_source = "/chat_assistant"
    if not thread_id:
        thread_id = _create_thread(uid, endpoint_source)

    history = _load_history(thread_id)
    rag_context = retrieve_context(user_message, top_k=5)
    response_text = _call_gemini(ADVISOR_SYSTEM_PROMPT, history, user_message, rag_context)
    _save_turn(thread_id, user_message, response_text, endpoint_source, uid)

    return {
        "response": response_text,
        "thread_id": thread_id,
        "run_status": "completed",
    }


def get_recent_conversations(uid: str, limit: int = 5) -> list[dict]:
    """
    Devuelve las últimas N conversaciones del usuario.
    Formato de cada item: { thread_id, summary, last_timestamp, endpoint_source }
    """
    try:
        docs = (
            firestore_db.collection(CONVERSATIONS_COLLECTION)
            .where("uid", "==", uid)
            .order_by("last_timestamp", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        conversations = []
        for doc in docs:
            data = doc.to_dict()
            last_ts = data.get("last_timestamp")
            if hasattr(last_ts, "isoformat"):
                last_ts = last_ts.isoformat()
            conversations.append({
                "thread_id": data.get("thread_id"),
                "summary": data.get("summary", "Conversación previa"),
                "last_timestamp": last_ts,
                "endpoint_source": data.get("endpoint_source", ""),
            })
        return conversations
    except Exception as e:
        logger.error(f"Error obteniendo conversaciones recientes para uid={uid}: {e}", exc_info=True)
        return []


def get_conversation_thread(thread_id: str) -> dict | None:
    """
    Devuelve el hilo completo con todos sus mensajes.
    Formato: { thread_id, endpoint_source, messages: [{role, text, timestamp}] }
    """
    try:
        doc = _get_conversation_ref(thread_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return {
            "thread_id": data.get("thread_id"),
            "endpoint_source": data.get("endpoint_source", ""),
            "messages": data.get("messages", []),
        }
    except Exception as e:
        logger.error(f"Error cargando hilo {thread_id}: {e}", exc_info=True)
        return None
