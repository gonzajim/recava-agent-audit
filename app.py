import os
import time
import json
from flask import Flask, request, jsonify
from openai import OpenAI
import logging
from google.cloud import firestore # <--- AÑADIDO: Importar Firestore

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

# Validaciones de variables de entorno (sin cambios)
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
    client = OpenAI(api_key=OPENAI_API_KEY)
    app.logger.info("OpenAI client initialized successfully.")
except Exception as e:
    app.logger.critical(f"Failed to initialize OpenAI client: {e}", exc_info=True)
    raise

# --- AÑADIDO: Inicializar Cliente de Firestore ---
try:
    db = firestore.Client()
    app.logger.info("Firestore client initialized successfully.")
except Exception as e:
    app.logger.critical(f"Failed to initialize Firestore client: {e}", exc_info=True)
    # Podrías decidir si la app debe fallar aquí o continuar sin Firestore
    # Por ahora, dejaremos que falle para asegurar que la configuración sea correcta.
    raise
# --- Fin Inicializar Cliente de Firestore ---


# --- AÑADIDO: Función para Guardar Conversación en Firestore ---
def store_conversation_turn(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str, run_id: str = None, assistant_name: str = None):
    """
    Almacena un turno de la conversación (pregunta y respuesta) en Firestore.
    """
    if not user_message and not assistant_response: # No guardar si falta información clave, permitir guardar aunque uno falte si el otro existe (ej. error antes de respuesta)
        app.logger.warning(f"Firestore: Skipping storage for thread {thread_id} from {endpoint_source} due to both user_message and assistant_response being empty.")
        return

    collection_name = "audit_trail" # Nombre de tu colección en Firestore
    try:
        doc_ref = db.collection(collection_name).document() # Firestore generará un ID único
        data_to_store = {
            'thread_id': thread_id,
            'user_message': user_message if user_message is not None else "", # Guardar cadena vacía si es None
            'assistant_response': assistant_response if assistant_response is not None else "", # Guardar cadena vacía si es None
            'endpoint_source': endpoint_source,
            'timestamp': firestore.SERVER_TIMESTAMP, # Usa el timestamp del servidor de Firestore
        }
        if run_id:
            data_to_store['run_id'] = run_id
        if assistant_name:
            data_to_store['assistant_name'] = assistant_name
        
        doc_ref.set(data_to_store)
        app.logger.info(f"Firestore: Stored conversation turn for thread {thread_id} from {endpoint_source} in document {doc_ref.id}.")
    except Exception as e:
        # Importante: Decide cómo manejar errores de Firestore.
        # Por ahora, solo logueamos el error para no interrumpir la respuesta al usuario.
        app.logger.error(f"Firestore: Failed to store conversation turn for thread {thread_id} from {endpoint_source}. Error: {e}", exc_info=True)
# --- Fin Función para Guardar Conversación ---


