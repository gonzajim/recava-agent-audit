import os
import time
import json

# --- 1. Importaciones combinadas ---
from flask import Flask, request, jsonify
import stripe

# SDKs de Firebase
import firebase_admin
from firebase_admin import credentials, auth, firestore

# Importaciones de la aplicación original
from src.config import app, logger, client, ORCHESTRATOR_ASSISTANT_ID, ASISTENTE_ID
from src.persistence_service import persist_conversation_turn
from src.openai_service import execute_invoke_sustainability_expert, process_assistant_message_without_citations

# --- 2. Configuración Inicial Unificada ---

# Inicializar Firebase Admin SDK
# Las credenciales se tomarán automáticamente del entorno de ejecución de GCP
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)
db = firestore.client()

# Cargar las claves de Stripe y la URL del frontend desde variables de entorno
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8080') # URL para redirección de Stripe

# Define los paquetes de créditos que se pueden comprar
CREDIT_PACKAGES = {
    'pack_10': {'name': '10 Créditos', 'price_in_cents': 500, 'credits': 10},
    'pack_50': {'name': '50 Créditos', 'price_in_cents': 2000, 'credits': 50},
}
CURRENCY = 'eur'

# --- 3. Middleware de autenticación ---
def check_auth(f):
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token is missing or invalid'}), 401
        
        id_token = auth_header.split('Bearer ')[1]
        try:
            # Verificar el token de ID de Firebase
            decoded_token = auth.verify_id_token(id_token)
            request.user = decoded_token # Adjuntar datos del usuario a la petición
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return jsonify({'error': 'Invalid token', 'details': str(e)}), 403
        
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- 4. Endpoints de la API con Monedero ---

@app.route('/chat_auditor', methods=['POST'])
@check_auth # Proteger y autenticar el endpoint
def chat_with_main_audit_orchestrator():
    """
    Gestiona el chat con el orquestador, consumiendo un crédito primero.
    """
    user_uid = request.user['uid']
    user_ref = db.collection('users').document(user_uid)
    
    # --- LÓGICA DE CONSUMO DE CRÉDITOS ---
    try:
        @firestore.transactional
        def consume_credit(transaction, user_doc_ref):
            snapshot = user_doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise Exception("User not found in Firestore.")
            
            current_credits = snapshot.get('credits')
            if current_credits is None or current_credits < 1:
                raise ValueError("Insufficient credits.")
            
            transaction.update(user_doc_ref, {'credits': current_credits - 1})
            return True

        consume_credit(db.transaction(), user_ref)
    except ValueError as e:
        logger.warning(f"User {user_uid} has insufficient credits.")
        return jsonify({'error': str(e), 'code': 'INSUFFICIENT_FUNDS'}), 402 # Payment Required
    except Exception as e:
        logger.error(f"Error during credit consumption for user {user_uid}: {e}")
        return jsonify({'error': f'An internal error occurred during payment verification: {str(e)}'}), 500
    
    # --- LÓGICA ORIGINAL DEL CHAT (si el pago es válido) ---
    endpoint_name, data = "/chat_auditor", request.json
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        if not user_message: return jsonify({"error": "Invalid request: message is required."}), 400
        if not thread_id: thread_id = client.beta.threads.create().id
        
        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ORCHESTRATOR_ASSISTANT_ID)
        run_id = run.id

        while run.status in ['queued', 'in_progress', 'requires_action']:
            time.sleep(1)
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            logger.info(f"{endpoint_name}: Polling Run {run.id}, Status: {run.status}")

            if run.status == 'requires_action':
                tool_outputs = [
                    {"tool_call_id": tc.id, "output": execute_invoke_sustainability_expert(json.loads(tc.function.arguments).get("query"), thread_id)}
                    for tc in run.required_action.submit_tool_outputs.tool_calls
                    if tc.function.name == "invoke_sustainability_expert"
                ]
                if tool_outputs:
                    client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs)
        
        run_status = run.status
        if run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc')
            response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)
            persist_conversation_turn(thread_id, user_message, response_text, endpoint_name, run_id=run.id, assistant_name="MainAuditOrchestrator", user_id=user_uid)
            return jsonify({"response": response_text, "thread_id": thread_id, "run_id": run.id, "run_status": run_status}), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        persist_conversation_turn(thread_id, user_message, f"API Error: {e}", endpoint_name, run_id=run_id, assistant_name="Exception", user_id=user_uid)
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500

