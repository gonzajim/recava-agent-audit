# app.py
import os
import time
import json
import uuid
import datetime
from flask import request, jsonify, abort
from openai import APITimeoutError

# --- Configuración base y clientes externos ---
from src.config import app, logger, client, ORCHESTRATOR_ASSISTANT_ID, ASISTENTE_ID

# Persistencia / OpenAI / BigQuery (tuyos)
from src.persistence_service import persist_conversation_turn
from src.openai_service import (
    execute_invoke_sustainability_expert,
    process_assistant_message_without_citations,
)
from src.bigquery_service import (
    fetch_recent_conversations_for_user,
    fetch_conversation_thread,
)

# --- Firebase Admin / Firestore ---
import firebase_admin
from firebase_admin import credentials, auth as fb_auth, firestore

# Firestore server timestamps y decoradores transaccionales
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# --- CORS (opcional) y Rate Limiting ---
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# =============================================================================
# 0) Inicialización de Firebase Admin
# =============================================================================
if not firebase_admin._apps:
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
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

# =============================================================================
# 1) CORS y Rate Limiting
# =============================================================================
# Orígenes permitidos: Lee desde variable de entorno o usa defaults seguros
_allowed_origins_str = os.getenv("CORS_ORIGINS", "https://recava-auditor-dev.web.app,https://recava-auditor.web.app,http://localhost:8000")
_allowed_origins = [origin.strip() for origin in _allowed_origins_str.split(",") if origin.strip()]

# Si no se define nada específico, permitir solo los dominios de Firebase y localhost
if not _allowed_origins or "*" in _allowed_origins:
    _allowed_origins = [
        "https://recava-auditor-dev.web.app", # Tu entorno de dev
        "https://recava-auditor.web.app",   # Tu (futuro) entorno de prod
        "http://localhost:8000"           # Para pruebas locales
    ]
    logger.warning(f"CORS_ORIGINS no definida o '*', usando defaults seguros: {_allowed_origins}")

CORS(
    app,
    # Permite solo los orígenes especificados
    origins=_allowed_origins,
    # Permite credenciales si las usaras (aunque ahora usas Authorization header)
    supports_credentials=True,
    # Métodos y Headers necesarios para tu app
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    # Headers que el frontend podrá leer
    expose_headers=["X-Request-Id"],
    # Tiempo que el navegador puede cachear la respuesta OPTIONS (preflight)
    max_age=86400 # 1 día
)
logger.info(f"CORS configured for origins: {_allowed_origins}")

# Rate Limiting (sin cambios)
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
    # No logueamos el cuerpo (datos sensibles); solo metadatos
    logger.info(
        json.dumps(
            {"evt": "request_start", "id": request._id, "path": request.path, "method": request.method}
        )
    )


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
    """Verifica ID token Firebase; exige email verificado. 401 si falta/incorrecto, 403 si no verificado."""
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
    logger.debug(
        f"Auth OK uid={decoded.get('uid')} email={decoded.get('email')} verified={decoded.get('email_verified')}"
    )
    return decoded


def _build_user_metadata(decoded_user: dict) -> dict:
    user_id = decoded_user.get("user_id") or decoded_user.get("uid")
    return {
        "user_id": user_id,
        "uid": decoded_user.get("uid"),
        "email": decoded_user.get("email"),
        "email_verified": decoded_user.get("email_verified"),
    }


def _iso_utc(ts):
    """Normaliza a ISO-8601 UTC (acepta datetime/FirestoreTimestamp/str/None)."""
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        return ts.astimezone(datetime.timezone.utc).isoformat()
    # Firestore Timestamp tiene .isoformat() tras conversión a datetime por SDK en responses
    try:
        return ts.isoformat()  # si ya es datetime-like
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(str(ts)).astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        return str(ts)


# =============================================================================
# 4) Bloques y progreso de auditoría
# =============================================================================
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
AUDIT_BLOCK_IDS = {b["id"] for b in AUDIT_BLOCKS}
VALID_STATUSES = {"pending", "in_progress", "completed"}


def _default_audit_progress_state(uid=None):
    return {"uid": uid, "blocks": {}, "updated_at": SERVER_TIMESTAMP}


def _get_audit_progress_doc(thread_id: str):
    return firestore_db.collection("audit_progress").document(thread_id)


