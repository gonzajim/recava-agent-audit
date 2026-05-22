# Especificación Técnica y Funcional: Módulo de Autoauditoría Híbrida
**Estado:** Propuesta de Modificación  
**Rama Base:** `buscador-indicadores`  
**Tecnologías Clave:** Gemini (RAG), Pinecone, React (Frontend), Python (Flask Backend), Firestore (Persistencia)

---

## 1. Objetivo General
Evolucionar el sistema actual para permitir que un usuario corporativo realice un proceso estructurado de **autoauditoría de sostenibilidad y Derechos Humanos**, utilizando como base los 7 bloques normativos de preguntas cargados en el sistema. 

El sistema debe operar de forma **híbrida**:
1. **Modo Auditor (Flujo Principal):** Guía al usuario de manera secuencial y persistente a través del cuestionario, validando entradas.
2. **Modo Asesor (Flujo Contextual):** Permite al usuario interrumpir el cuestionario en cualquier pregunta para resolver dudas técnicas con el asistente RAG (Gemini) sin perder su progreso ni las respuestas previas.

---

## 2. Arquitectura del Flujo y Estados de Interacción

La conversación o interfaz tendrá un comportamiento de máquina de estados:

```text
[Fase de Auditoría X] ---> (Pregunta X.Y) 
                               |
        +----------------------+----------------------+
        | (Usuario responde)                          | (Usuario tiene dudas)
        v                                             v
[Guardar en Firestore]                        [Activar Modo Asesor]
        |                                             |
        v                                             v
[Avanzar a Pregunta X.Y+1]              [Búsqueda Pinecone + Prompt Gemini]
                                                      |
                                                      v
                                              [Resolver Duda]
                                                      |
                                                      v
                                          [Retornar a Pregunta X.Y]
```

### Reglas de Negocio
* **Persistencia:** Las respuestas del usuario deben guardarse de forma asíncrona en cada paso utilizando Firestore (colección `interactive_audits`).
* **Aislamiento del Contexto de Duda:** Cuando el usuario hace una pregunta libre en medio de la auditoría, el prompt enviado a Gemini debe incluir la pregunta del cuestionario actual y el **contexto legal recuperado de Pinecone** como contexto prioritario.

---

## 3. Modelo de Datos del Cuestionario (Base Documental)

El motor de la auditoría se dividirá en 7 fases fijas extraídas del corpus documental:

| Fase | Bloque Normativo | Fuente Documental |
| :--- | :--- | :--- |
| **Fase 1** | Compromiso Institucional y Gobernanza | *Preguntas Frecuentes sobre Políticas y Códigos...* |
| **Fase 2** | Identificación y Evaluación de Impactos | *Preguntas Frecuentes sobre el Análisis de Riesgos.pdf* |
| **Fase 3** | Gestión Operativa y Supervisión del Sistema | *Preguntas Frecuentes sobre el Funcionamiento...* |
| **Fase 4A**| Riesgo Específico: Trabajo Infantil | *Preguntas sobre riesgos específicos - TRABAJO INFANTIL.pdf* |
| **Fase 4B**| Riesgo Específico: Condiciones Dignas | *Preguntas riesgos específicos - Condiciones de Trabajo Dignas.pdf* |
| **Fase 5** | Medidas de Transparencia y Difusión | *Preguntas Frecuentes sobre Medidas de Transparencia...* |
| **Fase 6** | Reporte de Desempeño (Informe de Progreso) | *Preguntas frecuentes sobre el Informe de Progreso...* |
| **Fase 7** | Mecanismos de Reparación de Daños | *Preguntas frecuentes sobre reparación de daños...* |

---

## 4. Modificaciones Requeridas en el Backend (`app.py`)

Se deben implementar endpoints específicos bajo la ruta `/api/audit/interactive/` para manejar este flujo, manteniendo separados los endpoints actuales de auditoría empírica (`/api/audit/empirical/`).

### 4.1. Estructura del Estado de la Auditoría en Firestore
Cada sesión de auditoría interactiva debe almacenar el progreso en un documento de Firestore:
```json
{
  "thread_id": "interactive_uuid-12345",
  "uid": "user_firebase_id",
  "status": "in_progress",
  "current_phase": 1,
  "current_question_id": "1.1.1.1",
  "responses": {
    "1.1.1.1": "2022",
    "1.1.1.4": "Sí, externalizado con consultora ESG"
  },
  "updated_at": "2023-10-27T10:00:00Z"
}
```

### 4.2. Nuevos Endpoints API

* **`POST /api/audit/interactive/start`**
  * **Descripción:** Inicializa una nueva sesión de autoauditoría interactiva en Firestore y devuelve el `thread_id` y la primera pregunta.

