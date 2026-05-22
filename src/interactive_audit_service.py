# src/interactive_audit_service.py
"""
Servicio de Auditoría Interactiva Secuencial con Skip Logic.

Gestiona sesiones de autoauditoría guiadas por cuestionario_base.json.
Persiste el estado en Firestore (colección 'interactive_audits').

Skip Logic:
  - Cada pregunta puede tener un campo `show_if`: lista de condiciones (AND lógico).
  - Si la pregunta NO debe mostrarse, se registra como '__skipped__' en responses.
  - Las condiciones sólo referencian preguntas anteriores en el flujo.
"""
import json
import os
import uuid
from src.config import logger, firestore_db
from src.vector_service import retrieve_context
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
import google.generativeai as genai

INTERACTIVE_AUDITS_COLLECTION = "interactive_audits"
SKIPPED_VALUE = "__skipped__"


# ── Carga del Cuestionario ────────────────────────────────────────────────────

_questionnaire_cache: dict | None = None


def _load_questionnaire() -> dict:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "cuestionario_base.json")
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def get_questionnaire() -> dict:
    global _questionnaire_cache
    if _questionnaire_cache is None:
        _questionnaire_cache = _load_questionnaire()
    return _questionnaire_cache


def _get_all_questions() -> list[dict]:
    """Devuelve lista plana de todas las preguntas con bloque adjunto."""
    q = get_questionnaire()
    all_qs = []
    for block in q.get("blocks", []):
        for question in block.get("questions", []):
            all_qs.append({
                **question,
                "block_id": block["id"],
                "block_label": block["label"],
            })
    return all_qs


def _get_question_by_id(question_id: str | None) -> dict | None:
    if not question_id:
        return None
    for q in _get_all_questions():
        if q["id"] == question_id:
            return q
    return None


# ── Motor de Skip Logic ───────────────────────────────────────────────────────

def _evaluate_condition(cond: dict, responses: dict) -> bool:
    """
    Evalúa una condición individual.
    Devuelve True si la condición es satisfecha (la pregunta DEBE mostrarse).

    Formato de condición:
        { "question_id": "X.Y", "op": "<operador>", "value": "<valor>" }

    Operadores soportados (case-insensitive):
        starts_with       → la respuesta empieza por <value>
        not_starts_with   → la respuesta NO empieza por <value>
        contains          → la respuesta contiene <value>
        not_contains      → la respuesta NO contiene <value>
        equals            → la respuesta es exactamente <value>
        not_equals        → la respuesta es distinta de <value>
        is_answered       → la respuesta existe y no está vacía ni skipped
        is_skipped        → la respuesta fue marcada como skipped
    """
    dep_id = cond.get("question_id")
    op = (cond.get("op") or "contains").lower().strip()
    value = (cond.get("value") or "").lower().strip()

    raw_answer = responses.get(dep_id, "")
    dep_answer = (raw_answer or "").lower().strip()

    # Si la pregunta dependiente fue omitida, esta pregunta también se omite
    if raw_answer == SKIPPED_VALUE:
        return False

    # Si la pregunta dependiente aún no ha sido respondida, mostramos la actual
    # (no podemos evaluarla aún; la condición se re-evaluará al avanzar)
    if dep_answer == "":
        return True

    if op == "starts_with":
        return dep_answer.startswith(value)
    elif op == "not_starts_with":
        return not dep_answer.startswith(value)
    elif op == "contains":
        return value in dep_answer
    elif op == "not_contains":
        return value not in dep_answer
    elif op == "equals":
        return dep_answer == value
    elif op == "not_equals":
        return dep_answer != value
    elif op == "is_answered":
        return bool(dep_answer) and dep_answer != SKIPPED_VALUE
    elif op == "is_skipped":
        return raw_answer == SKIPPED_VALUE
    else:
        logger.warning(f"Operador desconocido en skip logic: '{op}'. Condición ignorada.")
        return True


def _should_show(question: dict, responses: dict) -> bool:
    """
    Devuelve True si la pregunta debe mostrarse al usuario (todas las condiciones cumplidas).
    Si no hay condiciones, siempre se muestra.
    """
    show_if = question.get("show_if")
    if not show_if:
        return True  # Sin condiciones: siempre visible

    # AND lógico: todas las condiciones deben ser True
    return all(_evaluate_condition(cond, responses) for cond in show_if)


