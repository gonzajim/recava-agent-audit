# app.py
import os
import time
import json
import datetime
from flask import request, jsonify, abort

# --- 1. Importaciones de la configuración y servicios ---
from src.config import app, logger, client, ORCHESTRATOR_ASSISTANT_ID, ASISTENTE_ID
# --- CORRECCIÓN: Usar el nuevo nombre de la función ---
from src.persistence_service import persist_conversation_turn
from src.openai_service import execute_invoke_sustainability_expert, process_assistant_message_without_citations
from src.bigquery_service import fetch_recent_conversations_for_user, fetch_conversation_thread

# --- 1.b Autenticación Firebase: validar ID token y email verificado ---
# reemplaza tu bloque de init firebase_admin por:
import firebase_admin
from firebase_admin import credentials, auth as fb_auth, firestore

if not firebase_admin._apps:
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
        # En emulador NO hace falta credencial
        firebase_admin.initialize_app()
    else:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            logger.info("Firebase Admin: using application default credentials.")
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)

firestore_db = firestore.client()


def require_firebase_user_or_403():
    """Verifica el ID token de Firebase y exige email verificado.
    - 401 si falta o es inválido
    - 403 si email_verified == False
    Devuelve el dict decodificado del token (uid, email, claims, etc.)."""
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

    # Opcional: logs mínimos
    logger.debug(f"Auth OK uid={decoded.get('uid')} email={decoded.get('email')} verified={decoded.get('email_verified')}")
    return decoded


def _build_user_metadata(decoded_user: dict) -> dict:
    """Extrae campos relevantes del token verificado para persistencia."""
    user_id = decoded_user.get("user_id") or decoded_user.get("uid")
    return {
        "user_id": user_id,
        "uid": decoded_user.get("uid"),
        "email": decoded_user.get("email"),
        "email_verified": decoded_user.get("email_verified"),
    }


AUDIT_BLOCKS = [
    {"id": "block_1", "label": "1. Contexto y Alcance"},
    {"id": "block_2", "label": "2. Información Corporativa"},
    {"id": "block_3", "label": "3. Cadena de Valor"},
    {"id": "block_4", "label": "4. Gobernanza y Compliance"},
    {"id": "block_5", "label": "5. Impacto Ambiental"},
    {"id": "block_6", "label": "6. Personas y Derechos Humanos"},
    {"id": "block_7", "label": "7. Riesgos y Controles"},
    {"id": "block_8", "label": "8. Conclusiones y Roadmap"},
]
AUDIT_BLOCK_IDS = {block["id"] for block in AUDIT_BLOCKS}


