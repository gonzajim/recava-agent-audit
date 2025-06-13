import os
import time
import json
from flask import Flask, request, jsonify
from flask_cors import CORS # Importa CORS
import openai
from openai import OpenAI
import logging
from google.cloud import firestore

# Initialize Flask app
app = Flask(__name__)

# --- CONFIGURACIÓN DE CORS ---
# Añadimos las URL del nuevo frontend de desarrollo a la lista de orígenes permitidos.
allowed_origins = [
    "https://recava-auditor.web.app",       # URL de Firebase PROD
    "https://recava-auditor-dev.web.app"   # URL de Firebase DEV (CORREGIDA)
]

CORS(app, resources={r"/*": {"origins": allowed_origins}}, supports_credentials=True, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization", "X-Requested-With"])


# --- Centralized Logging Setup ---
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(threadName)s - %(filename)s:%(lineno)d - %(message)s'
    )
    stream_handler.setFormatter(formatter)
    app.logger.addHandler(stream_handler)

app.logger.info("Flask application starting up...")

# Load environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AUDIT_ORCHESTRATOR_ASSISTANT_ID = os.getenv("ORCHESTRATOR_ASSISTANT_ID")
SUSTAINABILITY_EXPERT_ASSISTANT_ID = os.getenv("ASISTENTE_ID")

# Validaciones de variables de entorno
if not OPENAI_API_KEY:
    app.logger.critical("Missing OPENAI_API_KEY environment variable.")
    raise ValueError("Missing OPENAI_API_KEY environment variable.")
if not AUDIT_ORCHESTRATOR_ASSISTANT_ID:
    app.logger.critical("Missing ORCHESTRATOR_ASSISTANT_ID (for Auditor-Orchestrator role) environment variable.")
    raise ValueError("Missing ORCHESTRATOR_ASSISTANT_ID (for Auditor-Orchestrator role) environment variable.")
if not SUSTAINABILITY_EXPERT_ASSISTANT_ID:
    app.logger.critical("Missing ASISTENTE_ID (for Sustainability Expert role) environment variable.")
    raise ValueError("Missing ASISTENTE_ID (for Sustainability Expert role) environment variable.")

app.logger.info("Environment variables loaded.")

# Initialize OpenAI client
try:
    client = OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=30.0,
        max_retries=2
    )
    app.logger.info("OpenAI client initialized successfully.")

    from packaging import version
    min_version = version.parse("1.3.0")
    installed_version = version.parse(openai.__version__)
    if installed_version < min_version:
        raise RuntimeError(
            f"OpenAI SDK version {min_version} or newer required; found {openai.__version__}"
        )
    app.logger.info(f"OpenAI SDK version {openai.__version__} meets minimum requirement")
except Exception as e:
    app.logger.critical(f"Failed to initialize OpenAI client: {e}", exc_info=True)
    raise

# Initialize Firestore Client
try:
    db = firestore.Client()
    app.logger.info("Firestore client initialized successfully.")
except Exception as e:
    app.logger.critical(f"Failed to initialize Firestore client: {e}", exc_info=True)
    raise

# --- Función para Guardar Conversación en Firestore ---
def store_conversation_turn(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str, run_id: str = None, assistant_name: str = None, citations: list = None):
    if not user_message and not assistant_response:
        app.logger.warning(f"Firestore: Skipping storage for thread {thread_id} from {endpoint_source} due to both user_message and assistant_response being empty.")
        return
    collection_name = "audit_trail"
    try:
        doc_ref = db.collection(collection_name).document()
        data_to_store = {
            'thread_id': thread_id if thread_id else "unknown_thread",
            'user_message': user_message if user_message is not None else "",
            'assistant_response': assistant_response if assistant_response is not None else "",
            'endpoint_source': endpoint_source,
            'timestamp': firestore.SERVER_TIMESTAMP,
        }
        if run_id:
            data_to_store['run_id'] = run_id
        if assistant_name:
            data_to_store['assistant_name'] = assistant_name
        if citations is not None and citations: # Solo guardar citas si la lista no está vacía
            data_to_store['citations'] = citations
        
        doc_ref.set(data_to_store)
        app.logger.info(f"Firestore: Stored conversation turn for thread {data_to_store['thread_id']} from {endpoint_source} in document {doc_ref.id}.")
    except Exception as e:
        app.logger.error(f"Firestore: Failed to store conversation turn for thread {thread_id}. Error: {e}", exc_info=True)

