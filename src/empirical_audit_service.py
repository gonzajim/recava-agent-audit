import json
import time
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from src.config import logger, firestore_db
from src.vector_service import retrieve_context
import google.generativeai as genai

# Lista de indicadores extraída del SDD
INDICATORS = [
    {"id": "1", "ref": "S1-9 66. a)", "question": "¿Divulga la distribución por género (en número y porcentaje) en la alta dirección?"},
    {"id": "2", "ref": "S1-9 66. b)", "question": "¿Divulga la distribución de los asalariados por grupos de edad?"},
    {"id": "3", "ref": "S1-10 69.", "question": "¿Divulga si todos sus asalariados perciben un salario adecuado de conformidad con lo índices de referencia aplicables?"},
    {"id": "4", "ref": "S1-10 70.", "question": "Si no todos lo perciben, ¿divulga los países en que los asalariados ganan menos del índice de referencia de salario adecuado aplicable y el porcentaje de asalariados en esta situación en cada uno de los países?"},
    {"id": "5", "ref": "S1-10 70.", "question": "Si no todos lo perciben, ¿divulga el porcentaje de asalariados en esta situación en cada uno de los países?"},
    {"id": "6", "ref": "S1-10 71.", "question": "¿Divulga la información especificada en este requisito con respecto a los trabajadores no asalariados de su personal propio?"},
    {"id": "7", "ref": "S1-11 74. a)", "question": "¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a enfermedad?"},
    {"id": "8", "ref": "S1-11 74. b)", "question": "¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a desempleo a partir del momento en que el trabajador propio trabaja para la empresa?"},
    {"id": "9", "ref": "S1-11 74. c)", "question": "¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a accidentes de trabajo y discapacidad adquirida?"},
    {"id": "10", "ref": "S1-11 74. d)", "question": "¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a permiso parental?"},
    {"id": "11", "ref": "S1-11 74. e)", "question": "¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a jubilación?"},
    {"id": "12", "ref": "S1-11 75. [1]", "question": "Si no todos los asalariados están cubiertos por la protección social, ¿divulga los países en que los asalariados no dispongan de protección social?"},
    {"id": "13", "ref": "S1-11 75. [2]", "question": "Si no todos los asalariados están cubiertos por la protección social, ¿divulga por países los tipos de asalariados que no dispongan de protección social con respecto a cada acontecimiento vital importante?"},
    {"id": "14", "ref": "S1-11 76.", "question": "¿Divulga la información especificada en este requisito de divulgación con respecto a los trabajadores no asalariados de su personal propio?"},
    {"id": "15", "ref": "S1-12 79.", "question": "¿Divulga el porcentaje de personas con discapacidad entre sus asalariados?"},
    {"id": "16", "ref": "S1-12 80.", "question": "¿Divulga el porcentaje de asalariados con discapacidad con desglose por género?"},
    {"id": "17", "ref": "S1-14 88. a) [1]", "question": "Sobre el personal propio asalariado: ¿divulga el porcentaje de miembros de su personal propio cubiertos por el sistema de gestión de la salud y la seguridad de la empresa, sobre la base de requisitos legales o normas o directrices reconocidas?"},
    {"id": "18", "ref": "S1-14 88. a) [2]", "question": "Sobre los trabajadores no asalariados: ¿divulga el porcentaje de miembros de su personal propio cubiertos por el sistema de gestión de la salud y la seguridad de la empresa, sobre la base de requisitos legales o normas o directrices reconocidas?"},
    {"id": "19", "ref": "S1-14 88. b) [1]", "question": "Sobre el personal propio asalariado: ¿divulga el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo?"},
    {"id": "20", "ref": "S1-14 88. b) [2]", "question": "Sobre los trabajadores no asalariados: ¿divulga el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo?"},
    {"id": "21", "ref": "S1-14 88. b) [3]", "question": "Sobre otros trabajadores de la cadena de valor: ¿divulga el el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo?"},
    {"id": "22", "ref": "S1-14 88. b) [4] {AR 82}", "question": "¿Divulga separadamente las muertes causadas por lesiones y las causadas por problemas de salud?"},
    {"id": "23", "ref": "S1-14 88. c) [1]", "question": "Sobre el personal propio asalariado: ¿divulga el número y la tasa de accidentes de trabajo registrables?"},
    {"id": "24", "ref": "S1-14 88. c) [2]", "question": "Sobre los trabajadores no asalariados: ¿divulga el número y la tasa de accidentes de trabajo registrables?"},
    {"id": "25", "ref": "S1-14 88. d)", "question": "Sobre el personal propio asalariado: ¿divulga el número de casos de problemas de salud relacionados con el trabajo?"},
    {"id": "26", "ref": "S1-14 88. d) [2] {89}", "question": "Sobre los trabajadores no asalariados: ¿divulga el número de casos de problemas de salud relacionados con el trabajo?"},
    {"id": "27", "ref": "S1-14 88.e)", "question": "Sobre el personal propio asalariado: ¿divulga el número de días perdidos por lesiones y muertes relacionadas con el trabajo como consecuencia de accidentes laborales, problemas de salud relacionados con el trabajo y muertes por enfermedad?"},
    {"id": "28", "ref": "S1-14 88. e) [2] {89}", "question": "Sobre los trabajadores no asalariados: ¿divulga el número de días perdidos por lesiones y muertes relacionadas con el trabajo como consecuencia de accidentes laborales, problemas de salud relacionados con el trabajo y muertes por enfermedad?"},
    {"id": "29", "ref": "S1-14 90.", "question": "¿Divulga el porcentaje de trabajadores propios cubiertos por un sistema de gestión de la salud y la seguridad basado en requisitos legales o en normas o directrices reconocidas y que ha sido auditado internamente o auditado o certificado por un tercero?"},
    {"id": "30", "ref": "S1-14 90. {AR 81}", "question": "¿Divulga la existencia o ausencia de esta auditoría, y en su caso las normas subyacentes en su realización?"},
    {"id": "31", "ref": "S1-15 93. a)", "question": "¿Divulga el porcentaje de asalariados que tienen derecho a acogerse a permisos por motivos familiares?"},
    {"id": "32", "ref": "S1-15 93. b)", "question": "¿Divulga el porcentaje de asalariados que gozan de este derecho y que se acogieron a permisos por motivos familiares, y su desglose por género?"},
    {"id": "33", "ref": "S1-16 97. a) [1]", "question": "¿Divulga la brecha salarial de género [del período de referencia actual {AR100}] expresada como porcentaje del nivel retributivo medio de los asalariados de género masculino?"},
    {"id": "34", "ref": "S1-16 97. a) [2] {98}", "question": "¿Divulga la brecha salarial de género por categoría de asalariado?"},
    {"id": "35", "ref": "S1-16 97. a) [3] {98}", "question": "¿Divulga la brecha salarial de género por país o segmento?"},
    {"id": "36", "ref": "S1-16 97. b) [1]", "question": "¿Divulga la relación entre la remuneración anual total de la persona con el mayor salario y la remuneración anual total media del conjunto de [todos: {AR 101.a)} asalariados (excluida la persona mejor pagada)?"},
    {"id": "37", "ref": "S1-16 97. b). [2] {99}", "question": "¿Divulga la relación entre la remuneración anual total de la persona con el mayor salario y la remuneración anual total media del conjunto de asalariados, ajustada para tener en cuenta las diferencias de poder adquisitivo entre países?"}
]