* **`GET /api/audit/interactive/<thread_id>/state`**
  * **Descripción:** Devuelve el estado completo de la auditoría (fase actual, respuestas dadas, próxima pregunta), útil para reconexiones o recargas del frontend.

* **`POST /api/audit/interactive/<thread_id>/submit`**
  * **Descripción:** Registra la respuesta del usuario a la pregunta actual en Firestore y devuelve la información de la siguiente pregunta.

* **`POST /api/audit/interactive/<thread_id>/consult-advisor`**
  * **Descripción:** Endpoint del **Modo Asesor**. Recibe la duda del usuario y el ID de la pregunta actual. Invoca a Pinecone para el contexto y a Gemini para la respuesta.
  * **Payload:**
    ```json
    {
      "question_id": "1.1.4.1",
      "user_doubt": "¿Qué implicaciones legales tiene vincular esto con el artículo 31 bis del Código Penal?"
    }
    ```

---

## 5. Estrategia de Prompt Engineering para el Modo Asesor

Cuando se invoque el endpoint `consult-advisor`, el prompt del sistema enviado a Gemini debe estructurarse dinámicamente inyectando el contexto vectorial:

```text
Eres el Modo Asesor de un sistema de auditoría experta en sostenibilidad y Derechos Humanos. 
El usuario está realizando una autoauditoría corporativa y tiene una duda sobre una pregunta específica.

[CONTEXTO DE LA AUDITORÍA]
- Pregunta actual: {current_question_text}
- ID de la pregunta: {current_question_id}

[BASE LEGAL / CORPUS EXPERTO]
{legal_context_from_pinecone}

[DUDA DEL USUARIO]
"{user_doubt}"

INSTRUCCIONES:
1. Utiliza estrictamente la BASE LEGAL proporcionada para dar una respuesta concisa, didáctica y adaptada al sector empresarial.
2. Explica claramente qué significa el concepto que el usuario no comprende en el contexto de la directiva CSDDD/ESRS.
3. Propón un ejemplo de qué tipo de evidencia o respuesta se espera en este paso del cuestionario (ej. "Indicar el año de aprobación").
4. Finaliza SIEMPRE tu respuesta invitando amigablemente al usuario a completar el campo de la pregunta para continuar con la auditoría.
```

---

## 6. Modificaciones Requeridas en el Frontend (React / Widget)

Dado que existen dos interfaces en el proyecto, se recomienda aplicar una estrategia adaptada a cada una:

### Opción A: Interfaz Dividida (Split Screen) - *Recomendada para el `admin-panel`*
Ideal para usuarios corporativos que interactúan desde el dashboard.
* **Lado Izquierdo:** Un formulario wizard estructurado mostrando la Fase, la pregunta actual, inputs de respuesta y barra de progreso.
* **Lado Derecho:** Un panel lateral o *drawer* colapsable que actúa como el "Modo Asesor". Al hacer clic en "¿Dudas con esta pregunta?", el panel se abre con contexto de la pregunta actual, permitiendo chatear con Gemini sin perder de vista el formulario.

### Opción B: Flujo Conversacional Unificado - *Recomendada para el `chatbot` widget*
Ideal para la integración web ligera (`bubble-prod-script.js`).
* El bot toma el rol de Auditor y escribe la pregunta en el flujo del chat.
* El usuario puede responder directamente o pulsar un botón de **"Tengo dudas"**.
* Al activar las dudas, la interfaz cambia a **Modo Asesor** (cambio visual de colores/iconos) permitiendo chat libre sobre la pregunta. Un botón de "Volver a responder" retorna el flujo al Modo Auditor.

---

## 7. Plan de Implementación Sugerido

* **Sprint 1 (Backend - Datos):** 
  * Crear archivo estructurado `cuestionario_base.json` con las preguntas de los 7 bloques.
  * Implementar estructura en Firestore (`interactive_audits`) y endpoints de inicio y navegación (`start`, `state`, `submit`).
* **Sprint 2 (Backend - Inteligencia):** 
  * Implementar `consult-advisor` conectando `src/vector_service.py` (Pinecone) con la generación RAG de Gemini usando el nuevo prompt dinámico.
* **Sprint 3 (Frontend - Admin Panel):** 
  * Desarrollar el componente `InteractiveAuditViewer.js` usando la Opción A (Split Screen) en Material UI.
* **Sprint 4 (Frontend - Chatbot & Testing):** 
  * Adaptar `bubble-prod-script.js` para soportar la Opción B en el widget.
  * Pruebas End-to-End asegurando que el estado persiste al recargar la página.
