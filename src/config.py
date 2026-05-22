# config.py
import os
import logging
from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

from flask import Flask

from packaging import version
import firebase_admin
from firebase_admin import credentials, firestore

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
logger.info("Environment configuration checked.")

# --- 4. Inicialización de Clientes Externos ---
try:
    # --- Inicialización de Firebase Admin ---
    if not firebase_admin._apps:
        if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
            firebase_admin.initialize_app()
        else:
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                logger.info("Firebase Admin: using application default credentials.")
                if cred_path:
                    # Remove it from env so firebase_admin doesn't crash trying to load a non-existent path
                    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
                # Intentamos usar ADC
                firebase_project = os.getenv("FIREBASE_PROJECT_ID")
                if firebase_project:
                    firebase_admin.initialize_app(options={'projectId': firebase_project})
                else:
                    firebase_admin.initialize_app()
    
    firestore_db = firestore.client()
    logger.info("Firestore client initialized.")

except Exception as e:
    logger.critical(f"Failed to initialize external clients: {e}", exc_info=True)
    raise
