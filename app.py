import os
import time
import json
from flask import Flask, request, jsonify
import openai
from openai import OpenAI
import logging
from google.cloud import firestore

# Initialize Flask app
app = Flask(__name__)

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
ORCHESTRATOR_ASSISTANT_ID = os.getenv("ORCHESTRATOR_ASSISTANT_ID")
ASISTENTE_ID = os.getenv("ASISTENTE_ID")
AUDITOR_ID = os.getenv("AUDITOR_ID")

# Validaciones de variables de entorno
if not OPENAI_API_KEY:
    app.logger.critical("Missing OPENAI_API_KEY environment variable.")
    raise ValueError("Missing OPENAI_API_KEY environment variable.")
if not ORCHESTRATOR_ASSISTANT_ID:
    app.logger.critical("Missing ORCHESTRATOR_ASSISTANT_ID environment variable.")
    raise ValueError("Missing ORCHESTRATOR_ASSISTANT_ID environment variable.")
if not ASISTENTE_ID:
    app.logger.critical("Missing ASISTENTE_ID environment variable.")
    raise ValueError("Missing ASISTENTE_ID environment variable.")
if not AUDITOR_ID:
    app.logger.critical("Missing AUDITOR_ID environment variable.")
    raise ValueError("Missing AUDITOR_ID environment variable.")

app.logger.info("Environment variables loaded.")

# Initialize OpenAI client
try:
    client = OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=30.0, 
        max_retries=2
    )
    app.logger.info("OpenAI client initialized successfully with timeout and retries.")
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

