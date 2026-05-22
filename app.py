# app.py
import os
import time
import json
import uuid
import datetime
from flask import request, jsonify, abort

# --- Configuración base y clientes externos ---
from src.config import app, logger, firestore_db

# --- Servicios ---
from src.empirical_audit_service import run_empirical_audit_async
from src.chat_service import (
    handle_chat_auditor,
    handle_chat_advisor,
    get_recent_conversations,
    get_conversation_thread,
)
from src.interactive_audit_service import (
    create_session,
    get_session_state,
    submit_answer,
    get_advisor_response,
    get_questionnaire,
)
import threading
import tempfile
import werkzeug.utils

# --- Firebase Admin / Firestore ---
import firebase_admin
from firebase_admin import credentials, auth as fb_auth, firestore

# Firestore server timestamps
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# --- CORS y Rate Limiting ---
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# =============================================================================
# 1) CORS y Rate Limiting
# =============================================================================
_allowed_origins_str = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "https://recava-buscador.web.app,https://recava-buscador.firebaseapp.com,"
    "https://recava-buscador-panel.web.app,http://localhost:3000,http://localhost:8000,"
    "http://localhost:8080"
)
_allowed_origins = [o.strip() for o in _allowed_origins_str.split(",") if o.strip()]

if not _allowed_origins or "*" in _allowed_origins:
    _allowed_origins = [
        "https://recava-buscador.web.app",
        "https://recava-buscador-panel.web.app",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    logger.warning(f"CORS_ORIGINS no definida o '*', usando defaults seguros: {_allowed_origins}")

CORS(
    app,
    origins=_allowed_origins,
    supports_credentials=True,
    methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["X-Request-Id"],
    max_age=86400,
)
logger.info(f"CORS configured for origins: {_allowed_origins}")

limiter = Limiter(get_remote_address, app=app, default_limits=["120/minute"])


# =============================================================================
# 2) Utilidades de respuesta y logging
# =============================================================================
def ok(data, **meta):
    resp = {"ok": True, "data": data}
    if meta:
        resp["meta"] = meta
    return jsonify(resp), 200


def fail(message, status=400, **details):
    return jsonify({"ok": False, "error": {"message": message, **details}}), status


@app.before_request
def _req_start():
    request._id = uuid.uuid4().hex[:12]
    request._t0 = time.time()
    logger.info(json.dumps(
        {"evt": "request_start", "id": request._id, "path": request.path, "method": request.method}
    ))


@app.after_request
def _req_end(resp):
    dur_ms = int((time.time() - getattr(request, "_t0", time.time())) * 1000)
    resp.headers["X-Request-Id"] = getattr(request, "_id", "")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    logger.info(json.dumps({"evt": "request_end", "id": request._id, "status": resp.status_code, "ms": dur_ms}))
    return resp


# =============================================================================
# 3) Autenticación y helpers
# =============================================================================
def require_firebase_user_or_403():
    """Verifica ID token Firebase; exige email verificado."""
    if os.getenv("DISABLE_AUTH_FOR_LOCAL", "false").lower() == "true":
        return {"uid": "local_dev_user", "email": "local@dev.com", "email_verified": True}

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        abort(401, description="Falta Authorization Bearer token")
    id_token = auth_header.split(" ", 1)[1]
    try:
        decoded = fb_auth.verify_id_token(id_token)
    except Exception as e:
        logger.warning(f"Auth: token inválido: {e}")
        abort(401, description="Token inválido")
    if not decoded.get("email_verified", False):
        abort(403, description="Email no verificado")
    return decoded


def _iso_utc(ts):
    """Normaliza a ISO-8601 UTC."""
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        return ts.astimezone(datetime.timezone.utc).isoformat()
    try:
        return ts.isoformat()
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(str(ts)).astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        return str(ts)


# =============================================================================
# 4) Endpoints de Chat (Modo Auditor y Modo Asesor) – Restaurados con Gemini
# =============================================================================

@app.route("/chat_auditor", methods=["POST"])
@limiter.limit("30/minute")
def chat_with_main_audit_orchestrator():
    """
    Modo Auditor: conversación guiada de auditoría de diligencia debida (Gemini + Pinecone RAG).
    Reemplaza la integración original con OpenAI.
    """
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    thread_id = data.get("thread_id")

    if not user_message:
        return fail("El campo 'message' es obligatorio.", status=400)

    try:
        result = handle_chat_auditor(user_message, thread_id, uid)
        return ok(result)
    except Exception as e:
        logger.error(f"/chat_auditor error: {e}", exc_info=True)
        return fail(f"Error interno del servidor: {str(e)}", status=500)


@app.route("/chat_assistant", methods=["POST"])
@limiter.limit("30/minute")
def chat_with_sustainability_expert():
    """
    Modo Asesor: consultas libres de sostenibilidad (Gemini + Pinecone RAG).
    Reemplaza la integración original con OpenAI.
    """
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    thread_id = data.get("thread_id")

    if not user_message:
        return fail("El campo 'message' es obligatorio.", status=400)

    try:
        result = handle_chat_advisor(user_message, thread_id, uid)
        return ok(result)
    except Exception as e:
        logger.error(f"/chat_assistant error: {e}", exc_info=True)
        return fail(f"Error interno del servidor: {str(e)}", status=500)


# =============================================================================
# 5) Endpoints de Historial de Conversaciones
# =============================================================================

@app.route("/chat_history/recents", methods=["GET"])
def get_chat_history_recents():
    """
    Devuelve las últimas conversaciones del usuario autenticado.
    Usado por el chatbot para mostrar el historial en la pantalla de selección.
    """
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")
    try:
        limit = min(int(request.args.get("limit", 5)), 20)
    except ValueError:
        limit = 5

    try:
        conversations = get_recent_conversations(uid, limit)
        return ok({"conversations": conversations})
    except Exception as e:
        logger.error(f"/chat_history/recents error uid={uid}: {e}", exc_info=True)
        return fail(f"Error al obtener historial: {str(e)}", status=500)


@app.route("/chat_history/thread/<thread_id>", methods=["GET"])
def get_chat_history_thread(thread_id):
    """
    Devuelve el hilo completo de una conversación (para reanudar desde el historial).
    """
    decoded_user = require_firebase_user_or_403()
    try:
        thread = get_conversation_thread(thread_id)
        if not thread:
            return fail("Conversación no encontrada.", status=404)
        return ok(thread)
    except Exception as e:
        logger.error(f"/chat_history/thread/{thread_id} error: {e}", exc_info=True)
        return fail(f"Error al obtener conversación: {str(e)}", status=500)


# =============================================================================
# 6) Endpoints de Progreso de Auditoría (para el panel lateral del chatbot)
# =============================================================================

AUDIT_PROGRESS_COLLECTION = "audit_progress"


@app.route("/audit_progress/<thread_id>", methods=["GET"])
def get_audit_progress(thread_id):
    """
    Devuelve el progreso por bloques de auditoría para una conversación.
    El chatbot lo usa para renderizar el panel de progreso lateral.
    """
    require_firebase_user_or_403()
    try:
        doc = firestore_db.collection(AUDIT_PROGRESS_COLLECTION).document(thread_id).get()
        if not doc.exists:
            # Devuelve estado vacío (estado inicial) si no existe
            return ok(_build_empty_audit_progress(thread_id))
        data = doc.to_dict()
        return ok(data)
    except Exception as e:
        logger.error(f"/audit_progress/{thread_id} GET error: {e}", exc_info=True)
        return fail(f"Error al obtener progreso: {str(e)}", status=500)


@app.route("/audit_progress/<thread_id>", methods=["POST"])
def update_audit_progress(thread_id):
    """
    Actualiza el estado de un bloque de auditoría.
    Payload: { block_id, status ('completed'|'in_progress'), summary (opcional) }
    """
    require_firebase_user_or_403()
    body = request.get_json(silent=True) or {}
    block_id = body.get("block_id")
    status = body.get("status")
    summary = body.get("summary", "")

    if not block_id or not status:
        return fail("Los campos 'block_id' y 'status' son obligatorios.", status=400)
    if status not in ("completed", "in_progress", "pending"):
        return fail("El campo 'status' debe ser 'completed', 'in_progress' o 'pending'.", status=400)

    try:
        ref = firestore_db.collection(AUDIT_PROGRESS_COLLECTION).document(thread_id)
        doc = ref.get()

        if not doc.exists:
            progress_data = _build_empty_audit_progress(thread_id)
            ref.set(progress_data)
            doc_data = progress_data
        else:
            doc_data = doc.to_dict()

        # Actualizar el bloque específico
        blocks = doc_data.get("blocks", [])
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        block_found = False
        for block in blocks:
            if block["id"] == block_id:
                block["status"] = status
                if summary:
                    block["summary"] = summary
                if status == "completed":
                    block["completed_at"] = now_iso
                block["updated_at"] = now_iso
                block_found = True
                break

        if not block_found:
            return fail(f"Bloque '{block_id}' no encontrado.", status=404)

        # Recalcular métricas
        completed_count = sum(1 for b in blocks if b["status"] == "completed")
        total_blocks = len(blocks)
        percent = round((completed_count / total_blocks) * 100) if total_blocks else 0

        # Determinar bloque activo (el siguiente al último completado)
        active_block_id = next(
            (b["id"] for b in blocks if b["status"] != "completed"), blocks[-1]["id"] if blocks else None
        )

        updated_data = {
            "blocks": blocks,
            "completed_count": completed_count,
            "total_blocks": total_blocks,
            "percent": percent,
            "active_block_id": active_block_id,
            "updated_at": now_iso,
        }
        ref.update(updated_data)
        doc_data.update(updated_data)
        return ok(doc_data)

    except Exception as e:
        logger.error(f"/audit_progress/{thread_id} POST error: {e}", exc_info=True)
        return fail(f"Error al actualizar progreso: {str(e)}", status=500)


def _build_empty_audit_progress(thread_id: str) -> dict:
    """Construye el estado vacío de progreso con los 8 bloques definidos."""
    blocks_definition = [
        {"id": "block_1", "label": "1. Contexto y Alcance"},
        {"id": "block_2", "label": "2. Información Corporativa"},
        {"id": "block_3", "label": "3. Cadena de Valor"},
        {"id": "block_4", "label": "4. Gobernanza y Compliance"},
        {"id": "block_5", "label": "5. Impacto Ambiental"},
        {"id": "block_6", "label": "6. Personas y Derechos Humanos"},
        {"id": "block_7", "label": "7. Riesgos y Controles"},
        {"id": "block_8", "label": "8. Conclusiones y Roadmap"},
    ]
    blocks = [
        {
            "id": b["id"],
            "label": b["label"],
            "status": "pending",
            "summary": None,
            "completed_at": None,
            "updated_at": None,
        }
        for b in blocks_definition
    ]
    return {
        "thread_id": thread_id,
        "active_block_id": "block_1",
        "completed_count": 0,
        "total_blocks": len(blocks),
        "percent": 0,
        "blocks": blocks,
    }


# =============================================================================
# 7) Endpoints de Auditoría Empírica (NEIS S1 - PDF asíncrono)
# =============================================================================

@app.route("/api/audit/empirical", methods=["POST"])
def start_empirical_audit():
    """Inicia una auditoría empírica asíncrona sobre un documento (PDF adjunto)."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    if "file" not in request.files:
        return fail("No se encontró ningún archivo", status=400)

    file = request.files["file"]
    if file.filename == "":
        return fail("Archivo vacío", status=400)

    temp_dir = tempfile.mkdtemp()
    filename = werkzeug.utils.secure_filename(file.filename) or "document.pdf"
    file_path = os.path.join(temp_dir, filename)
    file.save(file_path)

    thread_id = f"empirical_{uuid.uuid4().hex}"

    threading.Thread(
        target=run_empirical_audit_async,
        args=(thread_id, file_path, uid),
    ).start()

    return jsonify({"ok": True, "message": "Empirical audit started", "thread_id": thread_id}), 202


@app.route("/api/audit/empirical/<thread_id>", methods=["GET"])
def get_empirical_audit(thread_id):
    """Lee el estado y resultados de una auditoría empírica por su thread_id."""
    try:
        doc_snap = firestore_db.collection("empirical_audits").document(thread_id).get()
        if not doc_snap.exists:
            return fail("Auditoría no encontrada", status=404)
        data = doc_snap.to_dict()
        for key in ("created_at", "updated_at", "completed_at"):
            if key in data and data[key] is not None:
                data[key] = _iso_utc(data[key])
        return ok(data)
    except Exception as e:
        logger.error(f"Error leyendo auditoría {thread_id}: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)


@app.route("/api/audit/empirical/<thread_id>/feedback", methods=["PATCH"])
def patch_empirical_feedback(thread_id):
    """Actualiza la validación humana de un indicador."""
    body = request.get_json(silent=True) or {}
    indicator_id = body.get("indicator_id")
    human_validation = body.get("human_validation")
    if indicator_id is None:
        return fail("indicator_id requerido", status=400)
    try:
        firestore_db.collection("empirical_audits").document(thread_id).update(
            {f"results.{indicator_id}.human_validation": human_validation}
        )
        return ok({"updated": True})
    except Exception as e:
        logger.error(f"Error actualizando feedback {thread_id}/{indicator_id}: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)


# =============================================================================
# 8) Endpoints de Auditoría Interactiva (Nuevo módulo CSDDD)
# =============================================================================

@app.route("/api/audit/interactive/start", methods=["POST"])
def start_interactive_audit():
    """
    Inicia una nueva sesión de autoauditoría interactiva.
    Crea el documento en Firestore y devuelve la primera pregunta.
    """
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")
    try:
        session = create_session(uid)
        return ok(session), 201
    except Exception as e:
        logger.error(f"/api/audit/interactive/start error uid={uid}: {e}", exc_info=True)
        return fail(f"Error al iniciar sesión: {str(e)}", status=500)


@app.route("/api/audit/interactive/<thread_id>/state", methods=["GET"])
def get_interactive_audit_state(thread_id):
    """
    Devuelve el estado completo de la sesión de autoauditoría interactiva.
    Útil para recargas de página o reconexiones.
    """
    require_firebase_user_or_403()
    try:
        state = get_session_state(thread_id)
        if not state:
            return fail("Sesión no encontrada.", status=404)
        return ok(state)
    except Exception as e:
        logger.error(f"/api/audit/interactive/{thread_id}/state error: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)


@app.route("/api/audit/interactive/<thread_id>/submit", methods=["POST"])
def submit_interactive_answer(thread_id):
    """
    Registra la respuesta del usuario a la pregunta actual y avanza al estado siguiente.
    Payload: { question_id, answer }
    """
    require_firebase_user_or_403()
    body = request.get_json(silent=True) or {}
    question_id = body.get("question_id")
    answer = body.get("answer", "").strip()

    if not question_id:
        return fail("El campo 'question_id' es obligatorio.", status=400)
    if not answer:
        return fail("El campo 'answer' no puede estar vacío.", status=400)

    try:
        result = submit_answer(thread_id, question_id, answer)
        return ok(result)
    except ValueError as e:
        return fail(str(e), status=404)
    except Exception as e:
        logger.error(f"/api/audit/interactive/{thread_id}/submit error: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)


@app.route("/api/audit/interactive/<thread_id>/consult-advisor", methods=["POST"])
@limiter.limit("20/minute")
def consult_interactive_advisor(thread_id):
    """
    Modo Asesor Experto con memoria de conversación multi-turn.
    Usa Gemini 2.5 Pro con historial completo (start_chat) + Pinecone RAG.

    Payload:
        { question_id, user_doubt, history: [{role, text}, ...] }

    El campo `history` contiene el historial completo del chat del frontend
    (incluyendo mensajes anteriores de otras preguntas). Se usa para mantener
    el hilo de la conversación durante toda la sesión de auditoría.
    """
    require_firebase_user_or_403()
    body = request.get_json(silent=True) or {}
    question_id          = body.get("question_id")
    user_doubt           = body.get("user_doubt", "").strip()
    conversation_history = body.get("history") or []   # lista [{role, text}]

    if not question_id:
        return fail("El campo 'question_id' es obligatorio.", status=400)
    if not user_doubt:
        return fail("El campo 'user_doubt' no puede estar vacío.", status=400)

    # Limitar el historial a los últimos 30 mensajes para controlar tokens
    if len(conversation_history) > 30:
        conversation_history = conversation_history[-30:]

    try:
        result = get_advisor_response(
            thread_id=thread_id,
            question_id=question_id,
            user_doubt=user_doubt,
            conversation_history=conversation_history,
        )
        return ok(result)
    except Exception as e:
        logger.error(f"/api/audit/interactive/{thread_id}/consult-advisor error: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)



@app.route("/api/audit/interactive/<thread_id>/export", methods=["GET"])
def export_interactive_audit(thread_id):
    """
    Devuelve el informe completo de la sesión para visualización y exportación.
    Incluye TODAS las preguntas del cuestionario con su estado:
      - answered:        respondida con un valor real
      - not_applicable:  omitida por skip logic
      - pending:         aún no respondida
    Disponible tanto durante la auditoría (informe parcial) como al finalizar.
    """
    require_firebase_user_or_403()
    try:
        state = get_session_state(thread_id)
        if not state:
            return fail("Sesión no encontrada.", status=404)

        questionnaire = get_questionnaire()
        responses = state.get("responses", {})
        SKIPPED = "__skipped__"

        blocks_report = []
        total_gaps = 0
        total_answered = 0
        total_not_applicable = 0

        for block in questionnaire.get("blocks", []):
            block_qs = []
            block_gaps = 0
            block_answered = 0

            for q in block.get("questions", []):
                qid = q["id"]
                raw = responses.get(qid)

                if raw is None:
                    q_status = "pending"
                    answer = None
                    compliance = None
                elif raw == SKIPPED:
                    q_status = "not_applicable"
                    answer = None
                    compliance = "not_applicable"
                    total_not_applicable += 1
                else:
                    q_status = "answered"
                    answer = raw
                    block_answered += 1
                    total_answered += 1
                    # Señal de cumplimiento para preguntas Sí/No
                    if q.get("type") == "si_no":
                        al = answer.lower().strip()
                        if al.startswith("s"):
                            compliance = "compliant"
                        elif al.startswith("n"):
                            compliance = "gap"
                            block_gaps += 1
                            total_gaps += 1
                        else:
                            compliance = "in_progress"   # "en evaluación"
                    else:
                        compliance = "informational"

                block_qs.append({
                    "id": qid,
                    "text": q.get("text", ""),
                    "type": q.get("type", "text"),
                    "hint": q.get("hint", ""),
                    "options": q.get("options"),
                    "status": q_status,
                    "answer": answer,
                    "compliance": compliance,
                })

            # Calcular estado del bloque completo
            block_total = len(block_qs)
            block_na = sum(1 for bq in block_qs if bq["status"] == "not_applicable")
            block_pending = sum(1 for bq in block_qs if bq["status"] == "pending")
            block_applicable = block_total - block_na

            if block_pending == 0 and block_applicable > 0:
                block_completion = "complete"
            elif block_answered > 0:
                block_completion = "partial"
            else:
                block_completion = "pending"

            blocks_report.append({
                "id": block["id"],
                "label": block["label"],
                "phase_ref": block.get("phase_ref", ""),
                "completion": block_completion,
                "questions": block_qs,
                "stats": {
                    "total": block_total,
                    "answered": block_answered,
                    "not_applicable": block_na,
                    "pending": block_pending,
                    "applicable": block_applicable,
                    "gaps": block_gaps,
                },
            })

        # Resumen ejecutivo de cumplimiento
        progress = state.get("progress", {})
        applicable = progress.get("applicable", total_answered)
        compliance_pct = round((total_answered - total_gaps) / applicable * 100) if applicable > 0 else 0

        if compliance_pct >= 80:
            compliance_level = "Alto"
        elif compliance_pct >= 50:
            compliance_level = "Medio"
        else:
            compliance_level = "Bajo"

        # Preguntas con brecha (answer = No) para destacar en el informe
        critical_gaps = [
            {"block": bq_block["label"], "question_id": bq["id"], "text": bq["text"]}
            for bq_block in blocks_report
            for bq in bq_block["questions"]
            if bq["compliance"] == "gap"
        ]

        return ok({
            "thread_id": thread_id,
            "status": state.get("status"),
            "progress": progress,
            "summary": {
                "total_answered": total_answered,
                "total_not_applicable": total_not_applicable,
                "total_gaps": total_gaps,
                "compliance_pct": compliance_pct,
                "compliance_level": compliance_level,
                "critical_gaps": critical_gaps[:10],   # top 10 gaps
            },
            "blocks": blocks_report,
        })
    except Exception as e:
        logger.error(f"/api/audit/interactive/{thread_id}/export error: {e}", exc_info=True)
        return fail(f"Error interno: {str(e)}", status=500)



# =============================================================================
# 9) Health Checks
# =============================================================================

@app.route("/health", methods=["GET"])
def health_check():
    """Comprobación básica de que el proceso está vivo."""
    return ok({"status": "healthy"})


@app.route("/readyz", methods=["GET"])
def readyz():
    """Comprobación de dependencias: Firestore."""
    try:
        firestore_db.collection("_ready").document("ping").get()
        return ok({"status": "ready"})
    except Exception as e:
        return fail("degraded", status=503, details=str(e))


# =============================================================================
# 10) Entry point
# =============================================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
