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

# Configuración de CORS explícita
# Esto permite cualquier origen (*), cualquier cabecera, y los métodos comunes.
# También es importante para manejar el 'Content-Type' que envías.
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization", "X-Requested-With"])

# --- Centralized Logging Setup ---
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(threadName)s - %(filename)s:%(lineno)d - %(message)s'
    )
    stream_handler.setFormatter(formatter)
    app.logger.addHandler(stream_handler)
# --- End Centralized Logging Setup ---

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
def store_conversation_turn(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str, run_id: str = None, assistant_name: str = None):
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
            messages = client.beta.threads.messages.list(thread_id=temp_thread_id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                response_text = "".join([content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text'])
                if not response_text.strip(): 
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

# --- Endpoint Principal para el Asistente Auditor-Orquestador ---
@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    endpoint_name = "/chat_auditor"
    app.logger.info(f"Received request for {endpoint_name} (Main Auditor-Orchestrator) endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    data_from_request = None 
    assistant_response_for_storage = "Error or no response generated by Main Auditor-Orchestrator." 
    current_run_id_for_storage = None
    response_payload = {} # Para construir la respuesta final

    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            response_payload = {"error": "Invalid request: payload must be JSON."}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 400

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id') 

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")

        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            response_payload = {"error": "No message provided"}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 400
            
        app.logger.info(f"{endpoint_name}: Attempting to interact with Main Auditor-Orchestrator for thread: {thread_id or 'New Thread'}")
        
        original_thread_id_if_new_created = None
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Main Auditor-Orchestrator: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Main Auditor-Orchestrator: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Main Auditor-Orchestrator thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found. Creating a new one for this session.")
                original_thread_id_if_new_created = thread_id
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created}, starting new session) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Main Auditor-Orchestrator thread {thread_id}: {e}", exc_info=True)
                response_payload = {"error": f"Invalid or inaccessible thread_id for Main Auditor-Orchestrator: {thread_id}", "details": str(e)}
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), 400

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message_content
        )
        app.logger.info(f"{endpoint_name}: Added user message to Main Auditor-Orchestrator thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Main Auditor-Orchestrator ({AUDIT_ORCHESTRATOR_ASSISTANT_ID}) on thread {thread_id}")
        current_run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=AUDIT_ORCHESTRATOR_ASSISTANT_ID
        )
        current_run_id_for_storage = current_run.id 
        app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} created for thread {thread_id}. Initial status: {current_run.status}")
        
        polling_attempts = 0
        max_polling_attempts_before_action = 60 
        max_tool_call_iterations = 3 
        tool_iterations_count = 0
        
        while current_run.status in ['queued', 'in_progress', 'requires_action'] and tool_iterations_count < max_tool_call_iterations :
            if current_run.status in ['queued', 'in_progress']:
                polling_attempts += 1
                if polling_attempts > max_polling_attempts_before_action:
                    app.logger.warning(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} timed out waiting for 'requires_action' or completion. Last status: {current_run.status}")
                    assistant_response_for_storage = f"OpenAI run (Main Auditor-Orchestrator) timed out. Status: {current_run.status}"
                    try: 
                        app.logger.info(f"{endpoint_name}: Attempting to cancel run {current_run.id} due to polling timeout.")
                        client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                        app.logger.info(f"{endpoint_name}: Successfully cancelled run {current_run.id}.")
                        assistant_response_for_storage += " Run cancelled."
                    except Exception as cancel_err:
                        app.logger.error(f"{endpoint_name}: Failed to cancel run {current_run.id}: {cancel_err}", exc_info=True)
                        assistant_response_for_storage += " Failed to cancel run."
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorTimeout")
                    response_payload = {"error": "OpenAI run (Main Auditor-Orchestrator) timed out.", "thread_id": thread_id, "run_id": current_run.id, "status": "timed_out_and_cancelled_attempted"}
                    app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                    return jsonify(response_payload), 504
                
                time.sleep(1)
                current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
                app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} status: {current_run.status} (Polling Attempt {polling_attempts})")

            if current_run.status == 'requires_action':
                tool_iterations_count +=1
                polling_attempts = 0 
                app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} requires action (Tool Call Iteration {tool_iterations_count}).")
                tool_outputs = []
                if current_run.required_action and current_run.required_action.type == "submit_tool_outputs":
                    for tool_call in current_run.required_action.submit_tool_outputs.tool_calls:
                        function_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            app.logger.error(f"{endpoint_name}: Failed to parse JSON arguments for tool {function_name} on run {current_run.id}: {tool_call.function.arguments}. Error: {e}", exc_info=True)
                            output = f"Error: Invalid JSON arguments provided for tool {function_name}."
                        else:
                            app.logger.info(f"{endpoint_name}: Run {current_run.id} calling tool: {function_name}, Args: {arguments}")
                            output = ""
                            if function_name == "invoke_sustainability_expert": 
                                output = execute_invoke_sustainability_expert(query=arguments.get("query"), original_thread_id=thread_id)
                            else:
                                app.logger.warning(f"{endpoint_name}: Run {current_run.id} requested unknown tool function: {function_name}")
                                output = f"Error: Unknown tool function '{function_name}' requested."
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": str(output)})
                
                if tool_outputs:
                    app.logger.info(f"{endpoint_name}: Submitting tool outputs for run {current_run.id} on thread {thread_id}: {tool_outputs}")
                    try:
                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id, run_id=current_run.id, tool_outputs=tool_outputs
                        )
                        app.logger.info(f"{endpoint_name}: Tool outputs submitted for run {current_run.id}. Run will re-queue.")
                        time.sleep(0.5) 
                        current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id) 
                    except Exception as e: 
                        app.logger.error(f"{endpoint_name}: Error submitting tool outputs for run {current_run.id} on thread {thread_id}: {e}", exc_info=True)
                        assistant_response_for_storage = f"Error submitting tool outputs: {str(e)}"
                        store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorToolError")
                        response_payload = {"error": f"Error submitting tool outputs: {str(e)}", "thread_id": thread_id, "run_id": current_run.id}
                        app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                        return jsonify(response_payload), 500
                else: 
                    app.logger.warning(f"{endpoint_name}: Run {current_run.id} on thread {thread_id} was 'requires_action' but no tool_outputs were generated/processed.")
                    assistant_response_for_storage = "Auditor-Orchestrator required action but no tool outputs were processed."
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorToolError")
                    response_payload = {"error": "Auditor-Orchestrator required action but no tool outputs were processed.", "thread_id": thread_id, "run_id": current_run.id, "run_status": current_run.status}
                    app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                    return jsonify(response_payload), 500
            
            if tool_iterations_count >= max_tool_call_iterations:
                app.logger.error(f"{endpoint_name}: Exceeded max tool call iterations ({max_tool_call_iterations}) for run {current_run.id}.")
                assistant_response_for_storage = "Exceeded max tool call iterations."
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorMaxToolCalls")
                response_payload = {"error": "Exceeded max tool call iterations.", "thread_id": thread_id, "run_id": current_run.id}
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), 500
        
        if current_run.status == 'completed':
            app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} completed.")
            messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            assistant_response = "No new response from Main Auditor-Orchestrator for this run." 
            for msg in messages.data:
                if msg.run_id == current_run.id and msg.role == "assistant":
                    if msg.content:
                        assistant_response_parts = []
                        for content_block in msg.content:
                             if content_block.type == 'text':
                                assistant_response_parts.append(content_block.text.value)
                        assistant_response = "\n".join(assistant_response_parts).strip()
                        break
            
            app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator final response for run {current_run.id} on thread {thread_id}: \"{assistant_response[:200]}...\"")
            assistant_response_for_storage = assistant_response 
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestrator")
            response_payload = {"response": assistant_response, "thread_id": thread_id, "run_id": current_run.id, "run_status": current_run.status}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload)
        
        else: 
            app.logger.error(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} ended with unhandled/final status: {current_run.status}. Last error: {current_run.last_error}")
            error_details = str(current_run.last_error.message) if current_run.last_error else f"Run ended in status {current_run.status}."
            assistant_response_for_storage = f"Main Auditor-Orchestrator Run ended with status: {current_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorError")
            response_payload = {"error": f"Main Auditor-Orchestrator Run ended with status: {current_run.status}", "details": error_details, "thread_id": thread_id, "run_id": current_run.id}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred in Main Auditor-Orchestrator endpoint: {e}", exc_info=True)
        _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
        if user_message_content is not None : 
             store_conversation_turn(_thread_id_for_except_log, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, current_run_id_for_storage, "MainAuditOrchestratorException")
        response_payload = {"error": f"An internal server error occurred: {str(e)}", "thread_id": _thread_id_for_except_log}
        app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
        return jsonify(response_payload), 500

