# src/openai_service.py
import json
from config import client, logger, ASISTENTE_ID

def execute_invoke_sustainability_expert(query: str, original_thread_id: str) -> str:
    """Ejecuta una consulta al Asistente de Sostenibilidad como una herramienta."""
    tool_name = "invoke_sustainability_expert"
    logger.info(f"Tool ({tool_name}): Executing for query on thread {original_thread_id}")
    temp_thread = None
    error_message = "ERROR_EXPERT: No se pudo obtener respuesta del experto en sostenibilidad."

    try:
        temp_thread = client.beta.threads.create()
        client.beta.threads.messages.create(thread_id=temp_thread.id, role="user", content=query)
        run = client.beta.threads.runs.create_and_poll(
            thread_id=temp_thread.id,
            assistant_id=ASISTENTE_ID,
            instructions="Please address the user's query based on your knowledge. Provide a concise, focused answer."
        )
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(thread_id=temp_thread.id, run_id=run.id, order='desc', limit=1)
            if messages.data and messages.data[0].content:
                return "\n".join([block.text.value for block in messages.data[0].content if block.type == 'text']).strip()
        
        logger.error(f"Tool ({tool_name}): Run failed with status {run.status}. Details: {run.last_error or 'N/A'}")
        return error_message
    except Exception as e:
        logger.error(f"Tool ({tool_name}): Exception: {e}", exc_info=True)
        return error_message
    finally:
        if temp_thread:
            try:
                client.beta.threads.delete(temp_thread.id)
            except Exception as delete_err:
                logger.error(f"Tool ({tool_name}): Failed to delete temp thread {temp_thread.id}. Error: {delete_err}")

def process_assistant_message_without_citations(messages_data, final_run_id, endpoint_name):
    """Extrae el último mensaje de texto del asistente de una lista de mensajes."""
    for msg in messages_data:
        if msg.run_id == final_run_id and msg.role == "assistant" and msg.content:
            return "\n".join([block.text.value for block in msg.content if block.type == 'text']).strip()
    logger.warning(f"{endpoint_name}: No new response from assistant found for run {final_run_id}.")
    return "No se pudo obtener una nueva respuesta del asistente."