# app.py
import os
import time
import json
from flask import request, jsonify

# --- 1. Importaciones de la configuración y servicios ---
from src.config import app, logger, client, ORCHESTRATOR_ASSISTANT_ID, ASISTENTE_ID, auth
from src.credits_service import deduct_user_credit
# --- CORRECCIÓN: Usar el nuevo nombre de la función ---
from src.persistence_service import persist_conversation_turn
from src.openai_service import execute_invoke_sustainability_expert, process_assistant_message_without_citations

# --- 2. Endpoints de la API ---

@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    endpoint_name, data = "/chat_auditor", request.json
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        id_token = auth_header.split('Bearer ')[1]
        decoded = auth.verify_id_token(id_token)
        uid = decoded.get('uid')
        if not deduct_user_credit(uid):
            return jsonify({'error': 'Insufficient credits'}), 402

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
            # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
            persist_conversation_turn(thread_id, user_message, response_text, endpoint_name, run_id=run.id, assistant_name="MainAuditOrchestrator")
            return jsonify({"response": response_text, "thread_id": thread_id, "run_id": run.id, "run_status": run_status}), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
        persist_conversation_turn(thread_id, user_message, f"API Error: {e}", endpoint_name, run_id=run_id, assistant_name="Exception")
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500

@app.route('/chat_assistant', methods=['POST'])
def chat_with_sustainability_expert():
    endpoint_name, data = "/chat_assistant", request.json
    user_message, thread_id = data.get('message'), data.get('thread_id')
    run_id, run_status = None, "unknown"

    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        id_token = auth_header.split('Bearer ')[1]
        decoded = auth.verify_id_token(id_token)
        uid = decoded.get('uid')
        if not deduct_user_credit(uid):
            return jsonify({'error': 'Insufficient credits'}), 402

        if not user_message: return jsonify({"error": "Invalid request: message is required."}), 400
        if not thread_id: thread_id = client.beta.threads.create().id

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)
        run = client.beta.threads.runs.create_and_poll(thread_id=thread_id, assistant_id=ASISTENTE_ID, timeout=180.0)
        run_id, run_status = run.id, run.status

        if run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc')
            response_text = process_assistant_message_without_citations(messages.data, run.id, endpoint_name)
            # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
            persist_conversation_turn(thread_id, user_message, response_text, endpoint_name, run_id=run.id, assistant_name="SustainabilityExpert")
            return jsonify({"response": response_text, "thread_id": thread_id, "run_id": run.id, "run_status": run_status}), 200
        else:
            raise Exception(f"Run ended with unhandled status: {run_status}. Details: {run.last_error}")

    except Exception as e:
        logger.error(f"{endpoint_name}: An error occurred: {e}", exc_info=True)
        # --- CORRECCIÓN: Llamar a la función con el nombre correcto ---
        persist_conversation_turn(thread_id, user_message, f"API Error: {e}", endpoint_name, run_id=run_id, assistant_name="Exception")
        return jsonify({"error": "Internal server error", "details": str(e), "run_status": run_status}), 500

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401
    id_token = auth_header.split('Bearer ')[1]
    decoded = auth.verify_id_token(id_token)
    uid = decoded.get('uid')

    data = request.json or {}
    credits = data.get('credits')
    amount_cents = data.get('amount_cents')
    if not credits or not amount_cents:
        return jsonify({'error': 'Invalid request'}), 400

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='payment',
        line_items=[{
            'price_data': {
                'currency': 'eur',
                'unit_amount': int(amount_cents),
                'product_data': {'name': f'{credits} credits'}
            },
            'quantity': 1
        }],
        success_url=data.get('success_url', 'https://example.com/success'),
        cancel_url=data.get('cancel_url', 'https://example.com/cancel'),
        metadata={'uid': uid, 'credits': credits}
    )

    return jsonify({'checkout_url': session.url})

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