def _evaluate_indicator(indicator: dict, gemini_file) -> dict:
    """Evalúa un indicador específico usando el PDF completo y el corpus legal de Pinecone."""
    try:
        # 1. Recuperar contexto del corpus legal (Pinecone)
        query = f"{indicator['ref']} {indicator['question']}"
        legal_context = retrieve_context(query=query, top_k=3)

        system_prompt = f"""
        Eres un auditor experto en sostenibilidad (CSRD / ESRS).
        Debes evaluar si el documento PDF proporcionado cumple con el siguiente indicador:
        {indicator['ref']} - {indicator['question']}
        
        BASE LEGAL / CRITERIOS DE AUDITORÍA (Corpus Experto):
        Utiliza el siguiente contexto experto extraído de la base de datos legal para entender cómo se debe interpretar y evaluar este indicador de forma rigurosa:
        {legal_context if legal_context else "No hay contexto adicional específico para este indicador."}
        
        INSTRUCCIONES:
        1. Analiza el documento PDF buscando información relevante teniendo en cuenta los criterios de la base legal.
        2. Debes devolver un objeto JSON estricto con las siguientes claves:
        - "cumple": Valores permitidos: "SÍ", "NO", "NA" (No Aplica/No aparece), "FE" (Fuente Externa referenciada).
        - "evidencia_literal": Extrae literalmente el texto del PDF que justifica tu respuesta. Si es NO o NA, déjalo vacío.
        - "pagina_real": Indica el número de página donde se encontró la evidencia. Si no aplica o no se encuentra, pon "N/A".
        - "razonamiento": Explica brevemente por qué consideras que cumple o no cumple, apoyándote en la base legal proporcionada.
        """

        model = genai.GenerativeModel(
            model_name="gemini-2.5-pro",
            generation_config=genai.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            ),
            system_instruction=system_prompt
        )

        response = model.generate_content(
            [gemini_file, "Evalúa el indicador en base al documento proporcionado."]
        )
        
        result_json = json.loads(response.text)
        result_json["indicator_id"] = indicator["id"]
        return result_json
        
    except Exception as e:
        logger.error(f"Error evaluando indicador {indicator['id']}: {e}", exc_info=True)
        return {
            "indicator_id": indicator["id"],
            "cumple": "ERROR",
            "evidencia_literal": "",
            "pagina_real": "",
            "razonamiento": f"Error interno en la evaluación: {str(e)}"
        }

