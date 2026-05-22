# tests/test_empirical_audit_mock.py
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock dependencies before importing the service
sys.modules['src.config'] = MagicMock()
sys.modules['app'] = MagicMock()
mock_genai = MagicMock()
sys.modules['google.generativeai'] = mock_genai

from src.empirical_audit_service import _evaluate_indicator, INDICATORS

class TestEmpiricalAudit(unittest.TestCase):

    @patch('src.empirical_audit_service.retrieve_context')
    def test_evaluate_indicator_success(self, mock_retrieve):
        # Configurar mock de Vector DB
        mock_retrieve.return_value = "Texto de prueba con Página: 12"
        
        # Configurar mock de Gemini
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        mock_response = MagicMock()
        mock_response.text = '{"cumple": "SÍ", "evidencia_literal": "Prueba", "pagina_real": "12", "razonamiento": "Ok"}'
        mock_model.generate_content.return_value = mock_response
        
        # Ejecutar evaluación del primer indicador
        indicator = INDICATORS[0]
        result = _evaluate_indicator(indicator, "doc_123")
        
        # Verificaciones
        self.assertEqual(result["indicator_id"], "1")
        self.assertEqual(result["cumple"], "SÍ")
        self.assertEqual(result["pagina_real"], "12")
        mock_retrieve.assert_called_once()

    @patch('src.empirical_audit_service.retrieve_context')
    def test_evaluate_indicator_no_context(self, mock_retrieve):
        # Simular que no se encuentra nada en el Vector DB
        mock_retrieve.return_value = ""
        
        # Configurar mock de Gemini
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        mock_response = MagicMock()
        mock_response.text = '{"cumple": "NA", "evidencia_literal": "", "pagina_real": "N/A", "razonamiento": "No se encontró contexto en el Vector DB"}'
        mock_model.generate_content.return_value = mock_response
        
        indicator = INDICATORS[0]
        result = _evaluate_indicator(indicator, "doc_123")
        
        self.assertEqual(result["cumple"], "NA")
        self.assertIn("No se encontró", result["razonamiento"])

if __name__ == '__main__':
    unittest.main()