def _find_first_applicable_question(all_qs: list[dict], after_id: str | None, responses: dict) -> dict | None:
    """
    Itera sobre las preguntas después de `after_id` y devuelve la primera aplicable.
    Marca automáticamente como '__skipped__' las que no aplican.
    Devuelve None si no hay más preguntas.
    """
    found_start = (after_id is None)
    for q in all_qs:
        if not found_start:
            if q["id"] == after_id:
                found_start = True
            continue  # Seguir buscando el punto de partida

        # Ya estamos en las preguntas siguientes
        if _should_show(q, responses):
            return q
        else:
            # Marcar como omitida para que las condiciones futuras puedan evaluarla
            responses[q["id"]] = SKIPPED_VALUE
            logger.debug(f"Pregunta {q['id']} omitida (skip logic aplicado).")

    return None  # Fin del cuestionario


def _compute_progress(responses: dict, all_qs: list[dict]) -> dict:
    """
    Calcula el progreso de la sesión basándose en las respuestas.
    - answered: preguntas con respuesta real (no skipped)
    - skipped:  preguntas marcadas como skipped
    - total:    total de preguntas en el cuestionario
    """
    answered = sum(1 for v in responses.values() if v and v != SKIPPED_VALUE)
    skipped = sum(1 for v in responses.values() if v == SKIPPED_VALUE)
    total = len(all_qs)
    applicable = total - skipped
    percent = round((answered / applicable) * 100) if applicable > 0 else 0
    return {
        "answered": answered,
        "skipped": skipped,
        "total": total,
        "applicable": applicable,
        "percent": percent,
    }


# ── Helpers de Firestore ──────────────────────────────────────────────────────

def _get_session_ref(thread_id: str):
    return firestore_db.collection(INTERACTIVE_AUDITS_COLLECTION).document(thread_id)


# ── API Pública del Servicio ──────────────────────────────────────────────────

def create_session(uid: str) -> dict:
    """
    Crea una nueva sesión de autoauditoría en Firestore.
    Devuelve el estado inicial con la primera pregunta.
    """
    thread_id = f"interactive_{uuid.uuid4().hex}"
    all_qs = _get_all_questions()
    responses = {}

    first_question = _find_first_applicable_question(all_qs, after_id=None, responses=responses)

    doc_data = {
        "thread_id": thread_id,
        "uid": uid,
        "status": "in_progress",
        "current_block_id": first_question["block_id"] if first_question else None,
        "current_question_id": first_question["id"] if first_question else None,
        "responses": responses,
        "total_questions": len(all_qs),
        "created_at": SERVER_TIMESTAMP,
        "updated_at": SERVER_TIMESTAMP,
    }
    _get_session_ref(thread_id).set(doc_data)
    logger.info(f"Nueva sesión interactiva: {thread_id} (uid={uid})")

    return {
        "thread_id": thread_id,
        "status": "in_progress",
        "current_question": first_question,
        "progress": _compute_progress(responses, all_qs),
    }