def _build_audit_progress_payload(thread_id, uid, doc_data):
    data = doc_data or {}
    blocks_state = data.get("blocks") or {}
    blocks_payload = []
    completed = 0
    active_block_id = None
    first_pending = None

    for block in AUDIT_BLOCKS:
        stored = blocks_state.get(block["id"], {}) or {}
        status = stored.get("status", "pending")
        if status == "completed":
            completed += 1
        if status == "in_progress" and active_block_id is None:
            active_block_id = block["id"]
        if status == "pending" and first_pending is None:
            first_pending = block["id"]

        blocks_payload.append(
            {
                "id": block["id"],
                "label": block["label"],
                "status": status,
                "summary": stored.get("summary"),
                "completed_at": _iso_utc(stored.get("completed_at")),
                "updated_at": _iso_utc(stored.get("updated_at")),
            }
        )

    if active_block_id is None:
        active_block_id = first_pending or (AUDIT_BLOCKS[-1]["id"] if AUDIT_BLOCKS else None)

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
        "updated_at": _iso_utc(data.get("updated_at")),
    }


# =============================================================================
# 5) Propiedad de hilos (security)
# =============================================================================
def ensure_thread_ownership(thread_id: str, uid: str):
    """Registra o valida que el thread pertenece al uid dado."""
    doc_ref = firestore_db.collection("threads").document(thread_id)
    snap = doc_ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        owner = data.get("uid")
        if owner and owner != uid:
            abort(403, description="No tienes acceso a este hilo.")
    else:
        doc_ref.set({"uid": uid, "created_at": SERVER_TIMESTAMP}, merge=True)


# =============================================================================
# 6) Endpoints
# =============================================================================

@app.route("/audit_blocks", methods=["GET"])
def audit_blocks():
    return ok({"blocks": AUDIT_BLOCKS})


@limiter.limit("12/minute; 2/second")
@app.route("/chat_auditor", methods=["POST"])
def chat_with_main_audit_orchestrator():
    decoded_user = require_firebase_user_or_403()
    persistence_metadata = _build_user_metadata(decoded_user)

    if request.content_type != "application/json":
        return fail("Content-Type must be application/json", 415)
    data = request.get_json(silent=True) or {}

    user_message = (data.get("message") or "").strip()
    thread_id = data.get("thread_id")
    if not user_message:
        return fail("message is required", 400)
    if len(user_message) > 4000:
        return fail("message too long", 413)

    if not thread_id:
        try:
            thread_id = client.beta.threads.create(request_timeout=60.0).id
        except APITimeoutError as exc:
            logger.warning("%s: timeout creando thread en OpenAI: %s", endpoint_name, exc)
            return fail(
                "El orquestador tardó demasiado en iniciar la conversación.",
                status=504,
                upstream="openai",
                detail=str(exc),
            )

    # Verifica/Registra propiedad del hilo
    ensure_thread_ownership(thread_id, decoded_user["uid"])

    endpoint_name = "/chat_auditor"
    run = None

    try:
        logger.info(
            f"{endpoint_name}: uid={decoded_user.get('uid')} email={decoded_user.get('email')} thread_id={thread_id}"
        )

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message,
            request_timeout=60.0,
        )

        # Ejecuta orquestador
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ORCHESTRATOR_ASSISTANT_ID,
            timeout=180.0,
            request_timeout=60.0,
        )

        # Soporte de herramientas si requiere acción
        if run.status == "requires_action":
            tool_outputs = []
            ra = run.required_action
            for tc in ra.submit_tool_outputs.tool_calls:
                if tc.function.name == "invoke_sustainability_expert":
                    args = json.loads(tc.function.arguments or "{}")
                    query = args.get("query")
                    output = execute_invoke_sustainability_expert(query, thread_id)
                    tool_outputs.append({"tool_call_id": tc.id, "output": output})

            if tool_outputs:
                run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                    timeout=180.0,
                    request_timeout=60.0,
                )

        if run.status != "completed":
            raise Exception(f"Run ended with status={run.status}. Details: {getattr(run, 'last_error', None)}")

        messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order="desc")
        response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)

        persist_conversation_turn(
            thread_id,
            user_message,
            response_text,
            endpoint_name,
            run_id=run.id,
            assistant_name="MainAuditOrchestrator",
            **persistence_metadata,
        )

        return ok(
            {
                "response": response_text,
                "thread_id": thread_id,
                "run_id": run.id,
                "run_status": run.status,
            }
        )

    except APITimeoutError as exc:
        logger.warning("%s: timeout esperando respuesta de OpenAI: %s", endpoint_name, exc)
        persist_conversation_turn(
            thread_id,
            user_message,
            "API Timeout: OpenAI no respondió a tiempo.",
            endpoint_name,
            run_id=getattr(run, "id", None),
            assistant_name="Timeout",
            **persistence_metadata,
        )
        return fail(
            "El orquestador no respondió a tiempo. Inténtalo de nuevo en unos segundos.",
            status=504,
            upstream="openai",
            detail=str(exc),
        )
    except Exception as e:
        logger.error(f"{endpoint_name}: error: {e}", exc_info=True)
        persist_conversation_turn(
            thread_id,
            user_message,
            f"API Error: {e}",
            endpoint_name,
            run_id=getattr(run, "id", None),
            assistant_name="Exception",
            **persistence_metadata,
        )
        return fail("Internal server error", status=500, details=str(e))