def _normalize_timestamp_iso(value):
    """Convierte un timestamp (datetime/None/str) a ISO 8601 en UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc).isoformat()
    return str(value)


def _default_audit_progress_state(uid=None):
    return {
        "uid": uid,
        "blocks": {},
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }


def _build_audit_progress_payload(thread_id, uid, doc_data):
    data = doc_data or {}
    blocks_state = data.get("blocks") or {}
    blocks_payload = []
    completed = 0
    active_block_id = None

    for block in AUDIT_BLOCKS:
        stored = blocks_state.get(block["id"], {})
        status = stored.get("status", "pending")
        if status == "completed":
            completed += 1
        elif active_block_id is None:
            active_block_id = block["id"]

        blocks_payload.append({
            "id": block["id"],
            "label": block["label"],
            "status": status,
            "summary": stored.get("summary"),
            "completed_at": _normalize_timestamp_iso(stored.get("completed_at")),
            "updated_at": _normalize_timestamp_iso(stored.get("updated_at")),
        })

    if active_block_id is None and AUDIT_BLOCKS:
        active_block_id = AUDIT_BLOCKS[-1]["id"]

    total = len(AUDIT_BLOCKS)
    percent = int(round((completed / total) * 100)) if total else 0

    return {
        "thread_id": thread_id,
        "uid": uid,
        "blocks": blocks_payload,
        "active_block_id": active_block_id,
        "completed_count": completed,
        "total_blocks": total,
        "percent": percent,
        "updated_at": _normalize_timestamp_iso(data.get("updated_at")),
    }


def _get_audit_progress_doc(thread_id: str):
    return firestore_db.collection("audit_progress").document(thread_id)


# --- 2. Endpoints de la API ---

@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    # --- Nuevo: exigir auth y email verificado ---
    decoded_user = require_firebase_user_or_403()
    persistence_metadata = _build_user_metadata(decoded_user)

    endpoint_name, data = "/chat_auditor", request.json or {}
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        if not user_message:
            return jsonify({"error": "Invalid request: message is required."}), 400
        if not thread_id:
            thread_id = client.beta.threads.create().id

        # Log extra con uid/email (no cambiamos persistencia para no romper esquema)
        logger.info(f"{endpoint_name}: uid={decoded_user.get('uid')} email={decoded_user.get('email')} thread_id={thread_id}")

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ORCHESTRATOR_ASSISTANT_ID)
        run_id = run.id

        while run.status in ['queued', 'in_progress', 'requires_action']:
            time.sleep(1)
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            logger.info(f"{endpoint_name}: Polling Run {run.id}, Status: {run.status}")

            if run.status == 'requires_action':
                tool_outputs = []
                for tc in run.required_action.submit_tool_outputs.tool_calls:
                    if tc.function.name == "invoke_sustainability_expert":
                        args = json.loads(tc.function.arguments)
                        query = args.get("query")
                        output = execute_invoke_sustainability_expert(query, thread_id)
                        tool_outputs.append({"tool_call_id": tc.id, "output": output})
                if tool_outputs:
                    client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs)

        run_status = run.status
        if run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc')
            response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)
            # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
            persist_conversation_turn(
                thread_id, user_message, response_text, endpoint_name,
                run_id=run.id, assistant_name="MainAuditOrchestrator", **persistence_metadata
            )
            return jsonify({
                "response": response_text,
                "thread_id": thread_id,
                "run_id": run.id,
                "run_status": run_status
            }), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
        persist_conversation_turn(
            thread_id, user_message, f"API Error: {e}", endpoint_name,
            run_id=run_id, assistant_name="Exception", **persistence_metadata
        )
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500


@app.route('/chat_assistant', methods=['POST'])
def chat_with_sustainability_expert():
    # --- Nuevo: exigir auth y email verificado ---
    decoded_user = require_firebase_user_or_403()
    persistence_metadata = _build_user_metadata(decoded_user)

    endpoint_name, data = "/chat_assistant", request.json or {}
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        if not user_message:
            return jsonify({"error": "Invalid request: message is required."}), 400
        if not thread_id:
            thread_id = client.beta.threads.create().id

        logger.info(f"{endpoint_name}: uid={decoded_user.get('uid')} email={decoded_user.get('email')} thread_id={thread_id}")

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)
        run = client.beta.threads.runs.create_and_poll(thread_id=thread_id, assistant_id=ASISTENTE_ID, timeout=180.0)
        run_id, run_status = run.id, run.status

        if run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc')
            response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)
            # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
            persist_conversation_turn(
                thread_id, user_message, response_text, endpoint_name,
                run_id=run.id, assistant_name="SustainabilityExpert", **persistence_metadata
            )
            return jsonify({
                "response": response_text,
                "thread_id": thread_id,
                "run_id": run.id,
                "run_status": run_status
            }), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
        persist_conversation_turn(
            thread_id, user_message, f"API Error: {e}", endpoint_name,
            run_id=run_id, assistant_name="Exception", **persistence_metadata
        )
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500


@app.route('/chat_history/recents', methods=['GET'])
def get_recent_chat_history():
    """Devuelve las ultimas conversaciones de un usuario autenticado."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    try:
        limit = request.args.get("limit", default=5, type=int)
    except (TypeError, ValueError):
        limit = 5

    try:
        conversations = fetch_recent_conversations_for_user(uid=uid, limit=limit)
        return jsonify({"conversations": conversations}), 200
    except ValueError as err:
        abort(400, description=str(err))
    except Exception as exc:
        logger.error("Failed to fetch recent chat history for uid=%s: %s", uid, exc, exc_info=True)
        return jsonify({"error": "No se pudo obtener el historial reciente."}), 500