def run_empirical_audit_async(thread_id: str, file_path: str, uid: str):
    """Ejecuta la auditoría subiendo el PDF a Gemini y evaluándolo."""
    doc_ref = firestore_db.collection("empirical_audits").document(thread_id)
    
    doc_ref.set({
        "uid": uid,
        "filename": os.path.basename(file_path),
        "status": "processing",
        "created_at": SERVER_TIMESTAMP,
        "results": {}
    }, merge=True)
    
    logger.info(f"Iniciando auditoría empírica para thread {thread_id}, file {file_path}")
    
    gemini_file = None
    temp_dir = os.path.dirname(file_path)
    try:
        # 1. Upload to Gemini (with retry for transient SSL/network errors)
        max_upload_retries = 3
        for attempt in range(1, max_upload_retries + 1):
            try:
                logger.info(f"Uploading {file_path} to Gemini (attempt {attempt}/{max_upload_retries})...")
                gemini_file = genai.upload_file(file_path)
                break
            except Exception as upload_exc:
                logger.warning(f"Upload attempt {attempt} failed: {upload_exc}")
                if attempt == max_upload_retries:
                    raise
                time.sleep(3 * attempt)  # back-off: 3s, 6s
        
        # 2. Wait for processing
        while gemini_file.state.name == "PROCESSING":
            logger.info("Waiting for file processing...")
            time.sleep(2)
            gemini_file = genai.get_file(gemini_file.name)
            
        if gemini_file.state.name == "FAILED":
            raise Exception("Gemini file processing failed")
            
        logger.info(f"File uploaded successfully. URI: {gemini_file.uri}")

        # 3. Ejecutar evaluaciones concurrentemente (limitado a 5 workers para no saturar API)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_ind = {executor.submit(_evaluate_indicator, ind, gemini_file): ind for ind in INDICATORS}
            
            for future in as_completed(future_to_ind):
                ind = future_to_ind[future]
                try:
                    result = future.result()
                    doc_ref.update({
                        f"results.{result['indicator_id']}": result,
                        "updated_at": SERVER_TIMESTAMP
                    })
                    logger.info(f"Indicador {result['indicator_id']} evaluado para {thread_id}")
                except Exception as e:
                    logger.error(f"Error procesando future de indicador {ind['id']}: {e}")
                    
        # Finalizar auditoría
        doc_ref.update({
            "status": "completed",
            "completed_at": SERVER_TIMESTAMP
        })
        logger.info(f"Auditoría empírica finalizada para thread {thread_id}")

    except Exception as e:
        logger.error(f"Failed to complete empirical audit: {e}", exc_info=True)
        doc_ref.update({
            "status": "error",
            "error_msg": str(e),
            "updated_at": SERVER_TIMESTAMP
        })
    finally:
        # 4. Clean up: eliminate the entire temp directory (avoids WinError 32 race condition
        #    where Flask still holds the file handle when os.remove() is called)
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Deleted local temp dir {temp_dir}")
        except Exception as e:
            logger.warning(f"Could not delete temp dir {temp_dir}: {e}")
        # Optional: Delete from Gemini to save space/quota
        if gemini_file:
            try:
                genai.delete_file(gemini_file.name)
                logger.info(f"Deleted Gemini file {gemini_file.name}")
            except Exception as e:
                logger.warning(f"Could not delete Gemini file {gemini_file.name}: {e}")