# --- Tool Implementation Functions (MODIFICADAS PARA USAR HILOS TEMPORALES) ---
def execute_sustainability_assistant_tool(query: str, original_thread_id: str) -> str:
    # original_thread_id es el del Orquestador, no se usa aquí directamente para el run del sub-asistente.
    app.logger.info(f"Orchestrator's tool: Executing Sustainability Assistant with query: \"{query}\" (Original Thread: {original_thread_id})")
    temp_thread = None
    try:
        # 1. Crear hilo temporal
        temp_thread = client.beta.threads.create()
        temp_thread_id = temp_thread.id
        app.logger.info(f"Tool: Created temporary thread {temp_thread_id} for Sustainability Assistant.")

        # 2. Añadir mensaje al hilo temporal (la consulta del usuario)
        client.beta.threads.messages.create(
            thread_id=temp_thread_id,
            role="user",
            content=query
        )
        app.logger.info(f"Tool: Added query to temporary thread {temp_thread_id}.")

        # 3. Crear y sondear run en el hilo temporal para el Asistente de Sostenibilidad
        app.logger.info(f"Tool: Creating run on temp thread {temp_thread_id} for Sustainability Assistant ({ASISTENTE_ID}).")
        run = client.beta.threads.runs.create_and_poll(
            thread_id=temp_thread_id,
            assistant_id=ASISTENTE_ID,
            instructions="Please address the user's query (last message in this thread) based on your knowledge. Provide a concise and focused answer."
        )

        response_text = f"Error: Sustainability Assistant run did not complete successfully (status: {run.status})."
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=temp_thread_id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                response_text = "".join([content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text'])
                app.logger.info(f"Tool: Sustainability Assistant response from temp thread {temp_thread_id}: \"{response_text[:100]}...\"")
            else:
                app.logger.warning(f"Tool: Sustainability Assistant on temp thread {temp_thread_id}: No message content found.")
                response_text = "The Sustainability Assistant provided no textual response for this query."
        else:
            app.logger.error(f"Tool: Sustainability Assistant run on temp thread {temp_thread_id} failed. Status: {run.status}. Details: {run.last_error or 'N/A'}")
        
        return response_text

    except Exception as e:
        app.logger.error(f"Tool: Exception in execute_sustainability_assistant_tool: {e}", exc_info=True)
        return f"An error occurred while processing your sustainability query: {str(e)}"
    finally:
        # 5. Eliminar hilo temporal
        if temp_thread:
            try:
                client.beta.threads.delete(temp_thread.id)
                app.logger.info(f"Tool: Deleted temporary thread {temp_thread.id} for Sustainability Assistant.")
            except Exception as delete_err:
                app.logger.error(f"Tool: Failed to delete temporary thread {temp_thread.id}. Error: {delete_err}", exc_info=True)


def execute_auditor_assistant_tool(task: str, original_thread_id: str) -> str:
    app.logger.info(f"Orchestrator's tool: Executing Auditor Assistant with task: \"{task}\" (Original Thread: {original_thread_id})")
    temp_thread = None
    try:
        # 1. Crear hilo temporal
        temp_thread = client.beta.threads.create()
        temp_thread_id = temp_thread.id
        app.logger.info(f"Tool: Created temporary thread {temp_thread_id} for Auditor Assistant.")

        # 2. Determinar instrucción y añadir mensaje si es necesario
        instruction_for_auditor = ""
        if task.startswith("process_user_answer:"):
            user_answer = task.split("process_user_answer:", 1)[1].strip()
            client.beta.threads.messages.create(
                thread_id=temp_thread_id,
                role="user", # Simula que el usuario dio esta respuesta al auditor
                content=user_answer 
            )
            app.logger.info(f"Tool: Added user's answer to temporary thread {temp_thread_id} for Auditor.")
            instruction_for_auditor = "The user has provided an answer in the last message of this thread. Please process it and provide the next audit question or relevant feedback."
        elif task == "get_next_audit_question":
            instruction_for_auditor = "Please provide the next audit question according to the audit protocol."
        else:
            # Tarea desconocida o no manejada específicamente, pasarla tal cual
            instruction_for_auditor = f"Please perform the following task: \"{task}\""
            app.logger.warning(f"Tool: Auditor Assistant received an unspecific task structure: \"{task}\". Passing as general instruction.")

        # 3. Crear y sondear run en el hilo temporal para el Asistente Auditor
        app.logger.info(f"Tool: Creating run on temp thread {temp_thread_id} for Auditor Assistant ({AUDITOR_ID}). Instruction: {instruction_for_auditor}")
        run = client.beta.threads.runs.create_and_poll(
            thread_id=temp_thread_id,
            assistant_id=AUDITOR_ID,
            instructions=instruction_for_auditor
        )
        
        response_text = f"Error: Auditor Assistant run did not complete successfully (status: {run.status})."
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=temp_thread_id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                response_text = "".join([content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text'])
                app.logger.info(f"Tool: Auditor Assistant response from temp thread {temp_thread_id}: \"{response_text[:100]}...\"")
            else:
                app.logger.warning(f"Tool: Auditor Assistant on temp thread {temp_thread_id}: No message content found.")
                response_text = "The Auditor Assistant provided no textual response for this task."
        else:
            app.logger.error(f"Tool: Auditor Assistant run on temp thread {temp_thread_id} failed. Status: {run.status}. Details: {run.last_error or 'N/A'}")

        return response_text

    except Exception as e:
        app.logger.error(f"Tool: Exception in execute_auditor_assistant_tool: {e}", exc_info=True)
        return f"An error occurred while processing your audit task: {str(e)}"
    finally:
        # 5. Eliminar hilo temporal
        if temp_thread:
            try:
                client.beta.threads.delete(temp_thread.id)
                app.logger.info(f"Tool: Deleted temporary thread {temp_thread.id} for Auditor Assistant.")
            except Exception as delete_err:
                app.logger.error(f"Tool: Failed to delete temporary thread {temp_thread.id}. Error: {delete_err}", exc_info=True)

# --- Orchestrator API Endpoint (/chat_auditor) ---
# (La lógica interna de chat_with_orchestrator no necesita cambiar,
# ya que las funciones de herramienta ahora manejan la interacción con sub-asistentes de forma aislada)
@app.route('/chat_auditor', methods=['POST'])
def chat_with_orchestrator():
    endpoint_name = "/chat_auditor"
    app.logger.info(f"Received request for {endpoint_name} (Orchestrator) endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    data_from_request = None 
    assistant_response_for_storage = "Error or no response generated by Orchestrator." 
    current_run_id_for_storage = None

    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            return jsonify({"error": "Invalid request: payload must be JSON."}), 400

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id') 

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")

        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            return jsonify({"error": "No message provided"}), 400
            
        app.logger.info(f"{endpoint_name}: Attempting to interact with OpenAI Orchestrator for thread: {thread_id or 'New Thread'}")
        
        original_thread_id_if_new_created = None
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Orchestrator: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Orchestrator: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Orchestrator thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found. Creating a new one for this session.")
                original_thread_id_if_new_created = thread_id
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created}, starting new session) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Orchestrator thread {thread_id}: {e}", exc_info=True)
                return jsonify({"error": f"Invalid or inaccessible thread_id for Orchestrator: {thread_id}", "details": str(e)}), 400

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message_content
        )
        app.logger.info(f"{endpoint_name}: Added user message to Orchestrator thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Orchestrator ({ORCHESTRATOR_ASSISTANT_ID}) on thread {thread_id}")
        current_run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ORCHESTRATOR_ASSISTANT_ID
        )
        current_run_id_for_storage = current_run.id 
        app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} created for thread {thread_id}. Initial status: {current_run.status}")
        
        polling_attempts = 0
        max_polling_attempts_before_action = 60 
        
        while current_run.status in ['queued', 'in_progress']:
            polling_attempts += 1
            if polling_attempts > max_polling_attempts_before_action:
                app.logger.warning(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} timed out waiting for 'requires_action' or completion. Last status: {current_run.status}")
                assistant_response_for_storage = f"OpenAI run (Orchestrator) timed out before action or completion. Status: {current_run.status}"
                try: 
                    app.logger.info(f"{endpoint_name}: Attempting to cancel run {current_run.id} due to polling timeout.")
                    client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                    app.logger.info(f"{endpoint_name}: Successfully cancelled run {current_run.id}.")
                    assistant_response_for_storage += " Run cancelled."
                except Exception as cancel_err:
                    app.logger.error(f"{endpoint_name}: Failed to cancel run {current_run.id}: {cancel_err}", exc_info=True)
                    assistant_response_for_storage += " Failed to cancel run."
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "OrchestratorTimeout")
                return jsonify({"error": "OpenAI run (Orchestrator) timed out before action or completion.", "thread_id": thread_id, "run_id": current_run.id, "status": "timed_out_and_cancelled_attempted"}), 504
            
            time.sleep(1)
            current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
            app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} status: {current_run.status} (Attempt {polling_attempts})")

        if current_run.status == 'requires_action':
            app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} requires action (tool calls).")
            tool_outputs = []
            if current_run.required_action and current_run.required_action.type == "submit_tool_outputs":
                for tool_call in current_run.required_action.submit_tool_outputs.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        app.logger.error(f"{endpoint_name}: Failed to parse JSON arguments for tool {function_name} on Orchestrator run {current_run.id}: {tool_call.function.arguments}. Error: {e}", exc_info=True)
                        output = f"Error: Invalid JSON arguments provided for tool {function_name} by Orchestrator."
                    else:
                        app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} calling tool: {function_name}, Args: {arguments}")
                        output = ""
                        if function_name == "invoke_sustainability_assistant":
                            output = execute_sustainability_assistant_tool(query=arguments.get("query"), thread_id=thread_id)
                        elif function_name == "invoke_auditor_assistant":
                            # Pasamos el thread_id original del orquestador por si fuera necesario para logging o contexto futuro,
                            # aunque la función de herramienta ahora crea su propio hilo temporal.
                            output = execute_auditor_assistant_tool(task=arguments.get("task"), original_thread_id=thread_id)
                        else:
                            app.logger.warning(f"{endpoint_name}: Orchestrator Run {current_run.id} requested unknown tool function: {function_name}")
                            output = f"Error: Unknown tool function '{function_name}' requested by Orchestrator."
                    tool_outputs.append({"tool_call_id": tool_call.id, "output": str(output)})
            
            if tool_outputs:
                app.logger.info(f"{endpoint_name}: Submitting tool outputs for Orchestrator run {current_run.id} on thread {thread_id}: {tool_outputs}")
                try:
                    current_run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                        thread_id=thread_id, run_id=current_run.id, tool_outputs=tool_outputs
                    )
                    app.logger.info(f"{endpoint_name}: Tool outputs submitted for Orchestrator run {current_run.id}. Final status after tool poll: {current_run.status}")
                except Exception as e: 
                    app.logger.error(f"{endpoint_name}: Error submitting tool outputs or during poll for Orchestrator run {current_run.id} on thread {thread_id}: {e}", exc_info=True)
                    assistant_response_for_storage = f"Error submitting tool outputs for Orchestrator: {str(e)}"
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "OrchestratorToolError")
                    return jsonify({"error": f"Error submitting tool outputs for Orchestrator: {str(e)}", "thread_id": thread_id, "run_id": current_run.id}), 500
            else: 
                app.logger.warning(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} was 'requires_action' but no tool_outputs were generated/processed.")
                assistant_response_for_storage = "Orchestrator required action but no tool outputs were processed."
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "OrchestratorToolError")
                return jsonify({"error": "Orchestrator required action but no tool outputs were processed.", "thread_id": thread_id, "run_id": current_run.id, "run_status": current_run.status}), 500

        if current_run.status == 'completed':
            app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} completed.")
            messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            assistant_response = "No new response from Orchestrator for this run." 
            for msg in messages.data:
                if msg.run_id == current_run.id and msg.role == "assistant":
                    if msg.content:
                        assistant_response_parts = []
                        for content_block in msg.content:
                             if content_block.type == 'text':
                                assistant_response_parts.append(content_block.text.value)
                        assistant_response = "\n".join(assistant_response_parts).strip()
                        break
            
            app.logger.info(f"{endpoint_name}: Orchestrator final response for run {current_run.id} on thread {thread_id}: \"{assistant_response[:200]}...\"")
            assistant_response_for_storage = assistant_response 
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "Orchestrator")
            return jsonify({"response": assistant_response, "thread_id": thread_id, "run_id": current_run.id, "run_status": current_run.status})
        
        else: 
            app.logger.error(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} ended with unhandled status: {current_run.status}. Last error: {current_run.last_error}")
            error_details = str(current_run.last_error.message) if current_run.last_error else "No specific error details provided by API for Orchestrator run."
            assistant_response_for_storage = f"Orchestrator Run ended with status: {current_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "OrchestratorError")
            return jsonify({"error": f"Orchestrator Run ended with status: {current_run.status}", "details": error_details, "thread_id": thread_id, "run_id": current_run.id}), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred in Orchestrator endpoint: {e}", exc_info=True)
        _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
        if user_message_content is not None : 
             store_conversation_turn(_thread_id_for_except_log, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, current_run_id_for_storage, "OrchestratorException")
        return jsonify({"error": f"An internal server error occurred in Orchestrator endpoint: {str(e)}", "thread_id": _thread_id_for_except_log}), 500