@app.route('/chat_history/thread/<thread_id>', methods=['GET'])
def get_chat_history_thread(thread_id: str):
    """Devuelve todos los mensajes de una conversacion concreta si pertenece al usuario."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    try:
        conversation = fetch_conversation_thread(uid=uid, thread_id=thread_id)
        return jsonify(conversation), 200
    except ValueError as err:
        abort(400, description=str(err))
    except Exception as exc:
        logger.error("Failed to fetch chat thread %s for uid=%s: %s", thread_id, uid, exc, exc_info=True)
        return jsonify({"error": "No se pudo obtener la conversacion solicitada."}), 500


@app.route('/audit_progress/<thread_id>', methods=['GET'])
def get_audit_progress(thread_id: str):
    """Devuelve el estado de progreso de auditoria para un hilo concreto."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    try:
        doc = _get_audit_progress_doc(thread_id).get()
        if doc.exists:
            data = doc.to_dict() or {}
            stored_uid = data.get("uid")
            if stored_uid and stored_uid != uid:
                abort(403, description="No tienes acceso a este progreso de auditoria.")
        else:
            data = _default_audit_progress_state(uid=uid)
    except Exception as exc:
        logger.error("Failed to fetch audit progress for thread=%s: %s", thread_id, exc, exc_info=True)
        return jsonify({"error": "No se pudo obtener el progreso de auditoria."}), 500

    payload = _build_audit_progress_payload(thread_id, uid, data)
    return jsonify(payload), 200


@app.route('/audit_progress/<thread_id>', methods=['POST'])
def update_audit_progress(thread_id: str):
    """Actualiza el estado de un bloque de auditoria para un hilo."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    body = request.get_json(silent=True) or {}
    block_id = body.get("block_id")
    status = (body.get("status") or "completed").strip().lower()
    summary = body.get("summary")

    if not block_id or block_id not in AUDIT_BLOCK_IDS:
        abort(400, description="block_id invalido. Debe corresponderse con un bloque del proceso.")
    if status not in {"pending", "completed"}:
        abort(400, description="status invalido. Valores permitidos: 'pending' o 'completed'.")

    doc_ref = _get_audit_progress_doc(thread_id)
    try:
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            stored_uid = data.get("uid")
            if stored_uid and stored_uid != uid:
                abort(403, description="No tienes acceso a este progreso de auditoria.")
        else:
            data = _default_audit_progress_state(uid=uid)

        now_iso = datetime.datetime.utcnow().isoformat()
        block_state = data.setdefault("blocks", {}).get(block_id, {})

        block_state["status"] = status
        block_state["updated_at"] = now_iso
        if summary is not None:
            block_state["summary"] = summary

        block_state["completed_at"] = now_iso if status == "completed" else None

        data["blocks"][block_id] = block_state
        data["uid"] = uid
        data["updated_at"] = now_iso

        doc_ref.set(data)
    except Exception as exc:
        logger.error("Failed to update audit progress thread=%s block=%s: %s", thread_id, block_id, exc, exc_info=True)
        return jsonify({"error": "No se pudo actualizar el progreso de auditoria."}), 500

    payload = _build_audit_progress_payload(thread_id, uid, data)
    return jsonify(payload), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint para comprobaciones de estado del servicio."""
    return jsonify({"status": "healthy"}), 200


# --- 3. Punto de Entrada de la Aplicación ---
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get("PORT", 8080)),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    )