def get_session_state(thread_id: str) -> dict | None:
    """
    Devuelve el estado completo de la sesión.
    Reconstruye la pregunta actual a partir de los datos persistidos.
    """
    doc = _get_session_ref(thread_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    all_qs = _get_all_questions()
    return {
        "thread_id": thread_id,
        "status": data.get("status", "in_progress"),
        "current_question": _get_question_by_id(data.get("current_question_id")),
        "responses": data.get("responses", {}),
        "progress": _compute_progress(data.get("responses", {}), all_qs),
    }


def submit_answer(thread_id: str, question_id: str, answer: str) -> dict:
    """
    Guarda la respuesta del usuario, evalúa el skip logic y avanza al siguiente estado.
    Las preguntas que no aplican son marcadas automáticamente como '__skipped__'.
    Devuelve: { saved, next_question, status, skipped_questions, progress }
    """
    doc = _get_session_ref(thread_id).get()
    if not doc.exists:
        raise ValueError(f"Sesión {thread_id} no encontrada.")

    data = doc.to_dict()
    responses: dict = dict(data.get("responses", {}))

    # Guardar la respuesta actual
    responses[question_id] = answer

    all_qs = _get_all_questions()

    # Encontrar la siguiente pregunta aplicable (muta `responses` marcando skips)
    skipped_before = set(k for k, v in responses.items() if v == SKIPPED_VALUE)
    next_question = _find_first_applicable_question(all_qs, after_id=question_id, responses=responses)
    skipped_after = set(k for k, v in responses.items() if v == SKIPPED_VALUE)
    newly_skipped = list(skipped_after - skipped_before)

    status = "completed" if next_question is None else "in_progress"
    next_block_id = next_question["block_id"] if next_question else None

    _get_session_ref(thread_id).update({
        "responses": responses,
        "current_question_id": next_question["id"] if next_question else None,
        "current_block_id": next_block_id,
        "status": status,
        "updated_at": SERVER_TIMESTAMP,
    })

    progress = _compute_progress(responses, all_qs)

    if newly_skipped:
        skipped_labels = [
            _get_question_by_id(qid)["text"][:80] + "..." for qid in newly_skipped
            if _get_question_by_id(qid)
        ]
        logger.info(f"Sesión {thread_id}: {len(newly_skipped)} pregunta(s) omitida(s): {newly_skipped}")
    else:
        skipped_labels = []

    return {
        "saved": True,
        "next_question": next_question,
        "status": status,
        "skipped_questions": newly_skipped,
        "skipped_labels": skipped_labels,
        "progress": progress,
    }



def _build_audit_context_string(thread_id: str) -> str:
    """
    Construye un resumen ultra-compacto de las respuestas ya dadas en la sesión.
    Usa un formato clave-valor minimalista para ahorrar miles de tokens de contexto.
    """
    state = get_session_state(thread_id)
    if not state:
        return "No hay respuestas previas en esta sesión."
    responses = state.get("responses", {})
    all_qs = _get_all_questions()

    answered = [
        (q, responses[q["id"]])
        for q in all_qs
        if responses.get(q["id"]) and responses[q["id"]] != SKIPPED_VALUE
    ]
    skipped_count = sum(1 for v in responses.values() if v == SKIPPED_VALUE)

    if not answered:
        return "Esta es la primera pregunta de la auditoría. No hay respuestas previas."

    # Representación ultra-compacta para optimizar consumo y costes de la API de Gemini
    parts = []
    for q, ans in answered:
        parts.append(f"Q[{q['id']}]:{ans}")
    
    return f"Respuestas previas ({len(answered)} respondidas, {skipped_count} omitidas):\n" + " | ".join(parts)


def _prepare_gemini_history(conversation_history: list[dict]) -> list[dict]:
    """
    Convierte el historial de mensajes del frontend al formato de Gemini chat history.
    - Mapea role 'advisor' → 'model', 'user' → 'user'
    - Elimina mensajes de tipo 'divider' y mensajes vacíos
    - Fusiona mensajes consecutivos del mismo rol (Gemini requiere alternancia)
    - El historial resultante NO incluye el mensaje actual del usuario
      (éste se envía via chat.send_message)
    """
    gemini_history: list[dict] = []

    for msg in conversation_history:
        role = msg.get("role", "")
        text = (msg.get("text") or "").strip()

        # Ignorar dividers y mensajes vacíos
        if role == "divider" or not text:
            continue

        gemini_role = "model" if role == "advisor" else "user"

        # Fusionar mensajes consecutivos del mismo rol
        if gemini_history and gemini_history[-1]["role"] == gemini_role:
            gemini_history[-1]["parts"][0] += "\n\n" + text
        else:
            gemini_history.append({"role": gemini_role, "parts": [text]})

    # El historial debe terminar en 'model' (el mensaje del usuario actual
    # se envía aparte via send_message). Si termina en 'user', eliminarlo.
    while gemini_history and gemini_history[-1]["role"] == "user":
        gemini_history.pop()

    return gemini_history


# System prompt del Auditor Experto (se rellena en get_advisor_response)
_AUDITOR_SYSTEM_PROMPT = """Eres un **Auditor y Consultor Experto en Sostenibilidad y Derechos Humanos** \
con más de 15 años de experiencia en la implementación práctica de:
- CSDDD (Corporate Sustainability Due Diligence Directive — Directiva UE 2024/1760)
- CSRD / ESRS (European Sustainability Reporting Standards)
- GRI (Global Reporting Initiative) — especialmente GRI 406, 407, 408, 409
- Convenios OIT (núm. 29, 87, 98, 138, 182) y Principios Rectores ONU sobre DDHH
- Directrices OCDE para Empresas Multinacionales
- Reglamento EUDR (deforestación)

Estás asistiendo a un profesional corporativo en una **autoauditoría estructurada de diligencia debida** \
en sostenibilidad y Derechos Humanos. La auditoría consta de {total_questions} preguntas organizadas \
en 8 bloques temáticos. El usuario va respondiendo pregunta a pregunta y puede consultarte en cualquier \
momento durante el proceso.

═══════════════════════════════════════════════════════
ESTADO ACTUAL DE LA AUDITORÍA
═══════════════════════════════════════════════════════
{audit_context}

═══════════════════════════════════════════════════════
PREGUNTA QUE SE ESTÁ RESPONDIENDO AHORA
═══════════════════════════════════════════════════════
• ID:              {question_id}
• Bloque:          {block_label}
• Tipo de respuesta: {question_type}
{options_section}
• Texto completo:  {question_text}
• Orientación:     {question_hint}

═══════════════════════════════════════════════════════
BASE DOCUMENTAL LEGAL RECUPERADA (RAG)
═══════════════════════════════════════════════════════
{legal_context}

═══════════════════════════════════════════════════════
TUS REGLAS DE COMPORTAMIENTO COMO AUDITOR EXPERTO
═══════════════════════════════════════════════════════
1. RESPONDE LA DUDA CONCRETA: Responde exactamente lo que el usuario pregunta. Sé técnico pero claro.
2. GUÍA HACIA LA RESPUESTA: Siempre orienta al usuario para que pueda responder la pregunta actual \
con precisión. Dile explícitamente qué debería contestar y por qué, basándote en su contexto.
3. INDICA LAS EVIDENCIAS: Especifica qué documentos, registros o políticas internas debería tener \
la empresa para justificar cada respuesta (Sí/No/En evaluación). Da ejemplos concretos.
4. USA EL CONTEXTO: Si el usuario hace referencia a respuestas anteriores, usa la información del \
estado actual de la auditoría para dar una respuesta coherente y personalizada.
5. MANTÉN EL HILO: Recuerda que hay un proceso de auditoría en marcha. Tras resolver la duda, \
siempre invita al usuario a dar su respuesta para avanzar al siguiente punto.
6. RIGOR NORMATIVO: Cita la normativa relevante (artículo, párrafo) cuando sea útil. \
No inventes normativa; si tienes dudas, indícalo.
7. TONO: Profesional pero accesible. Como un auditor senior que está ayudando a su cliente, \
no como un chatbot genérico.
8. IDIOMA: Responde siempre en español.
9. FORMATO: Usa Markdown con negritas, listas y separaciones cuando sea útil para la legibilidad.
"""


def get_advisor_response(
    thread_id: str,
    question_id: str,
    user_doubt: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Modo Asesor Experto con memoria de conversación completa.

    Usa Gemini 2.5 Pro en modo multi-turn (start_chat con historial) para mantener
    el hilo de la conversación durante toda la sesión de auditoría.
    Lee el estado actual de Firestore para tener contexto de las respuestas ya dadas.

    Args:
        thread_id:            ID de la sesión de auditoría
        question_id:          ID de la pregunta actual
        user_doubt:           Mensaje del usuario
        conversation_history: Historial del chat del frontend [{role, text}, ...]
    """
    # ── Datos de la pregunta actual ────────────────────────────────────────────
    question      = _get_question_by_id(question_id)
    question_text = question["text"]      if question else f"Pregunta {question_id} (no encontrada)"
    question_hint = question.get("hint", "") if question else ""
    question_type = question.get("type", "text") if question else "text"
    block_label   = question.get("block_label", "") if question else ""

    options_section = ""
    if question and question_type == "select" and question.get("options"):
        opts = "\n  ".join(f"• {o}" for o in question["options"])
        options_section = f"• Opciones posibles:\n  {opts}"
    elif question_type == "si_no":
        options_section = "• Opciones posibles: Sí | No | En evaluación"

    # ── Contexto de respuestas anteriores (Firestore) ─────────────────────────
    audit_context = _build_audit_context_string(thread_id)
    all_qs_count  = len(_get_all_questions())

    # ── Base documental legal (RAG Pinecone) ──────────────────────────────────
    rag_query     = f"{question_text} {question_hint} {block_label}"
    legal_context = retrieve_context(query=rag_query, top_k=5)
    if not legal_context:
        legal_context = "No se recuperó contexto específico de la base documental para esta pregunta."

    # ── Construir el System Prompt ────────────────────────────────────────────
    system_prompt = _AUDITOR_SYSTEM_PROMPT.format(
        total_questions=all_qs_count,
        audit_context=audit_context,
        question_id=question_id,
        block_label=block_label,
        question_type=question_type,
        options_section=options_section,
        question_text=question_text,
        question_hint=question_hint,
        legal_context=legal_context,
    )

    # ── Preparar historial multi-turn para Gemini ─────────────────────────────
    gemini_history = _prepare_gemini_history(conversation_history or [])
    logger.debug(
        f"Asesor {thread_id}/{question_id}: historial con {len(gemini_history)} turnos previos"
    )

    # ── Llamada a Gemini con start_chat ───────────────────────────────────────
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=genai.GenerationConfig(temperature=0.25, max_output_tokens=1500),
            system_instruction=system_prompt,
        )
        # start_chat inicializa la sesión con todo el historial previo
        chat          = model.start_chat(history=gemini_history)
        api_response  = chat.send_message(user_doubt)
        advisor_text  = api_response.text.strip()
    except Exception as e:
        logger.error(f"Error Modo Asesor {thread_id}/{question_id}: {e}", exc_info=True)
        raise

    return {
        "advisor_response": advisor_text,
        "question_id": question_id,
    }