# --- Implementación de Herramienta para el Auditor-Orquestador ---
def execute_invoke_sustainability_expert(query: str, original_thread_id: str) -> str:
    tool_name = "invoke_sustainability_expert"
    app.logger.info(f"Auditor-Orchestrator's tool ({tool_name}): Executing for query: \"{query}\" (Original Thread: {original_thread_id})")
    temp_thread = None
    error_message_for_orchestrator = "ERROR_EXPERT: No se pudo obtener respuesta del experto en sostenibilidad en este momento. Por favor, intente la pregunta más tarde o continúe con la auditoría."

    try:
        temp_thread = client.beta.threads.create()
        temp_thread_id = temp_thread.id
        app.logger.info(f"Tool ({tool_name}): Created temporary thread {temp_thread_id} for Sustainability Expert.")

        client.beta.threads.messages.create(
            thread_id=temp_thread_id,
            role="user",
            content=query
        )
        app.logger.info(f"Tool ({tool_name}): Added query to temporary thread {temp_thread_id}.")

        app.logger.info(f"Tool ({tool_name}): Creating run on temp thread {temp_thread_id} for Sustainability Expert ({SUSTAINABILITY_EXPERT_ASSISTANT_ID}).")
        run = client.beta.threads.runs.create_and_poll(
            thread_id=temp_thread_id,
            assistant_id=SUSTAINABILITY_EXPERT_ASSISTANT_ID,
            instructions="Please address the user's query (last message in this thread) based on your knowledge. Provide a concise and focused answer."
        )

        response_text = error_message_for_orchestrator
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(
                thread_id=temp_thread_id,
                run_id=run.id, # Filtrar por run_id es buena práctica
                order='desc',
                limit=1 # Solo el último mensaje del asistente para este run
            )
            if messages.data and messages.data[0].content:
                response_text_parts = [content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text']
                response_text = "\n".join(response_text_parts).strip()

                if not response_text:
                    app.logger.warning(f"Tool ({tool_name}) on temp thread {temp_thread_id}: Sustainability Expert returned empty content.")
                    response_text = "El experto en sostenibilidad no proporcionó una respuesta textual para esta consulta."
                else:
                    app.logger.info(f"Tool ({tool_name}): Sustainability Expert response from temp thread {temp_thread_id}: \"{response_text[:100]}...\"")
            else:
                app.logger.warning(f"Tool ({tool_name}) on temp thread {temp_thread_id}: No message content found after run completion.")
        else:
            app.logger.error(f"Tool ({tool_name}): Sustainability Expert run on temp thread {temp_thread_id} failed. Status: {run.status}. Details: {run.last_error or 'N/A'}")
        
        return response_text

    except Exception as e:
        app.logger.error(f"Tool ({tool_name}): Exception: {e}", exc_info=True)
        return error_message_for_orchestrator
    finally:
        if temp_thread:
            try:
                client.beta.threads.delete(temp_thread.id)
                app.logger.info(f"Tool ({tool_name}): Deleted temporary thread {temp_thread.id}.")
            except Exception as delete_err:
                app.logger.error(f"Tool ({tool_name}): Failed to delete temporary thread {temp_thread.id}. Error: {delete_err}", exc_info=True)


# --- Función auxiliar para procesar mensajes (SIN CITAS) ---
def process_assistant_message_without_citations(messages_data, final_run_id, endpoint_name):
    assistant_response_text = "No new response from assistant for this run."

    for msg in messages_data:
        if msg.run_id == final_run_id and msg.role == "assistant":
            if msg.content:
                text_parts = [content_block.text.value for content_block in msg.content if content_block.type == 'text']
                raw_response_text = "\n".join(text_parts).strip()
                if raw_response_text:
                    assistant_response_text = raw_response_text
                else:
                    app.logger.warning(f"{endpoint_name}: Assistant message for run {final_run_id} had text content blocks but resulted in empty text.")
                    assistant_response_text = "El asistente proporcionó una respuesta vacía."
                break
    
    if assistant_response_text == "No new response from assistant for this run.":
        app.logger.warning(f"{endpoint_name}: No message from assistant role found for run {final_run_id}.")

    return assistant_response_text.strip()


# --- Endpoint Principal para el Asistente Auditor-Orquestador ---
@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    endpoint_name = "/chat_auditor"
    app.logger.info(f"Received request for {endpoint_name} from {request.remote_addr}")
    data_from_request = request.json
    user_message_content = data_from_request.get('message')
    thread_id = data_from_request.get('thread_id')
    final_run_status = "unknown"
    current_run_id_for_storage = None

    try:
        if not data_from_request or not user_message_content:
            app.logger.warning(f"{endpoint_name}: Invalid request, empty JSON or no message.")
            return jsonify({"error": "Invalid request: payload must be JSON and contain a message."}), 400

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content[:50]}...', thread_id='{thread_id}'")
        
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread: {thread_id}")
        else:
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Using existing thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found. Creating a new one.")
                thread = client.beta.threads.create()
                thread_id = thread.id

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message_content)
        app.logger.info(f"{endpoint_name}: Added user message to thread {thread_id}")

        current_run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=AUDIT_ORCHESTRATOR_ASSISTANT_ID)
        current_run_id_for_storage = current_run.id
        
        start_time = time.time()
        timeout_seconds = 180
        max_tool_call_iterations = 5
        tool_iterations_count = 0

        while current_run.status in ['queued', 'in_progress', 'requires_action']:
            if time.time() - start_time > timeout_seconds:
                raise Exception(f"Run timed out after {timeout_seconds}s.")

            time.sleep(1)
            current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
            final_run_status = current_run.status
            app.logger.info(f"{endpoint_name}: Polling Run {current_run.id}, Status: {final_run_status}")

            if current_run.status == 'requires_action':
                if tool_iterations_count >= max_tool_call_iterations:
                    raise Exception(f"Exceeded max tool call iterations ({max_tool_call_iterations}).")
                
                tool_iterations_count += 1
                tool_outputs = []
                if current_run.required_action and current_run.required_action.submit_tool_outputs:
                    for tool_call in current_run.required_action.submit_tool_outputs.tool_calls:
                        function_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            output = f"Error: Invalid JSON arguments for tool {function_name}."
                        else:
                            if function_name == "invoke_sustainability_expert":
                                output = execute_invoke_sustainability_expert(query=arguments.get("query"), original_thread_id=thread_id)
                            else:
                                output = f"Error: Unknown tool function '{function_name}'."
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": str(output)})
                
                if tool_outputs:
                    client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=current_run.id, tool_outputs=tool_outputs)
        
        if final_run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=current_run.id, order='desc', limit=10)
            assistant_response_text = process_assistant_message_without_citations(messages.data, current_run.id, endpoint_name)
            store_conversation_turn(thread_id, user_message_content, assistant_response_text, endpoint_name, current_run.id, "MainAuditOrchestrator")
            response_payload = {"response": assistant_response_text, "thread_id": thread_id, "run_id": current_run.id, "run_status": final_run_status}
            return jsonify(response_payload), 200
        else:
            error_message = f"Run ended with unhandled status: {final_run_status}."
            if current_run and current_run.last_error:
                error_message += f" Last Error: {current_run.last_error.message}"
            raise Exception(error_message)

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        error_details = str(e)
        store_conversation_turn(thread_id, user_message_content, f"API Error: {error_details}", endpoint_name, current_run_id_for_storage, "MainAuditOrchestratorException")
        response_payload = {"error": "An internal server error occurred.", "details": error_details, "thread_id": thread_id, "run_id": current_run_id_for_storage, "run_status": final_run_status}
        return jsonify(response_payload), 500