# --- Endpoint para el Asistente Experto en Sostenibilidad Directo ---
@app.route('/chat_assistant', methods=['POST'])
def chat_with_sustainability_expert(): 
    endpoint_name = "/chat_assistant"
    app.logger.info(f"Received request for {endpoint_name} (Sustainability Expert) endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    data_from_request = None
    assistant_response_for_storage = "Error or no response generated by Sustainability Expert."
    sustainability_run_id_for_storage = None
    response_payload = {}

    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            response_payload = {"error": "Invalid request: payload must be JSON."}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 400

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id')

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")
        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            response_payload = {"error": "No message provided"}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 400

        app.logger.info(f"{endpoint_name}: Attempting to interact with Sustainability Expert ({SUSTAINABILITY_EXPERT_ASSISTANT_ID}) for thread: {thread_id or 'New Thread'}")
        
        original_thread_id_if_new_created = None
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Sustainability Expert: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Sustainability Expert: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Sustainability Expert thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found for Sustainability Expert. Creating a new one.")
                original_thread_id_if_new_created = thread_id
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created} with Sustainability Expert, starting new session) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} for Sustainability Expert after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Sustainability Expert thread {thread_id}: {e}", exc_info=True)
                response_payload = {"error": f"Invalid or inaccessible thread_id for Sustainability Expert: {thread_id}", "details": str(e)}
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), 400
        
        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message_content)
        app.logger.info(f"{endpoint_name}: Added user message to Sustainability Expert thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Sustainability Expert ({SUSTAINABILITY_EXPERT_ASSISTANT_ID}) on thread {thread_id}")
        sustainability_run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=SUSTAINABILITY_EXPERT_ASSISTANT_ID,
            instructions=f"Please answer the user's latest question: \"{user_message_content}\""
        )
        sustainability_run_id_for_storage = sustainability_run.id
        app.logger.info(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} completed with status: {sustainability_run.status}")

        if sustainability_run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            assistant_response = "No new response from Sustainability Expert for this run."
            for msg in messages.data:
                if msg.run_id == sustainability_run_id_for_storage and msg.role == "assistant": 
                    if msg.content:
                        assistant_response_parts = []
                        for content_block in msg.content:
                            if content_block.type == 'text':
                                assistant_response_parts.append(content_block.text.value)
                        assistant_response = "\n".join(assistant_response_parts).strip()
                        break
            
            app.logger.info(f"{endpoint_name}: Sustainability Expert final response for run {sustainability_run_id_for_storage} on thread {thread_id}: \"{assistant_response[:200]}...\"")
            assistant_response_for_storage = assistant_response 
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpert")
            response_payload = {"response": assistant_response, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage, "run_status": sustainability_run.status}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload)
        else:
            app.logger.error(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} ended with status: {sustainability_run.status}. Last error: {sustainability_run.last_error}")
            error_details = str(sustainability_run.last_error.message) if sustainability_run.last_error else "No specific error details."
            assistant_response_for_storage = f"Sustainability Expert Run ended with status: {sustainability_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertError")
            response_payload = {"error": f"Sustainability Expert Run ended with status: {sustainability_run.status}", "details": error_details, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage}
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
        if user_message_content is not None:
            store_conversation_turn(_thread_id_for_except_log, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertException")
        response_payload = {"error": f"An internal server error occurred: {str(e)}", "thread_id": _thread_id_for_except_log}
        app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
        return jsonify(response_payload), 500

# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    app.logger.info("Health check endpoint was called.")
    response_payload = {}
    try:
        pass 
    except Exception as e:
        app.logger.error(f"Health check: Potential backend connectivity issue. Error: {e}", exc_info=True)
        response_payload = {"status": "unhealthy", "reason": "Potential backend connectivity issue"}
        app.logger.info(f"/health: Responding with JSON: {json.dumps(response_payload)}")
        return jsonify(response_payload), 503
    
    response_payload = {"status": "healthy"}
    app.logger.info(f"/health: Responding with JSON: {json.dumps(response_payload)}")
    return jsonify(response_payload), 200

if __name__ == '__main__':
    app.logger.info("Starting Flask development server with debug mode.")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
