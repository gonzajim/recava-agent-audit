# app.py
import os
import time
import json
from flask import request, jsonify, abort

# --- 1. Importaciones de la configuración y servicios ---
from src.config import app, logger, client, ORCHESTRATOR_ASSISTANT_ID, ASISTENTE_ID
# --- CORRECCIÓN: Usar el nuevo nombre de la función ---
from src.persistence_service import persist_conversation_turn
from src.openai_service import execute_invoke_sustainability_expert, process_assistant_message_without_citations

# --- 1.b Autenticación Firebase: validar ID token y email verificado ---
# reemplaza tu bloque de init firebase_admin por:
import firebase_admin
from firebase_admin import credentials, auth as fb_auth

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