# --- Tool Implementation Functions (sin cambios significativos, solo logging) ---
def execute_sustainability_assistant_tool(query: str, thread_id: str) -> str:
    app.logger.info(f"Orchestrator's tool executing Sustainability Assistant for thread {thread_id} with query: \"{query}\"")
    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASISTENTE_ID,
            instructions=f"Address the following sustainability query based on your knowledge: \"{query}\". Provide a concise and focused answer."
        )
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                response_text = "".join([content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text'])
                app.logger.info(f"Sustainability Assistant (via tool) response for thread {thread_id}: \"{response_text[:100]}...\"")
                return response_text
            else:
                app.logger.warning(f"Sustainability Assistant (via tool) for thread {thread_id}: No message content found.")
                return "The Sustainability Assistant provided no textual response for this query."
        else:
            app.logger.error(f"Sustainability Assistant (via tool) for thread {thread_id}: Run failed status {run.status}. Details: {run.last_error or 'N/A'}")
            return f"Error interacting with Sustainability Assistant via tool: {run.status}"
    except Exception as e:
        app.logger.error(f"Exception in execute_sustainability_assistant_tool for thread {thread_id}: {e}", exc_info=True)
        return f"An error occurred while the Orchestrator's tool was calling the Sustainability Assistant: {str(e)}"


def execute_auditor_assistant_tool(task: str, thread_id: str) -> str:
    app.logger.info(f"Orchestrator's tool executing Auditor Assistant for thread {thread_id} with task: \"{task}\"")
    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=AUDITOR_ID,
            instructions=f"Perform the following audit task based on the conversation history: \"{task}\". Ensure your response is relevant to the audit process."
        )
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                response_text = "".join([content_block.text.value for content_block in messages.data[0].content if content_block.type == 'text'])
                app.logger.info(f"Auditor Assistant (via tool) response for thread {thread_id}: \"{response_text[:100]}...\"")
                return response_text
            else:
                app.logger.warning(f"Auditor Assistant (via tool) for thread {thread_id}: No message content found.")
                return "The Auditor Assistant provided no textual response for this task."
        else:
            app.logger.error(f"Auditor Assistant (via tool) for thread {thread_id}: Run failed status {run.status}. Details: {run.last_error or 'N/A'}")
            return f"Error interacting with Auditor Assistant via tool: {run.status}"
    except Exception as e:
        app.logger.error(f"Exception in execute_auditor_assistant_tool for thread {thread_id}: {e}", exc_info=True)
        return f"An error occurred while the Orchestrator's tool was calling the Auditor Assistant: {str(e)}"


# --- Orchestrator API Endpoint ---
@app.route('/chat_auditor', methods=['POST']) # <--- NOMBRE DE ENDPOINT CAMBIADO
def chat_with_orchestrator():
    endpoint_name = "/chat_auditor" # <--- NOMBRE DE ENDPOINT CAMBIADO para logging
    app.logger.info(f"Received request for {endpoint_name} (Orchestrator) endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    assistant_response_for_storage = "Error or no response generated by Orchestrator." 
    current_run_id = None

    try:
        data = request.json
        if not data:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            return jsonify({"error": "Invalid request: payload must be JSON."}), 400

        user_message_content = data.get('message')
        thread_id = data.get('thread_id') 

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")

        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            return jsonify({"error": "No message provided"}), 400
            
        app.logger.info(f"{endpoint_name}: Attempting to interact with OpenAI Orchestrator for thread: {thread_id or 'New Thread'}")
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Orchestrator: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Orchestrator: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Orchestrator thread: {thread_id}")
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
        current_run_id = current_run.id 
        app.logger.info(f"{endpoint_name}: Orchestrator Run {current_run.id} created for thread {thread_id}. Initial status: {current_run.status}")
        
        polling_attempts = 0
        max_polling_attempts_before_action = 60 
        
        while current_run.status in ['queued', 'in_progress']:
            polling_attempts += 1
            if polling_attempts > max_polling_attempts_before_action:
                app.logger.warning(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} timed out waiting for 'requires_action' or completion. Last status: {current_run.status}")
                assistant_response_for_storage = f"OpenAI run (Orchestrator) timed out before action or completion. Status: {current_run.status}"
                # Guardar intento fallido por timeout
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id, "OrchestratorTimeout")
                return jsonify({"error": "OpenAI run (Orchestrator) timed out before action or completion.", "thread_id": thread_id, "run_id": current_run.id, "status": current_run.status}), 504
            
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
                            output = execute_auditor_assistant_tool(task=arguments.get("task"), thread_id=thread_id)
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
                    store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id, "OrchestratorToolError")
                    return jsonify({"error": f"Error submitting tool outputs for Orchestrator: {str(e)}", "thread_id": thread_id, "run_id": current_run.id}), 500
            else: 
                app.logger.warning(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} was 'requires_action' but no tool_outputs were generated/processed.")
                assistant_response_for_storage = "Orchestrator required action but no tool outputs were processed."
                store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id, "OrchestratorToolError")
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
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id, "Orchestrator")
            return jsonify({"response": assistant_response, "thread_id": thread_id, "run_id": current_run.id, "run_status": current_run.status})
        
        else: 
            app.logger.error(f"{endpoint_name}: Orchestrator Run {current_run.id} on thread {thread_id} ended with unhandled status: {current_run.status}. Last error: {current_run.last_error}")
            error_details = str(current_run.last_error.message) if current_run.last_error else "No specific error details provided by API for Orchestrator run."
            assistant_response_for_storage = f"Orchestrator Run ended with status: {current_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, current_run_id, "OrchestratorError")
            return jsonify({"error": f"Orchestrator Run ended with status: {current_run.status}", "details": error_details, "thread_id": thread_id, "run_id": current_run.id}), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred in Orchestrator endpoint: {e}", exc_info=True)
        if user_message_content is not None and thread_id is not None: # Solo guardar si tenemos la info básica
             store_conversation_turn(thread_id, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, current_run_id, "OrchestratorException")
        elif user_message_content is not None: # Si solo tenemos el mensaje del usuario
             store_conversation_turn(None, user_message_content, f"Unhandled API Exception (no thread_id): {str(e)}", endpoint_name, None, "OrchestratorException")
        return jsonify({"error": f"An internal server error occurred in Orchestrator endpoint: {str(e)}", "thread_id": thread_id if thread_id else (data.get('thread_id') if 'data' in locals() and data else None)}), 500