# --- Endpoint para el Asistente Experto en Sostenibilidad Directo ---
@app.route('/chat_assistant', methods=['POST'])
def chat_with_sustainability_expert():
    endpoint_name = "/chat_assistant"
    app.logger.info(f"Received request for {endpoint_name} from {request.remote_addr}")
    data_from_request = request.json
    user_message_content = data_from_request.get('message')
    thread_id = data_from_request.get('thread_id')
    final_run_status = "unknown"
    sustainability_run_id_for_storage = None

    try:
        if not data_from_request or not user_message_content:
            app.logger.warning(f"{endpoint_name}: Invalid request, empty JSON or no message.")
            return jsonify({"error": "Invalid request: payload must be JSON and contain a message."}), 400

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content[:50]}...', thread_id='{thread_id}'")
        
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread: {thread_id}")
        else:
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Using existing thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found. Creating a new one.")
                thread = client.beta.threads.create()
                thread_id = thread.id

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message_content)
        app.logger.info(f"{endpoint_name}: Added user message to thread {thread_id}")

        sustainability_run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=SUSTAINABILITY_EXPERT_ASSISTANT_ID,
            instructions=f"Please answer the user's latest question: \"{user_message_content}\"",
            timeout=180.0
        )
        sustainability_run_id_for_storage = sustainability_run.id
        final_run_status = sustainability_run.status
        app.logger.info(f"{endpoint_name}: Run {sustainability_run_id_for_storage} completed with status: {final_run_status}")

        if final_run_status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=sustainability_run.id, order='desc', limit=10)
            assistant_response_text = process_assistant_message_without_citations(messages.data, sustainability_run.id, endpoint_name)
            store_conversation_turn(thread_id, user_message_content, assistant_response_text, endpoint_name, sustainability_run.id, "SustainabilityExpert")
            response_payload = {"response": assistant_response_text, "thread_id": thread_id, "run_id": sustainability_run.id, "run_status": final_run_status}
            return jsonify(response_payload), 200
        else:
            error_message = f"Run ended with unhandled status: {final_run_status}."
            if sustainability_run and sustainability_run.last_error:
                error_message += f" Last Error: {sustainability_run.last_error.message}"
            raise Exception(error_message)

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        error_details = str(e)
        store_conversation_turn(thread_id, user_message_content, f"API Error: {error_details}", endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertException")
        response_payload = {"error": "An internal server error occurred.", "details": error_details, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage, "run_status": final_run_status}
        return jsonify(response_payload), 500


# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    app.logger.info("Health check endpoint was called.")
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080)) 
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.logger.info(f"Starting Flask server on port {port} with debug mode: {debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
