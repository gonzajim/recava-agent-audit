"""BigQuery persistence utilities for advisor interactions."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi.concurrency import run_in_threadpool
from google.cloud import bigquery

logger = logging.getLogger(__name__)

DISABLE_BIGQUERY = os.getenv("DISABLE_BIGQUERY", "0") == "1"
_DATASET = os.getenv("BIGQUERY_DATASET_ID")
_TABLE = os.getenv("BIGQUERY_TABLE_ID")
_bq_client: Optional[bigquery.Client] = None


def _get_bigquery_client() -> bigquery.Client:
    global _bq_client  # pylint: disable=global-statement
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


async def insert_chat_turn_to_bigquery(
    *,
    session_id: str,
    user_id: Optional[str],
    user_email: Optional[str],
    user_verified: Optional[bool],
    query: str,
    response_text: str,
    citations: Optional[List[Dict[str, Any]]],
    mode: str,
    endpoint_source: str = "advisor",
) -> None:
    """Persist advisor interaction in BigQuery."""
    if DISABLE_BIGQUERY:
        logger.info("BigQuery disabled; skipping insert for session %s", session_id)
        return

    if not _DATASET or not _TABLE:
        logger.warning("BIGQUERY_DATASET_ID or BIGQUERY_TABLE_ID not configured; skipping insert.")
        return

    row: Dict[str, Any] = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "thread_id": session_id,
        "user_message": query,
        "assistant_response": response_text,
        "endpoint_source": endpoint_source,
        "mode": mode,
        "uid": user_id,
        "email": user_email,
        "email_verified": user_verified,
        "citations": citations or [],
    }

    row = {key: value for key, value in row.items() if value is not None}

    client = _get_bigquery_client()
    table_ref = client.dataset(_DATASET).table(_TABLE)

    def _insert() -> List[Any]:
        return client.insert_rows_json(
            table_ref,
            [row],
            ignore_unknown_values=True,
        )

    errors = await run_in_threadpool(_insert)
    if errors:
        logger.error("BigQuery insertion errors for session %s: %s", session_id, errors)