@limiter.limit("20/minute; 3/second")
@app.route("/chat_assistant", methods=["POST"])
def chat_with_sustainability_expert():
    decoded_user = require_firebase_user_or_403()
    persistence_metadata = _build_user_metadata(decoded_user)

    if request.content_type != "application/json":
        return fail("Content-Type must be application/json", 415)
    data = request.get_json(silent=True) or {}

    user_message = (data.get("message") or "").strip()
    thread_id = data.get("thread_id")
    if not user_message:
        return fail("message is required", 400)
    if len(user_message) > 4000:
        return fail("message too long", 413)

    if not thread_id:
        try:
            thread_id = client.beta.threads.create(request_timeout=60.0).id
        except APITimeoutError as exc:
            logger.warning("%s: timeout creando thread en OpenAI: %s", endpoint_name, exc)
            return fail(
                "El asistente tardó demasiado en iniciar la conversación.",
                status=504,
                upstream="openai",
                detail=str(exc),
            )

    ensure_thread_ownership(thread_id, decoded_user["uid"])

    endpoint_name = "/chat_assistant"
    run = None

    try:
        logger.info(
            f"{endpoint_name}: uid={decoded_user.get('uid')} email={decoded_user.get('email')} thread_id={thread_id}"
        )

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message,
            request_timeout=60.0,
        )

        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASISTENTE_ID,
            timeout=180.0,
            request_timeout=60.0,
        )

        if run.status != "completed":
            raise Exception(f"Run ended with status={run.status}. Details: {getattr(run, 'last_error', None)}")

        messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order="desc")
        response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)

        persist_conversation_turn(
            thread_id,
            user_message,
            response_text,
            endpoint_name,
            run_id=run.id,
            assistant_name="SustainabilityExpert",
            **persistence_metadata,
        )

        return ok(
            {
                "response": response_text,
                "thread_id": thread_id,
                "run_id": run.id,
                "run_status": run.status,
            }
        )

    except APITimeoutError as exc:
        logger.warning("%s: timeout esperando respuesta de OpenAI: %s", endpoint_name, exc)
        persist_conversation_turn(
            thread_id,
            user_message,
            "API Timeout: OpenAI no respondió a tiempo.",
            endpoint_name,
            run_id=getattr(run, "id", None),
            assistant_name="Timeout",
            **persistence_metadata,
        )
        return fail(
            "El asistente no respondió a tiempo. Inténtalo de nuevo en unos segundos.",
            status=504,
            upstream="openai",
            detail=str(exc),
        )
    except Exception as e:
        logger.error(f"{endpoint_name}: error: {e}", exc_info=True)
        persist_conversation_turn(
            thread_id,
            user_message,
            f"API Error: {e}",
            endpoint_name,
            run_id=getattr(run, "id", None),
            assistant_name="Exception",
            **persistence_metadata,
        )
        return fail("Internal server error", status=500, details=str(e))


