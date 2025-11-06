# src/persistence_service.py
from src.config import logger
from src.bigquery_service import insert_chat_turn_to_bigquery

def persist_conversation_turn(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str, **kwargs):
    """Persiste un turno de conversación en BigQuery, consolidando todo el historial."""
    logger.info(f"Persisting turn for thread {thread_id} from {endpoint_source} via BigQuery...")

    try:
        insert_chat_turn_to_bigquery(
            thread_id=thread_id,
            user_message=user_message,
            assistant_response=assistant_response,
            endpoint_source=endpoint_source,
            run_id=kwargs.get('run_id'),
            assistant_name=kwargs.get('assistant_name'),
            user_id=kwargs.get('user_id'),
            uid=kwargs.get('uid'),
            email=kwargs.get('email'),
            email_verified=kwargs.get('email_verified'),
        )
        logger.info("BigQuery: Successfully stored turn.")
    except Exception:
        logger.error(f"BigQuery: Failed to store turn for thread {thread_id}.", exc_info=True)
