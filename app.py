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
                # Concatenar todos los bloques de texto si los hubiera
                response_text_parts = []
                for content_block in messages.data[0].content:
                    if content_block.type == 'text':
                        response_text_parts.append(content_block.text.value)
                response_text = "\n".join(response_text_parts).strip()

                if not response_text: # Verificar si después de unir todo, está vacío
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
                text_parts = []
                for content_block in msg.content:
                    if content_block.type == 'text':
                        text_parts.append(content_block.text.value)
                
                raw_response_text = "\n".join(text_parts).strip()
                if raw_response_text:
                    assistant_response_text = raw_response_text
                else: # Si text_parts estaba vacío o solo contenía strings vacíos
                    app.logger.warning(f"{endpoint_name}: Assistant message for run {final_run_id} had text content blocks but resulted in empty text.")
                    assistant_response_text = "El asistente proporcionó una respuesta vacía." # O mantener el default
                break # Salir después de encontrar el primer mensaje relevante del asistente
    
    if assistant_response_text == "No new response from assistant for this run.":
        app.logger.warning(f"{endpoint_name}: No message from assistant role found for run {final_run_id}.")

    return assistant_response_text.strip()


# --- Endpoint Principal para el Asistente Auditor-Orquestador ---
@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    endpoint_name = "/chat_auditor"
    app.logger.info(f"Received request for {endpoint_name} (Main Auditor-Orchestrator) endpoint from {request.remote_addr}")
    user_message_content = None
    thread_id = None
    data_from_request = None
    assistant_response_for_storage = "Error or no response generated by Main Auditor-Orchestrator."
    # citations_for_storage = [] # Ya no se usa para extraer citas
    current_run_id_for_storage = None
    response_payload = {} 
    http_status_code = 200
    final_run_status = "unknown"


    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            response_payload = {"error": "Invalid request: payload must be JSON."}
            http_status_code = 400
            # No es necesario llamar a store_conversation_turn aquí, ya que no hay interacción de usuario/asistente
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), http_status_code

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id')

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")

        if not user_message_content: # Asumimos que siempre habrá un mensaje si la petición es válida
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            response_payload = {"error": "No message provided"}
            http_status_code = 400
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), http_status_code
            
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
                original_thread_id_if_new_created = thread_id # Guardar para log
                thread = client.beta.threads.create()
                thread_id = thread.id # Usar el nuevo thread_id
                # Considerar si el mensaje del usuario debe modificarse para reflejar esto.
                # user_message_content = f"(Original Thread ID {original_thread_id_if_new_created} not found, new session started) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e: # Otras excepciones al recuperar el hilo
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Main Auditor-Orchestrator thread {thread_id}: {e}", exc_info=True)
                response_payload = {"error": f"Invalid or inaccessible thread_id for Main Auditor-Orchestrator: {thread_id}", "details": str(e)}
                http_status_code = 400 # Podría ser 500 si es un error del servidor al intentar recuperar
                # No guardar en Firestore todavía, ya que el mensaje del usuario no se ha procesado.
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), http_status_code

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message_content
        )
        app.logger.info(f"{endpoint_name}: Added user message to Main Auditor-Orchestrator thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Main Auditor-Orchestrator ({AUDIT_ORCHESTRATOR_ASSISTANT_ID}) on thread {thread_id}")
        current_run = client.beta.threads.runs.create( # No usar create_and_poll aquí para manejar 'requires_action'
            thread_id=thread_id,
            assistant_id=AUDIT_ORCHESTRATOR_ASSISTANT_ID
        )
        current_run_id_for_storage = current_run.id
        app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} created for thread {thread_id}. Initial status: {current_run.status}")
        
        polling_attempts = 0
        max_polling_attempts_total = 120 # Total 2 minutos de polling (120 * 1s)
        max_polling_attempts_before_action_check = 60 # Revisar acción después de 1 min si sigue en progreso
        max_tool_call_iterations = 5 # Permitir hasta 5 iteraciones de herramientas
        tool_iterations_count = 0
        
        final_run_status = current_run.status

        # Bucle de polling mejorado
        start_time = time.time()
        timeout_seconds = 180 # Timeout general de 3 minutos para todo el proceso del run

        while current_run.status in ['queued', 'in_progress', 'requires_action']:
            if time.time() - start_time > timeout_seconds:
                app.logger.warning(f"{endpoint_name}: Run {current_run.id} on thread {thread_id} exceeded total timeout of {timeout_seconds}s. Last status: {current_run.status}")
                assistant_response_for_storage = f"OpenAI run (Main Auditor-Orchestrator) timed out after {timeout_seconds}s. Status: {current_run.status}"
                final_run_status = "timed_out_overall"
                try:
                    client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                    assistant_response_for_storage += " Run cancelled."
                    final_run_status = "timed_out_and_cancelled"
                except Exception as cancel_err:
                    assistant_response_for_storage += " Failed to cancel run."
                    final_run_status = "timed_out_cancel_failed"
                break # Salir del bucle while

            time.sleep(1) # Espera de 1 segundo entre polls
            current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
            final_run_status = current_run.status
            app.logger.info(f"{endpoint_name}: Polling Run {current_run.id}, Status: {current_run.status}")

            if current_run.status == 'requires_action':
                if tool_iterations_count >= max_tool_call_iterations:
                    app.logger.error(f"{endpoint_name}: Exceeded max tool call iterations ({max_tool_call_iterations}) for run {current_run.id}.")
                    assistant_response_for_storage = "Exceeded max tool call iterations."
                    final_run_status = "max_tool_iterations_exceeded"
                    break # Salir del bucle while
                
                tool_iterations_count += 1
                app.logger.info(f"{endpoint_name}: Run {current_run.id} requires action (Iteration {tool_iterations_count}).")
                
                tool_outputs = []
                if current_run.required_action and current_run.required_action.type == "submit_tool_outputs":
                    for tool_call in current_run.required_action.submit_tool_outputs.tool_calls:
                        function_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            app.logger.error(f"{endpoint_name}: Failed to parse JSON arguments for tool {function_name}: {tool_call.function.arguments}. Error: {e}", exc_info=True)
                            output = f"Error: Invalid JSON arguments for tool {function_name}."
                        else:
                            app.logger.info(f"{endpoint_name}: Calling tool: {function_name}, Args: {arguments}")
                            if function_name == "invoke_sustainability_expert":
                                output = execute_invoke_sustainability_expert(query=arguments.get("query"), original_thread_id=thread_id)
                            else:
                                app.logger.warning(f"{endpoint_name}: Unknown tool function: {function_name}")
                                output = f"Error: Unknown tool function '{function_name}'."
                        tool_outputs.append({"tool_call_id": tool_call.id, "output": str(output)})
                
                if tool_outputs:
                    try:
                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id, run_id=current_run.id, tool_outputs=tool_outputs
                        )
                        app.logger.info(f"{endpoint_name}: Tool outputs submitted for run {current_run.id}. Waiting for run to continue.")
                        # El run volverá a 'queued' o 'in_progress', el bucle continuará
                    except Exception as e:
                        app.logger.error(f"{endpoint_name}: Error submitting tool outputs for run {current_run.id}: {e}", exc_info=True)
                        assistant_response_for_storage = f"Error submitting tool outputs: {str(e)}"
                        final_run_status = "tool_submission_error"
                        break # Salir del bucle while
                else:
                    app.logger.warning(f"{endpoint_name}: Run {current_run.id} was 'requires_action' but no tool_outputs were generated.")
                    # Esto podría ser un error si se esperaban herramientas, o normal si el asistente decidió no usar ninguna herramienta.
                    # Considerar si esto debe ser un error fatal o si el run puede continuar.
                    # Por ahora, se asume que si requiere acción, se deben generar outputs.
                    assistant_response_for_storage = "Assistant required action but no tool outputs were processed."
                    final_run_status = "requires_action_no_outputs"
                    break # Salir del bucle while

        # Fin del bucle de polling
        
        if final_run_status == 'completed':
            app.logger.info(f"{endpoint_name}: Run {current_run.id} on thread {thread_id} completed.")
            messages = client.beta.threads.messages.list(
                thread_id=thread_id,
                run_id=current_run.id, # Importante para obtener solo mensajes de este run
                order='desc',
                limit=10 # Suficiente para encontrar el último mensaje del asistente
                # No es necesario expand=['file_citations'] si no las vamos a procesar
            )
            
            assistant_response_text = process_assistant_message_without_citations(messages.data, current_run.id, endpoint_name)
            
            assistant_response_for_storage = assistant_response_text
            # No hay citations_for_storage aquí

            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestrator") # No pasar citations
            response_payload = {
                "response": assistant_response_text, 
                # "citations": [], # Omitir o enviar lista vacía
                "thread_id": thread_id, 
                "run_id": current_run.id, 
                "run_status": final_run_status
            }
            http_status_code = 200
        
        else: # Run no completado (failed, cancelled, timed_out, etc.)
            app.logger.error(f"{endpoint_name}: Run {current_run_id_for_storage} on thread {thread_id} ended with status: {final_run_status}. Current Run Object: {current_run}")
            error_message = f"Run ended with status: {final_run_status}."
            if current_run and current_run.last_error:
                error_message += f" Last Error: Code={current_run.last_error.code}, Message={current_run.last_error.message}"
            elif assistant_response_for_storage == "Error or no response generated by Main Auditor-Orchestrator.": # Si no se actualizó antes
                 assistant_response_for_storage = error_message # Usar el mensaje de error del run status

            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id_for_storage, "MainAuditOrchestratorError")
            response_payload = {
                "error": "OpenAI run did not complete successfully.", 
                "details": assistant_response_for_storage,
                "thread_id": thread_id, 
                "run_id": current_run_id_for_storage, 
                "run_status": final_run_status
            }
            http_status_code = 500 # Error genérico del servidor si el run no completó

        app.logger.info(f"{endpoint_name}: Responding to client with JSON: {json.dumps(response_payload)}")
        return jsonify(response_payload), http_status_code

    except openai.APIConnectionError as e:
        app.logger.error(f"{endpoint_name}: OpenAI APIConnectionError: {e}", exc_info=True)
        response_payload = {"error": "Failed to connect to OpenAI API.", "details": str(e)}
        http_status_code = 503
    except openai.RateLimitError as e:
        app.logger.error(f"{endpoint_name}: OpenAI RateLimitError: {e}", exc_info=True)
        response_payload = {"error": "Rate limit exceeded for OpenAI API.", "details": str(e)}
        http_status_code = 429
    except openai.APIStatusError as e: 
        app.logger.error(f"{endpoint_name}: OpenAI APIStatusError: status={e.status_code}, response={e.response}, message={e.message}", exc_info=True)
        response_payload = {"error": f"OpenAI API error (status {e.status_code}).", "details": e.message}
        http_status_code = e.status_code if isinstance(e.status_code, int) and e.status_code >= 400 else 500
    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        error_message_for_response = f"An internal server error occurred: {str(e)}"
        response_payload = {"error": error_message_for_response}
        http_status_code = 500
    
    # Common error handling for payload and storage
    _thread_id_for_except_log = thread_id or (data_from_request.get('thread_id') if data_from_request else "unknown_thread_on_error")
    
    if 'thread_id' not in response_payload: response_payload['thread_id'] = _thread_id_for_except_log
    if 'run_id' not in response_payload and current_run_id_for_storage: response_payload['run_id'] = current_run_id_for_storage
    if 'run_status' not in response_payload and final_run_status: response_payload['run_status'] = final_run_status

    # Guardar el turno de conversación en caso de error si el mensaje del usuario se procesó
    if user_message_content is not None: # Solo si user_message_content fue inicializado
        assistant_error_response = response_payload.get("details", response_payload.get("error", "Unhandled API Exception in main endpoint"))
        store_conversation_turn(
            _thread_id_for_except_log, 
            user_message_content, 
            assistant_error_response, 
            endpoint_name, 
            current_run_id_for_storage, 
            "MainAuditOrchestratorException" # O un nombre de asistente más específico para errores
        ) # No se pasan citas
    
    app.logger.info(f"{endpoint_name}: Responding with JSON error: {json.dumps(response_payload)}")
    return jsonify(response_payload), http_status_code


