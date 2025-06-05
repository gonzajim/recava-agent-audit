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
        if citations is not None: # Guardar citas si se proporcionan
            data_to_store['citations'] = citations
        
        doc_ref.set(data_to_store)
        app.logger.info(f"Firestore: Stored conversation turn for thread {data_to_store['thread_id']} from {endpoint_source} in document {doc_ref.id}.")
    except Exception as e:
        app.logger.error(f"Firestore: Failed to store conversation turn for thread {thread_id}. Error: {e}", exc_info=True)

# --- Implementación de Herramienta para el Auditor-Orquestador ---
# (execute_invoke_sustainability_expert se mantiene igual, ya que su respuesta es consumida internamente
# por el orquestador. Si este experto también necesitara devolver citas al orquestador de esta manera,
# se requerirían cambios similares allí. Por ahora, se asume que su respuesta es texto plano.)
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
                run_id=run.id,
                order='desc',
                limit=1,
                expand=['file_citations']
            )
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

# --- Función auxiliar para procesar mensajes y extraer citas ---
# --- Función auxiliar para procesar mensajes y extraer citas ---
def process_assistant_message_with_citations(messages_data, final_run_id, endpoint_name):
    assistant_response_text = "No new response from assistant for this run."
    full_assistant_response_object = None
    citations_extracted = []
    raw_response_text_for_processing = "" # Texto original del asistente antes de insertar marcadores

    for msg in messages_data:
        if msg.run_id == final_run_id and msg.role == "assistant":
            if msg.content:
                text_parts = []
                # Iterar sobre todos los bloques de contenido del mensaje
                for content_block_idx, content_block in enumerate(msg.content):
                    if content_block.type == 'text':
                        text_parts.append(content_block.text.value)
                        # Considerar el primer bloque de texto con anotaciones para el procesamiento de citas
                        # O si es el único bloque de texto.
                        if not full_assistant_response_object and hasattr(content_block.text, 'annotations') and content_block.text.annotations:
                            full_assistant_response_object = content_block # Guardamos el TextContentBlock
                        elif not full_assistant_response_object and len(msg.content) == 1: # Si solo hay un bloque y es texto
                            full_assistant_response_object = content_block


                raw_response_text_for_processing = "\n".join(text_parts).strip()
                assistant_response_text = raw_response_text_for_processing 
                break 

    if not raw_response_text_for_processing and assistant_response_text == "No new response from assistant for this run.":
        app.logger.warning(f"{endpoint_name}: No text content found in assistant's message for run {final_run_id}.")
        return assistant_response_text, citations_extracted # Devuelve respuesta vacía y sin citas

    # Procesar anotaciones si existen en el objeto guardado
    if full_assistant_response_object and full_assistant_response_object.type == 'text' and hasattr(full_assistant_response_object.text, 'annotations') and full_assistant_response_object.text.annotations:
        annotations = full_assistant_response_object.text.annotations
        
        # Necesitamos trabajar sobre el texto del content_block específico que tiene las anotaciones
        # ya que los start_index y end_index son relativos a ese bloque.
        # Si concatenamos varios bloques, los índices no coincidirán.
        # Aquí asumimos que las anotaciones importantes están en `raw_response_text_for_processing`
        # si este vino del `full_assistant_response_object`.
        # Si `raw_response_text_for_processing` es una concatenación de múltiples bloques,
        # y las anotaciones solo pertenecen a uno, este enfoque de reemplazo global podría ser problemático.
        # Por simplicidad, continuaremos con el reemplazo sobre `raw_response_text_for_processing`,
        # asumiendo que el texto relevante para las anotaciones está contenido ahí y los índices son manejables.
        # Una solución más robusta implicaría procesar cada content_block con sus anotaciones por separado.

        # Ordenar anotaciones por start_index para un reemplazo consistente y no solapado
        # Es crucial que los reemplazos se hagan de atrás hacia adelante o usando offsets si se hacen hacia adelante.
        # O construir una nueva cadena.
        
        processed_text_parts = []
        current_pos_in_raw_text = 0
        citation_counter = 1 

        # Asegurarnos de que las anotaciones son solo del tipo file_citation relevante
        # y ordenarlas para procesarlas correctamente
        file_citation_annotations = []
        for ann_idx, annotation in enumerate(annotations):
            if hasattr(annotation, 'file_citation') and annotation.file_citation and hasattr(annotation.file_citation, 'file_id'):
                 file_citation_annotations.append(annotation)
        
        file_citation_annotations.sort(key=lambda x: x.start_index)


        for annotation in file_citation_annotations:
            # Añadir el texto antes de la anotación actual
            # Los índices start_index y end_index se refieren al texto del content_block específico.
            # Si raw_response_text_for_processing es solo ese content_block, esto es correcto.
            processed_text_parts.append(raw_response_text_for_processing[current_pos_in_raw_text:annotation.start_index])
            
            marker = f" [{citation_counter}]"
            processed_text_parts.append(marker)
            
            cited_file_id = annotation.file_citation.file_id
            
            # Acceso seguro al atributo 'quote'
            quote_from_file = getattr(annotation.file_citation, 'quote', None)
            
            if quote_from_file is None:
                app.logger.warning(f"{endpoint_name}: Annotation file_citation for file_id '{cited_file_id}' (annotation text: '{annotation.text}') did not contain a 'quote' attribute. Full file_citation object: {str(annotation.file_citation)}")
                # Usar el texto de la anotación del LLM como fallback si 'quote' no está.
                # Esto significa que el texto en la respuesta del LLM se usará como si fuera la "cita".
                quote_from_file = annotation.text  # O un placeholder como "Referencia directa al archivo (cita específica no extraída)."
            
            citations_extracted.append({
                "marker": marker,
                "text_in_response": annotation.text, 
                "file_id": cited_file_id,
                "quote_from_file": quote_from_file,
            })
            app.logger.info(f"{endpoint_name}: Found file citation: marker='{marker}', text_in_response='{annotation.text}', file_id='{cited_file_id}', quote_from_file='{str(quote_from_file)[:100]}...'")
            
            current_pos_in_raw_text = annotation.end_index
            citation_counter += 1
        
        # Añadir cualquier texto restante después de la última anotación
        processed_text_parts.append(raw_response_text_for_processing[current_pos_in_raw_text:])
        assistant_response_text = "".join(processed_text_parts)

    elif not full_assistant_response_object and raw_response_text_for_processing:
        app.logger.info(f"{endpoint_name}: Assistant message for run {final_run_id} found, but no annotations detected or structure not as expected. Returning raw text.")
        # assistant_response_text ya tiene el raw_response_text_for_processing
    elif assistant_response_text != "No new response from assistant for this run.":
        # Hay texto pero no se procesaron anotaciones (quizás no había o no se detectó full_assistant_response_object)
        app.logger.info(f"{endpoint_name}: Assistant response text available but no annotations were processed. Text: {assistant_response_text[:100]}...")


    return assistant_response_text.strip(), citations_extracted


