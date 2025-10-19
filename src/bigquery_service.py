# src/bigquery_service.py
import datetime
import os
from typing import Optional

from src.config import bq_client, logger, BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID

# Permite desactivar las escrituras en BigQuery cuando se trabaja en local.
DISABLE_BIGQUERY = os.getenv("DISABLE_BIGQUERY", "0") == "1"


def insert_chat_turn_to_bigquery(
    thread_id: str,
    user_message: str,
    assistant_response: str,
    endpoint_source: str,
    run_id: Optional[str] = None,
    assistant_name: Optional[str] = None,
    user_id: Optional[str] = None,
    uid: Optional[str] = None,
    email: Optional[str] = None,
    email_verified: Optional[bool] = None,
):
    """Inserta una fila en la tabla de historial de chat de BigQuery."""

    row = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "thread_id": thread_id,
        "user_message": user_message,
        "assistant_response": assistant_response,
        "endpoint_source": endpoint_source,
    }

    if run_id is not None:
        row["run_id"] = run_id
    if assistant_name is not None:
        row["assistant_name"] = assistant_name
    if user_id is not None:
        row["user_id"] = user_id
    if uid is not None:
        row["uid"] = uid
    if email is not None:
        row["email"] = email
    if email_verified is not None:
        row["email_verified"] = bool(email_verified)

    if DISABLE_BIGQUERY:
        logger.info("BigQuery disabled via DISABLE_BIGQUERY=1. Skipping insert: %s", row)
        return

    table_ref = bq_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID)

    try:
        errors = bq_client.insert_rows_json(table_ref, [row])
        if not errors:
            logger.info("BigQuery: Successfully stored turn for thread %s.", thread_id)
        else:
            logger.error("BigQuery: Encountered errors while inserting rows: %s", errors)
    except Exception:
        logger.error("BigQuery: Failed to stream data for thread %s.", thread_id, exc_info=True)