@app.route("/chat_history/recents", methods=["GET"])
def get_recent_chat_history():
    """Devuelve las últimas conversaciones del usuario autenticado."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")
    try:
        limit = request.args.get("limit", default=5, type=int)
    except (TypeError, ValueError):
        limit = 5

    try:
        conversations = fetch_recent_conversations_for_user(uid=uid, limit=limit)
        return ok({"conversations": conversations})
    except ValueError as err:
        return fail(str(err), status=400)
    except Exception as exc:
        logger.error("Failed to fetch recent chat history for uid=%s: %s", uid, exc, exc_info=True)
        return fail("No se pudo obtener el historial reciente.", status=500)


@app.route("/chat_history/thread/<thread_id>", methods=["GET"])
def get_chat_history_thread(thread_id: str):
    """Devuelve todos los mensajes de una conversación concreta si pertenece al usuario."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    # Seguridad: el hilo debe pertenecer al usuario
    ensure_thread_ownership(thread_id, uid)

    try:
        conversation = fetch_conversation_thread(uid=uid, thread_id=thread_id)
        return ok(conversation)
    except ValueError as err:
        return fail(str(err), status=400)
    except Exception as exc:
        logger.error("Failed to fetch chat thread %s for uid=%s: %s", thread_id, uid, exc, exc_info=True)
        return fail("No se pudo obtener la conversacion solicitada.", status=500)


@app.route("/audit_progress/<thread_id>", methods=["GET"])
def get_audit_progress(thread_id: str):
    """Devuelve el estado de progreso de auditoría para un hilo concreto."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    # Seguridad: el hilo debe pertenecer al usuario
    ensure_thread_ownership(thread_id, uid)

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
        return fail("No se pudo obtener el progreso de auditoria.", status=500)

    payload = _build_audit_progress_payload(thread_id, uid, data)
    return ok(payload)


@app.route("/audit_progress/<thread_id>", methods=["POST"])
def update_audit_progress(thread_id: str):
    """Actualiza el estado de un bloque de auditoría para un hilo."""
    decoded_user = require_firebase_user_or_403()
    uid = decoded_user.get("uid")

    # Seguridad: el hilo debe pertenecer al usuario
    ensure_thread_ownership(thread_id, uid)

    body = request.get_json(silent=True) or {}
    block_id = body.get("block_id")
    status = (body.get("status") or "completed").strip().lower()
    summary = body.get("summary")

    if not block_id or block_id not in AUDIT_BLOCK_IDS:
        return fail("block_id invalido. Debe corresponderse con un bloque del proceso.", status=400)
    if status not in VALID_STATUSES:
        return fail(
            f"status invalido. Valores permitidos: {', '.join(sorted(VALID_STATUSES))}", status=400
        )

    doc_ref = _get_audit_progress_doc(thread_id)

    @firestore.transactional
    def _tx_update_progress(tx, ref, _uid, _block_id, _status, _summary):
        snap = ref.get(transaction=tx)
        if snap.exists:
            data = snap.to_dict() or {}
            stored_uid = data.get("uid")
            if stored_uid and stored_uid != _uid:
                abort(403, description="No tienes acceso a este progreso de auditoria.")
        else:
            data = _default_audit_progress_state(uid=_uid)

        block_state = (data.setdefault("blocks", {}).get(_block_id) or {})
        block_state["status"] = _status
        block_state["updated_at"] = SERVER_TIMESTAMP
        if _summary is not None:
            block_state["summary"] = _summary
        block_state["completed_at"] = SERVER_TIMESTAMP if _status == "completed" else None

        data["blocks"][_block_id] = block_state
        data["uid"] = _uid
        data["updated_at"] = SERVER_TIMESTAMP

        tx.set(ref, data, merge=True)
        return data

    try:
        tx = firestore_db.transaction()
        data = _tx_update_progress(tx, doc_ref, uid, block_id, status, summary)
    except Exception as exc:
        logger.error(
            "Failed to update audit progress thread=%s block=%s: %s", thread_id, block_id, exc, exc_info=True
        )
        return fail("No se pudo actualizar el progreso de auditoria.", status=500)

    payload = _build_audit_progress_payload(thread_id, uid, data)
    return ok(payload)


@app.route("/health", methods=["GET"])
def health_check():
    """Comprobación básica de que el proceso está vivo."""
    return ok({"status": "healthy"})


@app.route("/readyz", methods=["GET"])
def readyz():
    """Comprobación de dependencias: Firestore (y opcional OpenAI si quieres añadir)."""
    try:
        # Ping liviano a Firestore
        firestore_db.collection("_ready").document("ping").get()
        # Podrías añadir una llamada barata a OpenAI si tu política lo permite:
        # _ = client.models.list()  # cuidado con costes/latencia
        return ok({"status": "ready"})
    except Exception as e:
        return fail("degraded", status=503, details=str(e))


# =============================================================================
# 7) Entry point
# =============================================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