# --- Endpoint para el Asistente Experto en Sostenibilidad Directo ---
@app.route('/chat_assistant', methods=['POST'])
def chat_with_sustainability_expert():
    endpoint_name = "/chat_assistant"
    app.logger.info(f"Received request for {endpoint_name} (Sustainability Expert) endpoint from {request.remote_addr}")
    user_message_content = None
    thread_id = None
    data_from_request = None
    assistant_response_for_storage = "Error or no response generated by Sustainability Expert."
    # citations_for_storage = [] # Ya no se usa
    sustainability_run_id_for_storage = None
    response_payload = {}
    http_status_code = 200
    final_run_status = "unknown"

    try:
        data_from_request = request.json
        if not data_from_request:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            response_payload = {"error": "Invalid request: payload must be JSON."}
            http_status_code = 400
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), http_status_code

        user_message_content = data_from_request.get('message')
        thread_id = data_from_request.get('thread_id')

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")
        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            response_payload = {"error": "No message provided"}
            http_status_code = 400
            app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
            return jsonify(response_payload), http_status_code

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
                # user_message_content = f"(Original Thread ID {original_thread_id_if_new_created} not found, new session started with Sustainability Expert) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} for Sustainability Expert after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Sustainability Expert thread {thread_id}: {e}", exc_info=True)
                response_payload = {"error": f"Invalid or inaccessible thread_id for Sustainability Expert: {thread_id}", "details": str(e)}
                http_status_code = 400
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), http_status_code
        
        client.beta.threads.messages.create(
            thread_id=thread_id, 
            role="user", 
            content=user_message_content
        )
        app.logger.info(f"{endpoint_name}: Added user message to Sustainability Expert thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Sustainability Expert ({SUSTAINABILITY_EXPERT_ASSISTANT_ID}) on thread {thread_id}")
        
        # Usar create_and_poll para el asistente experto directo, asumiendo que no usa tools que requieran submit_tool_outputs
        sustainability_run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=SUSTAINABILITY_EXPERT_ASSISTANT_ID,
            instructions=f"Please answer the user's latest question: \"{user_message_content}\"",
            poll_interval_ms=1000, # Verificar cada segundo
            timeout=180.0 # Timeout de 3 minutos para la operación create_and_poll
        )
        sustainability_run_id_for_storage = sustainability_run.id
        final_run_status = sustainability_run.status
        app.logger.info(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} polling completed with status: {final_run_status}")

        if final_run_status == 'completed':
            messages = client.beta.threads.messages.list(
                thread_id=thread_id,
                run_id=sustainability_run_id_for_storage,
                order='desc',
                limit=10
                # No es necesario expand=['file_citations']
            )
            
            assistant_response_text = process_assistant_message_without_citations(messages.data, sustainability_run_id_for_storage, endpoint_name)

            app.logger.info(f"{endpoint_name}: Sustainability Expert final response for run {sustainability_run_id_for_storage} on thread {thread_id}: \"{assistant_response_text[:200]}...\"")
            assistant_response_for_storage = assistant_response_text
            # No hay citations_for_storage aquí

            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpert") # No pasar citations
            response_payload = {
                "response": assistant_response_text, 
                # "citations": [], # Omitir o enviar lista vacía
                "thread_id": thread_id, 
                "run_id": sustainability_run_id_for_storage, 
                "run_status": final_run_status
            }
            http_status_code = 200
        else: 
            app.logger.error(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} ended with status: {final_run_status}. Run Object: {sustainability_run}")
            error_message = f"Sustainability Expert Run ended with status: {final_run_status}."
            if sustainability_run and sustainability_run.last_error:
                error_message += f" Last Error: Code={sustainability_run.last_error.code}, Message={sustainability_run.last_error.message}"
            elif final_run_status == 'requires_action': # Inesperado para create_and_poll sin tools
                 error_message = f"Run ended in 'requires_action' status unexpectedly. This assistant might be misconfigured if it's not supposed to use tools."

            assistant_response_for_storage = error_message
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertError")
            response_payload = {
                "error": "Sustainability Expert run did not complete successfully.", 
                "details": assistant_response_for_storage, 
                "thread_id": thread_id, 
                "run_id": sustainability_run_id_for_storage,
                "run_status": final_run_status
                }
            http_status_code = 500
        
        app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
        return jsonify(response_payload), http_status_code

    except openai.APIConnectionError as e:
        app.logger.error(f"{endpoint_name}: OpenAI APIConnectionError: {e}", exc_info=True)
        response_payload = {"error": "Failed to connect to OpenAI API.", "details": str(e)}
        http_status_code = 503
    except openai.RateLimitError as e:
        app.logger.error(f"{endpoint_name}: OpenAI RateLimitError: {e}", exc_info=True)
        response_payload = {"error": "Rate limit exceeded for OpenAI API.", "details": str(e)}
        http_status_code = 429
    except openai.APIStatusError as e: 
        app.logger.error(f"{endpoint_name}: OpenAI APIStatusError: status={e.status_code}, response={e.response}, message={e.message}", exc_info=True)
        response_payload = {"error": f"OpenAI API error (status {e.status_code}).", "details": e.message}
        http_status_code = e.status_code if isinstance(e.status_code, int) and e.status_code >= 400 else 500
    except Exception as e: # Captura otras excepciones, incluyendo timeouts de create_and_poll
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        error_message_for_response = f"An internal server error occurred: {str(e)}"
        # Verificar si es un timeout de la librería de OpenAI para create_and_poll
        if "timed out" in str(e).lower(): # Asumiendo que 'create_and_poll' podría lanzar un error con "timed out"
            final_run_status_on_exception = "timed_out_library_poll" # Estado personalizado
            error_message_for_response = f"The request to the Sustainability Expert (create_and_poll) timed out. Run ID (if available): {sustainability_run_id_for_storage or 'N/A'}"
            http_status_code = 504 # Gateway Timeout
        else:
            http_status_code = 500
        response_payload = {"error": error_message_for_response}

    # Common error handling for payload and storage
    _thread_id_for_except_log = thread_id or (data_from_request.get('thread_id') if data_from_request else "unknown_thread_on_error")

    if 'thread_id' not in response_payload: response_payload['thread_id'] = _thread_id_for_except_log
    if 'run_id' not in response_payload and sustainability_run_id_for_storage: response_payload['run_id'] = sustainability_run_id_for_storage
    # Usar final_run_status_on_exception si se definió, sino el final_run_status general
    current_final_status = final_run_status_on_exception if 'final_run_status_on_exception' in locals() else final_run_status
    if 'run_status' not in response_payload: response_payload['run_status'] = current_final_status


    if user_message_content is not None:
        assistant_error_response = response_payload.get("details", response_payload.get("error", "Unhandled API Exception in direct assistant endpoint"))
        store_conversation_turn(
            _thread_id_for_except_log, 
            user_message_content, 
            assistant_error_response, 
            endpoint_name, 
            sustainability_run_id_for_storage, 
            "SustainabilityExpertException"
        ) # No se pasan citas
    
    app.logger.info(f"{endpoint_name}: Responding with JSON error: {json.dumps(response_payload)}")
    return jsonify(response_payload), http_status_code


# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    app.logger.info("Health check endpoint was called.")
    response_payload = {}
    try:
        # client.models.list(limit=1) # Opcional: prueba de conectividad con OpenAI
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
    port = int(os.environ.get("PORT", 8080)) 
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.logger.info(f"Starting Flask server on port {port} with debug mode: {debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)