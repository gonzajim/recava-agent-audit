# src/config.py
import os
import logging
from flask import Flask
from google.cloud import bigquery
from google import genai
from pinecone import Pinecone as PineconeClient
from sentence_transformers import SentenceTransformer

# --- 1. Flask ---
app = Flask(__name__)
# CORS is configured in app.py with specific allowed origins (supports_credentials=True
# is incompatible with wildcard origin, so it must use an explicit list)

# --- 2. Logging ---
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

# --- 3. Variables de entorno ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
BIGQUERY_DATASET_ID = os.getenv("BIGQUERY_DATASET_ID")
BIGQUERY_TABLE_ID = os.getenv("BIGQUERY_TABLE_ID")

if not GEMINI_API_KEY:
    logger.critical("Missing GEMINI_API_KEY environment variable.")
    raise ValueError("Missing GEMINI_API_KEY environment variable.")
if not all([BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID]):
    logger.critical("Missing BigQuery environment variables (BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID).")
    raise ValueError("Missing BigQuery environment variables.")

logger.info("Environment variables loaded.")

# --- 4. Clientes externos ---
try:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("Gemini client initialized.")

    bq_client = bigquery.Client()
    logger.info("BigQuery client initialized.")

    if PINECONE_API_KEY and PINECONE_INDEX_NAME:
        _pc = PineconeClient(api_key=PINECONE_API_KEY)
        # PINECONE_INDEX_NAME may be a host URL (https://...) or a plain index name.
        if PINECONE_INDEX_NAME.startswith("http"):
            pinecone_index = _pc.Index(host=PINECONE_INDEX_NAME)
        else:
            pinecone_index = _pc.Index(PINECONE_INDEX_NAME)
        logger.info("Pinecone index connected via '%s'.", PINECONE_INDEX_NAME)
    else:
        pinecone_index = None
        logger.warning("Pinecone not configured (PINECONE_API_KEY or PINECONE_INDEX_NAME missing). RAG disabled.")

    # Embedding model — must match the model used to build the Pinecone corpus.
    # Current corpus: sentence-transformers/all-MiniLM-L6-v2 (384 dims, English).
    # To improve Spanish quality without re-indexing: keep this model.
    # Future: migrate to paraphrase-multilingual-MiniLM-L12-v2 + re-index corpus.
    _EMBEDDING_MODEL_NAME = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    embed_model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
    logger.info("SentenceTransformer '%s' loaded.", _EMBEDDING_MODEL_NAME)

except Exception as e:
    logger.critical("Failed to initialize external clients: %s", e, exc_info=True)
    raise
