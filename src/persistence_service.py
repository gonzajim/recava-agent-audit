# src/persistence_service.py
from google.cloud import firestore
from config import db, logger
# <-- CAMBIO: Importamos el nuevo servicio de BigQuery
from src.bigquery_service import insert_chat_turn_to_bigquery

# <-- CAMBIO: Nombre de la función más genérico para reflejar su doble propósito
def persist_conversation_turn(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str, **kwargs):
    """
    Función orquestadora que persiste un turno de conversación en múltiples sistemas.
    Actualmente: Firestore y BigQuery.
    """
    logger.info(f"Persisting turn for thread {thread_id} from {endpoint_source}...")

    # --- 1. Persistir en Firestore (lógica original) ---
    try:
        # Un modo más conciso de construir el diccionario, manejando kwargs
        data_to_store = {k: v for k, v in {
            'thread_id': thread_id or "unknown_thread",
            'user_message': user_message or "",
            'assistant_response': assistant_response or "",
            'endpoint_source': endpoint_source,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'run_id': kwargs.get('run_id'),
            'assistant_name': kwargs.get('assistant_name')
        }.items() if v is not None} # Limpia claves con valor None

        db.collection("audit_trail").document().set(data_to_store)
        logger.info(f"Firestore: Successfully stored turn.")
    except Exception as e:
        logger.error(f"Firestore: Failed to store turn for thread {thread_id}.", exc_info=True)
        # Nota: Decidimos continuar incluso si falla la escritura en Firestore.

    # --- 2. Persistir en BigQuery (lógica nueva) ---
    try:
        # Llamamos a la función de nuestro servicio de BigQuery
        insert_chat_turn_to_bigquery(
            thread_id=thread_id,
            user_message=user_message,
            assistant_response=assistant_response,
            endpoint_source=endpoint_source
        )
    except Exception as e:
        # La función interna ya loguea el detalle, aquí solo confirmamos que falló en este nivel.
        logger.error(f"Persistence service failed to write to BigQuery for thread {thread_id}.")