# --- Endpoint Principal para el Asistente Auditor-Orquestador ---
@app.route('/chat_auditor', methods=['POST'])
def chat_with_main_audit_orchestrator():
    endpoint_name = "/chat_auditor"
    app.logger.info(f"Received request for {endpoint_name} (Main Auditor-Orchestrator) endpoint from {request.remote_addr}")
    user_message_content = None
    thread_id = None
    data_from_request = None
    assistant_response_for_storage = "Error or no response generated by Main Auditor-Orchestrator."
    citations_for_storage = []
    current_run_id_for_storage = None
    response_payload = {} 
    http_status_code = 200

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
        # attachments = data_from_request.get('attachments') # Para uso futuro si se suben archivos directamente aquí

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")

        if not user_message_content:
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
                original_thread_id_if_new_created = thread_id
                thread = client.beta.threads.create()
                thread_id = thread.id
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created}, starting new session) {user_message_content}"
                app.logger.info(f"{endpoint_name}: Created new thread {thread_id} after failing to retrieve {original_thread_id_if_new_created}.")
            except Exception as e:
                app.logger.error(f"{endpoint_name}: Failed to retrieve existing Main Auditor-Orchestrator thread {thread_id}: {e}", exc_info=True)
                response_payload = {"error": f"Invalid or inaccessible thread_id for Main Auditor-Orchestrator: {thread_id}", "details": str(e)}
                http_status_code = 400
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), http_status_code

        # TODO: Manejar 'attachments' si se envían desde el frontend al crear el mensaje.
        # Por ahora, se asume que los archivos se suben y asocian al asistente o hilo por otros medios si es RAG.
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message_content
            # attachments=attachments if attachments else None # Ejemplo si se pasan attachments
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
        
        final_run_status = current_run.status

        while current_run.status in ['queued', 'in_progress', 'requires_action'] and tool_iterations_count < max_tool_call_iterations :
            final_run_status = current_run.status
            if current_run.status in ['queued', 'in_progress']:
                polling_attempts += 1
                if polling_attempts > max_polling_attempts_before_action:
                    app.logger.warning(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} timed out waiting. Last status: {current_run.status}")
                    assistant_response_for_storage = f"OpenAI run (Main Auditor-Orchestrator) timed out. Status: {current_run.status}"
                    try:
                        app.logger.info(f"{endpoint_name}: Attempting to cancel run {current_run.id} due to polling timeout.")
                        client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                        app.logger.info(f"{endpoint_name}: Successfully cancelled run {current_run.id}.")
                        assistant_response_for_storage += " Run cancelled."
                        final_run_status = "timed_out_and_cancelled"
                    except Exception as cancel_err:
                        app.logger.error(f"{endpoint_name}: Failed to cancel run {current_run.id}: {cancel_err}", exc_info=True)
                        assistant_response_for_storage += " Failed to cancel run."
                        final_run_status = "timed_out_cancel_failed"
                    
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorTimeout")
                    response_payload = {"error": "OpenAI run (Main Auditor-Orchestrator) timed out.", "thread_id": thread_id, "run_id": current_run.id, "run_status": final_run_status}
                    http_status_code = 504
                    app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                    return jsonify(response_payload), http_status_code
                
                time.sleep(1) # Espera antes de volver a consultar
                current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
                app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} status: {current_run.status} (Polling Attempt {polling_attempts})")

            if current_run.status == 'requires_action':
                tool_iterations_count +=1
                polling_attempts = 0 # Resetear contador de polling
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
                        time.sleep(0.5) # Dar tiempo a que el run se re-enquee
                        current_run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id) # Actualizar estado del run
                    except Exception as e:
                        app.logger.error(f"{endpoint_name}: Error submitting tool outputs for run {current_run.id} on thread {thread_id}: {e}", exc_info=True)
                        assistant_response_for_storage = f"Error submitting tool outputs: {str(e)}"
                        store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorToolError")
                        response_payload = {"error": f"Error submitting tool outputs: {str(e)}", "thread_id": thread_id, "run_id": current_run.id}
                        http_status_code = 500
                        app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                        return jsonify(response_payload), http_status_code
                else:
                    app.logger.warning(f"{endpoint_name}: Run {current_run.id} on thread {thread_id} was 'requires_action' but no tool_outputs were generated/processed.")
                    assistant_response_for_storage = "Auditor-Orchestrator required action but no tool outputs were processed."
                    final_run_status = "requires_action_no_tool_outputs"
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorToolError")
                    response_payload = {"error": "Auditor-Orchestrator required action but no tool outputs were processed.", "thread_id": thread_id, "run_id": current_run.id, "run_status": final_run_status}
                    http_status_code = 500
                    app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                    return jsonify(response_payload), http_status_code
            
            if tool_iterations_count >= max_tool_call_iterations:
                app.logger.error(f"{endpoint_name}: Exceeded max tool call iterations ({max_tool_call_iterations}) for run {current_run.id}.")
                assistant_response_for_storage = "Exceeded max tool call iterations."
                final_run_status = "max_tool_iterations_exceeded"
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorMaxToolCalls")
                response_payload = {"error": "Exceeded max tool call iterations.", "thread_id": thread_id, "run_id": current_run.id, "run_status": final_run_status}
                http_status_code = 500
                app.logger.info(f"{endpoint_name}: Responding with JSON: {json.dumps(response_payload)}")
                return jsonify(response_payload), http_status_code
        
        final_run_status = current_run.status # Actualizar estado final del run

        if final_run_status == 'completed':
            app.logger.info(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} completed.")
            messages = client.beta.threads.messages.list(
                thread_id=thread_id,
                run_id=current_run.id,
                order='desc',
                limit=10,
                expand=['file_citations']
            )
            
            assistant_response_text, citations_extracted = process_assistant_message_with_citations(messages.data, current_run.id, endpoint_name)
            
            assistant_response_for_storage = assistant_response_text
            citations_for_storage = citations_extracted

            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestrator", citations=citations_for_storage)
            response_payload = {
                "response": assistant_response_text, 
                "citations": citations_extracted,
                "thread_id": thread_id, 
                "run_id": current_run.id, 
                "run_status": final_run_status
            }
            http_status_code = 200
        
        else: # 'failed', 'cancelled', 'expired', etc.
            app.logger.error(f"{endpoint_name}: Main Auditor-Orchestrator Run {current_run.id} on thread {thread_id} ended with unhandled/final status: {final_run_status}. Last error: {current_run.last_error}")
            error_details_obj = current_run.last_error
            error_message = "An unexpected error occurred."
            if error_details_obj:
                error_message = f"Error Code: {error_details_obj.code}. Message: {error_details_obj.message}"
            else:
                error_message = f"Run ended in status {final_run_status} without specific error details."

            assistant_response_for_storage = f"Main Auditor-Orchestrator Run ended with status: {final_run_status}. Details: {error_message}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run.id, "MainAuditOrchestratorError")
            response_payload = {"error": f"Main Auditor-Orchestrator Run ended with status: {final_run_status}", "details": error_message, "thread_id": thread_id, "run_id": current_run.id, "run_status": final_run_status}
            http_status_code = 500

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
    except openai.APIStatusError as e: # More generic OpenAI API errors
        app.logger.error(f"{endpoint_name}: OpenAI APIStatusError: status={e.status_code}, response={e.response}, message={e.message}", exc_info=True)
        response_payload = {"error": f"OpenAI API error (status {e.status_code}).", "details": e.message}
        http_status_code = e.status_code if e.status_code else 500
    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred in Main Auditor-Orchestrator endpoint: {e}", exc_info=True)
        error_message_for_response = f"An internal server error occurred: {str(e)}"
        response_payload = {"error": error_message_for_response}
        http_status_code = 500
    
    # Asegurar que thread_id se incluya en la respuesta de error si está disponible
    _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
    if 'thread_id' not in response_payload and _thread_id_for_except_log:
        response_payload['thread_id'] = _thread_id_for_except_log
    if 'run_id' not in response_payload and current_run_id_for_storage:
        response_payload['run_id'] = current_run_id_for_storage
    if 'run_status' not in response_payload and final_run_status:
        response_payload['run_status'] = final_run_status


    # Guardar el turno de conversación incluso en caso de error, si es posible
    if user_message_content is not None: # Solo si el mensaje del usuario fue procesado
        assistant_error_response = response_payload.get("error", "Unhandled API Exception")
        if response_payload.get("details"):
             assistant_error_response += f" Details: {response_payload.get('details')}"
        store_conversation_turn(_thread_id_for_except_log, user_message_content, assistant_error_response, endpoint_name, current_run_id_for_storage, "MainAuditOrchestratorException", citations_for_storage)
    
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
    citations_for_storage = []
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
        # attachments = data_from_request.get('attachments') # Para uso futuro

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
                user_message_content = f"(Attempted to resume non-existent thread {original_thread_id_if_new_created} with Sustainability Expert, starting new session) {user_message_content}"
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
            # attachments=attachments if attachments else None # Ejemplo
        )
        app.logger.info(f"{endpoint_name}: Added user message to Sustainability Expert thread {thread_id}: \"{user_message_content}\"")

        app.logger.info(f"{endpoint_name}: Creating run for Sustainability Expert ({SUSTAINABILITY_EXPERT_ASSISTANT_ID}) on thread {thread_id}")
        sustainability_run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=SUSTAINABILITY_EXPERT_ASSISTANT_ID,
            instructions=f"Please answer the user's latest question: \"{user_message_content}\"",
            # timeout=60 # Ejemplo de timeout para create_and_poll (en segundos)
        )
        sustainability_run_id_for_storage = sustainability_run.id
        final_run_status = sustainability_run.status
        app.logger.info(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} polling completed with status: {final_run_status}")

        if final_run_status == 'completed':
            messages = client.beta.threads.messages.list(
                thread_id=thread_id,
                run_id=sustainability_run_id_for_storage,
                order='desc',
                limit=10,
                expand=['file_citations']
            )
            
            assistant_response_text, citations_extracted = process_assistant_message_with_citations(messages.data, sustainability_run_id_for_storage, endpoint_name)

            app.logger.info(f"{endpoint_name}: Sustainability Expert final response for run {sustainability_run_id_for_storage} on thread {thread_id}: \"{assistant_response_text[:200]}...\"")
            assistant_response_for_storage = assistant_response_text
            citations_for_storage = citations_extracted

            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpert", citations=citations_for_storage)
            response_payload = {
                "response": assistant_response_text, 
                "citations": citations_extracted,
                "thread_id": thread_id, 
                "run_id": sustainability_run_id_for_storage, 
                "run_status": final_run_status
            }
            http_status_code = 200
        else: # 'failed', 'cancelled', 'expired', 'requires_action' (inesperado con create_and_poll si no hay tools)
            app.logger.error(f"{endpoint_name}: Sustainability Expert Run {sustainability_run_id_for_storage} on thread {thread_id} ended with status: {final_run_status}. Last error: {sustainability_run.last_error}")
            error_details_obj = sustainability_run.last_error
            error_message = "An unexpected error occurred with the Sustainability Expert."
            if error_details_obj:
                error_message = f"Error Code: {error_details_obj.code}. Message: {error_details_obj.message}"
            elif final_run_status == 'requires_action': # Esto sería inesperado si el asistente no tiene tools habilitadas
                 error_message = f"Run ended in 'requires_action' status unexpectedly. This assistant might require tool configuration."
            else:
                error_message = f"Run ended in status {final_run_status} without specific error details."
            
            assistant_response_for_storage = f"Sustainability Expert Run ended with status: {final_run_status}. Details: {error_message}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertError")
            response_payload = {"error": f"Sustainability Expert Run ended with status: {final_run_status}", "details": error_message, "thread_id": thread_id, "run_id": sustainability_run_id_for_storage, "run_status": final_run_status}
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
    except openai.APIStatusError as e: # More generic OpenAI API errors
        app.logger.error(f"{endpoint_name}: OpenAI APIStatusError: status={e.status_code}, response={e.response}, message={e.message}", exc_info=True)
        response_payload = {"error": f"OpenAI API error (status {e.status_code}).", "details": e.message}
        http_status_code = e.status_code if e.status_code else 500
    except Exception as e: # Captura otras excepciones como timeouts de create_and_poll
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        error_message_for_response = f"An internal server error occurred: {str(e)}"
        # Verificar si es un timeout de la librería de OpenAI
        if "timed out" in str(e).lower() and sustainability_run_id_for_storage: # Puede ser un timeout de la librería
            final_run_status = "timed_out_library" # Estado personalizado
            error_message_for_response = f"The request to the Sustainability Expert timed out. Run ID: {sustainability_run_id_for_storage}"
            http_status_code = 504 # Gateway Timeout
        else:
            http_status_code = 500
        response_payload = {"error": error_message_for_response}

    # Asegurar que thread_id se incluya en la respuesta de error si está disponible
    _thread_id_for_except_log = data_from_request.get('thread_id') if data_from_request else thread_id
    if 'thread_id' not in response_payload and _thread_id_for_except_log:
        response_payload['thread_id'] = _thread_id_for_except_log
    if 'run_id' not in response_payload and sustainability_run_id_for_storage:
        response_payload['run_id'] = sustainability_run_id_for_storage
    if 'run_status' not in response_payload and final_run_status: # Asegurar que run_status esté
        response_payload['run_status'] = final_run_status

    if user_message_content is not None:
        assistant_error_response = response_payload.get("error", "Unhandled API Exception")
        if response_payload.get("details"):
             assistant_error_response += f" Details: {response_payload.get('details')}"
        store_conversation_turn(_thread_id_for_except_log, user_message_content, assistant_error_response, endpoint_name, sustainability_run_id_for_storage, "SustainabilityExpertException", citations_for_storage)
    
    app.logger.info(f"{endpoint_name}: Responding with JSON error: {json.dumps(response_payload)}")
    return jsonify(response_payload), http_status_code


# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    app.logger.info("Health check endpoint was called.")
    response_payload = {}
    try:
        # Podrías añadir una prueba simple de conectividad con OpenAI aquí si es necesario
        # client.models.list(limit=1) 
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
    # No es recomendable usar app.run(debug=True) en producción.
    # Gunicorn u otro servidor WSGI es preferible.
    # El puerto se toma de la variable de entorno PORT, común en Cloud Run.
    port = int(os.environ.get("PORT", 8080)) # Default a 8080 para desarrollo local si PORT no está seteado
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.logger.info(f"Starting Flask server on port {port} with debug mode: {debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)