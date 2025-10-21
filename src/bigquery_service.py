# src/bigquery_service.py
import datetime
import os
from typing import Optional, List, Dict, Any

from google.cloud import bigquery

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


def _build_table_fqn() -> str:
    """Devuelve el identificador completamente calificado de la tabla de historial."""
    project_id = bq_client.project
    return f"`{project_id}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}`"


def _normalize_timestamp(value: Any) -> Optional[str]:
    """Convierte valores de marca de tiempo de BigQuery a ISO 8601 (UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc).isoformat()
        return value.astimezone(datetime.timezone.utc).isoformat()
    return str(value)


def fetch_recent_conversations_for_user(uid: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Obtiene las `limit` conversaciones m��s recientes para un usuario."""
    if not uid:
        raise ValueError("uid is required to fetch recent conversations")

    limit = max(1, min(limit, 20))  # acota a un rango razonable

    if DISABLE_BIGQUERY:
        logger.info("BigQuery disabled. Returning empty recent conversation list for uid=%s.", uid)
        return []

    table_fqn = _build_table_fqn()
    query = f"""
        WITH user_turns AS (
            SELECT
                thread_id,
                timestamp,
                user_message,
                assistant_response,
                endpoint_source
            FROM {table_fqn}
            WHERE uid = @uid
        ),
        thread_stats AS (
            SELECT
                thread_id,
                ANY_VALUE(endpoint_source) AS endpoint_source,
                MAX(timestamp) AS last_timestamp,
                COALESCE(
                    ARRAY_AGG(user_message IGNORE NULLS ORDER BY timestamp ASC)[SAFE_OFFSET(0)],
                    ARRAY_AGG(assistant_response IGNORE NULLS ORDER BY timestamp ASC)[SAFE_OFFSET(0)],
                    'Conversacion sin mensajes'
                ) AS summary_text
            FROM user_turns
            GROUP BY thread_id
        )
        SELECT thread_id, endpoint_source, last_timestamp, summary_text
        FROM thread_stats
        ORDER BY last_timestamp DESC
        LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", uid),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )

    try:
        rows = bq_client.query(query, job_config=job_config).result()
    except Exception:
        logger.error("BigQuery: Failed to fetch recent conversations for uid=%s.", uid, exc_info=True)
        raise

    conversations: List[Dict[str, Any]] = []
    for row in rows:
        summary_raw = (row.get("summary_text") or "").strip()
        summary = " ".join(summary_raw.split())[:160] or "Conversacion previa"
        conversations.append({
            "thread_id": row.get("thread_id"),
            "endpoint_source": row.get("endpoint_source"),
            "last_timestamp": _normalize_timestamp(row.get("last_timestamp")),
            "summary": summary,
        })
    return conversations


def fetch_conversation_thread(uid: str, thread_id: str) -> Dict[str, Any]:
    """Recupera el detalle completo de una conversaci��n perteneciente al usuario."""
    if not uid:
        raise ValueError("uid is required to fetch a conversation thread")
    if not thread_id:
        raise ValueError("thread_id is required to fetch a conversation thread")

    if DISABLE_BIGQUERY:
        logger.info("BigQuery disabled. Returning empty conversation for uid=%s thread_id=%s.", uid, thread_id)
        return {"thread_id": thread_id, "endpoint_source": None, "messages": []}

    table_fqn = _build_table_fqn()
    query = f"""
        SELECT timestamp, user_message, assistant_response, endpoint_source
        FROM {table_fqn}
        WHERE uid = @uid AND thread_id = @thread_id
        ORDER BY timestamp ASC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", uid),
            bigquery.ScalarQueryParameter("thread_id", "STRING", thread_id),
        ]
    )

    try:
        rows = bq_client.query(query, job_config=job_config).result()
    except Exception:
        logger.error("BigQuery: Failed to fetch conversation thread %s for uid=%s.", thread_id, uid, exc_info=True)
        raise

    messages: List[Dict[str, Any]] = []
    endpoint_source = None
    for row in rows:
        endpoint_source = endpoint_source or row.get("endpoint_source")
        timestamp_iso = _normalize_timestamp(row.get("timestamp"))

        user_msg = row.get("user_message")
        if user_msg:
            messages.append({
                "role": "user",
                "text": user_msg,
                "timestamp": timestamp_iso,
            })

        assistant_msg = row.get("assistant_response")
        if assistant_msg:
            messages.append({
                "role": "assistant",
                "text": assistant_msg,
                "timestamp": timestamp_iso,
            })

    return {
        "thread_id": thread_id,
        "endpoint_source": endpoint_source,
        "messages": messages,
        "total_messages": len(messages),
    }