@app.route('/chat_assistant', methods=['POST'])
@check_auth # Proteger y autenticar el endpoint
def chat_with_sustainability_expert():
    """
    Gestiona el chat con el experto, consumiendo un crédito primero.
    """
    user_uid = request.user['uid']
    user_ref = db.collection('users').document(user_uid)

    # --- LÓGICA DE CONSUMO DE CRÉDITOS (Idéntica al otro endpoint) ---
    try:
        @firestore.transactional
        def consume_credit(transaction, user_doc_ref):
            snapshot = user_doc_ref.get(transaction=transaction)
            if not snapshot.exists: raise Exception("User not found in Firestore.")
            current_credits = snapshot.get('credits')
            if current_credits is None or current_credits < 1: raise ValueError("Insufficient credits.")
            transaction.update(user_doc_ref, {'credits': current_credits - 1})
            return True
        consume_credit(db.transaction(), user_ref)
    except ValueError as e:
        return jsonify({'error': str(e), 'code': 'INSUFFICIENT_FUNDS'}), 402
    except Exception as e:
        return jsonify({'error': f'An internal error occurred during payment verification: {str(e)}'}), 500

    # --- LÓGICA ORIGINAL DEL CHAT ---
    endpoint_name, data = "/chat_assistant", request.json
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        if not user_message: return jsonify({"error": "Invalid request: message is required."}), 400
        if not thread_id: thread_id = client.beta.threads.create().id

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)
        run = client.beta.threads.runs.create_and_poll(thread_id=thread_id, assistant_id=ASISTENTE_ID, timeout=180.0)
        run_id, run_status = run.id, run.status

        if run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc')
            response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)
            persist_conversation_turn(thread_id, user_message, response_text, endpoint_name, run_id=run.id, assistant_name="SustainabilityExpert", user_id=user_uid)
            return jsonify({"response": response_text, "thread_id": thread_id, "run_id": run.id, "run_status": run_status}), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        persist_conversation_turn(thread_id, user_message, f"API Error: {e}", endpoint_name, run_id=run_id, assistant_name="Exception", user_id=user_uid)
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500

# --- Endpoint para crear una sesión de pago de Stripe ---
@app.route('/create-checkout-session', methods=['POST'])
@check_auth
def create_checkout_session():
    """
    Crea una sesión de Stripe Checkout para comprar un paquete de créditos.
    """
    data = request.get_json()
    package_id = data.get('package_id')
    user_uid = request.user['uid']

    if package_id not in CREDIT_PACKAGES:
        return jsonify({'error': 'Invalid package ID'}), 400
    
    package = CREDIT_PACKAGES[package_id]

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': CURRENCY,
                    'product_data': {'name': package['name']},
                    'unit_amount': package['price_in_cents'],
                },
                'quantity': 1,
            }],
            mode='payment',
            metadata={
                'user_uid': user_uid,
                'credits_to_add': package['credits']
            },
            success_url=f'{FRONTEND_URL}?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{FRONTEND_URL}',
        )
        return jsonify({'sessionId': checkout_session.id, 'url': checkout_session.url})
    except Exception as e:
        logger.error(f"Stripe session creation failed: {e}")
        return jsonify({'error': str(e)}), 403

# --- Endpoint de Health Check ---
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint para comprobaciones de estado del servicio."""
    return jsonify({"status": "healthy"}), 200

# --- Punto de Entrada de la Aplicación ---
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get("PORT", 8080)),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    )