# --- NUEVO ENDPOINT para el Asistente de Sostenibilidad ---
@app.route('/chat_assistant', methods=['POST']) # <--- NOMBRE DE ENDPOINT CAMBIADO
def preguntar_asistente_sostenibilidad():
    endpoint_name = "/chat_assistant" # <--- NOMBRE DE ENDPOINT CAMBIADO para logging
    app.logger.info(f"Received request for {endpoint_name} endpoint from {request.remote_addr}")
    user_message_content = None 
    thread_id = None
    assistant_response_for_storage = "Error or no response generated by Sustainability Assistant."
    sustainability_run_id = None

    try:
        data = request.json
        if not data:
            app.logger.warning(f"{endpoint_name}: Request is not JSON or empty.")
            return jsonify({"error": "Invalid request: payload must be JSON."}), 400

        user_message_content = data.get('message')
        thread_id = data.get('thread_id')

        app.logger.info(f"{endpoint_name}: Request data: message='{user_message_content}', thread_id='{thread_id}'")
        if not user_message_content:
            app.logger.warning(f"{endpoint_name}: No message provided in the request.")
            return jsonify({"error": "No message provided"}), 400

        app.logger.info(f"{endpoint_name}: Attempting to interact with Sustainability Assistant ({ASISTENTE_ID}) for thread: {thread_id or 'New Thread'}")
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            app.logger.info(f"{endpoint_name}: Created new thread for Sustainability Assistant: {thread_id}")
        else:
            app.logger.info(f"{endpoint_name}: Using existing thread for Sustainability Assistant: {thread_id}")
            try:
                client.beta.threads.retrieve(thread_id=thread_id)
                app.logger.info(f"{endpoint_name}: Successfully retrieved existing Sustainability Assistant thread: {thread_id}")
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
        sustainability_run_id = sustainability_run.id
        app.logger.info(f"{endpoint_name}: Sustainability Assistant Run {sustainability_run_id} on thread {thread_id} completed with status: {sustainability_run.status}")


        if sustainability_run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            assistant_response = "No new response from Sustainability Assistant for this run."
            for msg in messages.data:
                if msg.run_id == sustainability_run_id and msg.role == "assistant": 
                    if msg.content:
                        assistant_response_parts = []
                        for content_block in msg.content:
                            if content_block.type == 'text':
                                assistant_response_parts.append(content_block.text.value)
                        assistant_response = "\n".join(assistant_response_parts).strip()
                        break
            
            app.logger.info(f"{endpoint_name}: Sustainability Assistant final response for run {sustainability_run_id} on thread {thread_id}: \"{assistant_response[:200]}...\"")
            assistant_response_for_storage = assistant_response 
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id, "SustainabilityAssistant")
            return jsonify({"response": assistant_response, "thread_id": thread_id, "run_id": sustainability_run_id, "run_status": sustainability_run.status})
        else:
            app.logger.error(f"{endpoint_name}: Sustainability Assistant Run {sustainability_run_id} on thread {thread_id} ended with status: {sustainability_run.status}. Last error: {sustainability_run.last_error}")
            error_details = str(sustainability_run.last_error.message) if sustainability_run.last_error else "No specific error details."
            assistant_response_for_storage = f"Sustainability Assistant Run ended with status: {sustainability_run.status}. Details: {error_details}"
            store_conversation_turn(thread_id, user_message_content, assistant_response_for_storage, endpoint_name, sustainability_run_id, "SustainabilityAssistantError")
            return jsonify({"error": f"Sustainability Assistant Run ended with status: {sustainability_run.status}", "details": error_details, "thread_id": thread_id, "run_id": sustainability_run_id}), 500

    except Exception as e:
        app.logger.error(f"{endpoint_name}: An unexpected error occurred: {e}", exc_info=True)
        if user_message_content is not None and thread_id is not None:
            store_conversation_turn(thread_id, user_message_content, f"Unhandled API Exception: {str(e)}", endpoint_name, sustainability_run_id, "SustainabilityAssistantException")
        elif user_message_content is not None:
            store_conversation_turn(None, user_message_content, f"Unhandled API Exception (no thread_id): {str(e)}", endpoint_name, None, "SustainabilityAssistantException")
        return jsonify({"error": f"An internal server error occurred in {endpoint_name}: {str(e)}", "thread_id": thread_id if thread_id else (data.get('thread_id') if 'data' in locals() and data else None)}), 500


# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    app.logger.info("Health check endpoint was called.")
    try:
        pass 
    except Exception as e:
        app.logger.error(f"Health check: Firestore connectivity test failed. Error: {e}", exc_info=True)
        return jsonify({"status": "unhealthy", "reason": "Firestore connectivity issue"}), 503
    
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    app.logger.info("Starting Flask development server with debug mode.")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