# --- Endpoint para el Asistente de Sostenibilidad Directo (/chat_assistant) ---
# (La lógica interna de preguntar_asistente_sostenibilidad no necesita cambios importantes
# para el manejo de hilos temporales, ya que ya usa create_and_poll de forma aislada.
# Solo se han añadido las mejoras de manejo de thread_id no encontrado y logging)
@app.route('/chat_assistant', methods=['POST'])
def preguntar_asistente_sostenibilidad():
    endpoint_name = "/chat_assistant"
    app.logger.info(f"Received request for {endpoint_name} endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    data_from_request = None
    assistant_response_for_storage = "Error or no response generated by Sustainability Assistant."
    sustainability_run_id_for_storage = None

    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            return jsonify({"error": "Invalid request: payload must be JSON."}), 400

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id')

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")
        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            return jsonify({"error": "No message provided"}), 400

        app.logger.info(f"{endpoint_name}: Attempting to interact with Sustainability Assistant ({ASISTENTE_ID}) for thread: {thread_id or 'New Thread'}")
        
        original_thread_id_if_new_created = None
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Sustainability Assistant: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Sustainability Assistant: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Sustainability Assistant thread: {thread_id}")
            except openai.NotFoundError:
                app.logger.warning(f"{endpoint_name}: Thread {thread_id} not found for Sustainability Assistant. Creating a new one.")
                original_thread_id_if_new_created = thread_id
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created} with Sustainability Assistant, starting new session) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} for Sustainability Assistant after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Sustainability Assistant thread {thread_id}: {e}", exc_info=True)
                return jsonify({"error": f"Invalid or inaccessible thread_id for Sustainability Assistant: {thread_id}", "details": str(e)}), 400
        
        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message_content)
        app.logger.info(f"{endpoint_name}: Added user message to Sustainability Assistant thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Sustainability Assistant ({ASISTENTE_ID}) on thread {thread_id}")
        sustainability_run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASISTENTE_ID,
            instructions=f"Please answer the user's latest question: \"{user_message_content}\""
        )
        sustainability_run_id_for_storage = sustainability_run.id
        app.logger.info(f"{endpoint_name}: Sustainability Assistant Run {sustainability_run_id_for_storage} on thread {thread_id} completed with status: {sustainability_run.status}")

        if sustainability_run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            assistant_response = "No new response from Sustainability Assistant for this run."
            for msg in messages.data:
                if msg.run_id == sustainability_run_id_for_storage and msg.role == "assistant": 
                    if msg.content:
                        assistant_response_parts = []
                        for content_block in msg.content:
                            if content_block.type == 'text':
                                assistant_response_parts.append(content_block.text.value)
                        assistant_response = "\n".join(assistant_response_parts).strip()
                        break
            
            app.logger.info(f"{endpoint_name}: Sustainability Assistant final response for run {sustainability_run_id_for_storage} on thread {thread_id}: \"{assistant_response[:200]}...\"")
            assistant_response_for_storage = assistant_response 
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityAssistant")
            return jsonify({"response": assistant_response, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage, "run_status": sustainability_run.status})
        else:
            app.logger.error(f"{endpoint_name}: Sustainability Assistant Run {sustainability_run_id_for_storage} on thread {thread_id} ended with status: {sustainability_run.status}. Last error: {sustainability_run.last_error}")
            error_details = str(sustainability_run.last_error.message) if sustainability_run.last_error else "No specific error details."
            assistant_response_for_storage = f"Sustainability Assistant Run ended with status: {sustainability_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityAssistantError")
            return jsonify({"error": f"Sustainability Assistant Run ended with status: {sustainability_run.status}", "details": error_details, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage}), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
        if user_message_content is not None:
            store_conversation_turn(_thread_id_for_except_log, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, sustainability_run_id_for_storage, "SustainabilityAssistantException")
        return jsonify({"error": f"An internal server error occurred in {endpoint_name}: {str(e)}", "thread_id": _thread_id_for_except_log}), 500


# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    app.logger.info("Health check endpoint was called.")
    try:
        # Opcional: prueba de conectividad a Firestore si quieres un health check más profundo
        # list(db.collection(u'audit_trail').limit(1).stream())
        # app.logger.info("Firestore connectivity check successful for health check.")
        pass 
    except Exception as e:
        app.logger.error(f"Health check: Firestore connectivity test failed. Error: {e}", exc_info=True)
        return jsonify({"status": "unhealthy", "reason": "Potential backend connectivity issue"}), 503 # Usar 503 Service Unavailable
    
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    app.logger.info("Starting Flask development server with debug mode.")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
