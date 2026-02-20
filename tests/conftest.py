# tests/conftest.py
"""
Configuración compartida de pytest para el proyecto recava-agent-audit.
Parchea variables de entorno antes de importar cualquier módulo de la app.
"""
import os
import pytest


def pytest_configure(config):
    """Configura variables de entorno mínimas para que config.py no falle al importar."""
    env_defaults = {
        "OPENAI_API_KEY": "test-openai-key",
        "ORCHESTRATOR_ASSISTANT_ID": "asst_test_orchestrator",
        "ASISTENTE_ID": "asst_test_assistant",
        "BIGQUERY_DATASET_ID": "test_dataset",
        "BIGQUERY_TABLE_ID": "test_table",
        "DISABLE_BIGQUERY": "1",  # Deshabilita escrituras reales a BigQuery
    }
    for key, value in env_defaults.items():
        os.environ.setdefault(key, value)
