# src/bigquery_service.py
import datetime
from config import bq_client, logger, BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID

def insert_chat_turn_to_bigquery(thread_id: str, user_message: str, assistant_response: str, endpoint_source: str):
    """Inserta una fila en la tabla de historial de chat de BigQuery."""

    table_ref = bq_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID)

    rows_to_insert = [
        {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "thread_id": thread_id,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "endpoint_source": endpoint_source,
        }
    ]

    try:
        errors = bq_client.insert_rows_json(table_ref, rows_to_insert)
        if not errors:
            logger.info(f"BigQuery: Successfully streamed 1 row for thread {thread_id}.")
        else:
            logger.error(f"BigQuery: Encountered errors while inserting rows: {errors}")
    except Exception as e:
        logger.error(f"BigQuery: Failed to stream data for thread {thread_id}.", exc_info=True)