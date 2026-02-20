# config.py
import os
import logging
import openai
from flask import Flask

from google.cloud import bigquery
from packaging import version
from httpx import Timeout

# --- 1. Inicialización de Flask ---
# Nota: CORS se configura en app.py con orígenes restringidos; NO inicializar aquí.
app = Flask(__name__)


# --- 2. Configuración Centralizada de Logging ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(filename)s:%(lineno)d - %(message)s'
    )
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

logger.info("Application configuration starting...")

# --- 3. Carga y Validación de Variables de Entorno ---
# Variables de OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ORCHESTRATOR_ASSISTANT_ID = os.getenv("ORCHESTRATOR_ASSISTANT_ID")
ASISTENTE_ID = os.getenv("ASISTENTE_ID")

if not OPENAI_API_KEY:
    logger.critical("Missing OPENAI_API_KEY environment variable.")
    raise ValueError("Missing OPENAI_API_KEY environment variable.")
if not ORCHESTRATOR_ASSISTANT_ID:
    logger.critical("Missing ORCHESTRATOR_ASSISTANT_ID environment variable.")
    raise ValueError("Missing ORCHESTRATOR_ASSISTANT_ID environment variable.")
if not ASISTENTE_ID:
    logger.critical("Missing ASISTENTE_ID environment variable.")
    raise ValueError("Missing ASISTENTE_ID environment variable.")

# <-- NUEVO: Variables de Entorno para BigQuery ---
BIGQUERY_DATASET_ID = os.getenv("BIGQUERY_DATASET_ID")
BIGQUERY_TABLE_ID = os.getenv("BIGQUERY_TABLE_ID")

if not all([BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID]):
    logger.critical("Missing BigQuery environment variables (BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID).")
    raise ValueError("Missing BigQuery environment variables.")

logger.info("All environment variables loaded successfully.")

# --- 4. Inicialización de Clientes Externos ---
try:
    # Cliente de OpenAI
    client = openai.OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=Timeout(60.0, read=60.0, write=60.0, connect=10.0),
        max_retries=3,
    )
    logger.info("OpenAI client initialized.")

    # Cliente de BigQuery
    bq_client = bigquery.Client()
    logger.info("BigQuery client initialized.")

except Exception as e:
    logger.critical(f"Failed to initialize external clients: {e}", exc_info=True)
    raise
