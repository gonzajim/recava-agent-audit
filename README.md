# recava-agent-audit
Orquestador en GCP + OpenAI Responses API & Agents SDK
ReCaVa - Arquitectura cloud multiagente para proceso auditoría.

Los usuarios pueden interactuar con el sistema de agentes de dos modos principales:
a través de una interfaz web embebida (widget o iframe) en un sitio web
o mediante llamadas directas a la API REST expuesta por Cloud Run.
La capa de autenticación y control de acceso se gestiona con IAM de GCP (permiso Cloud Run Invoker para allUsers o grupos específicos) o con un API Gateway/IAP si se requiere seguridad adicional.
Desde dispositivos móviles basta con cargar la misma interfaz web en un WebView o envolver peticiones al endpoint REST. Los desarrolladores integran el widget copiando un script de JavaScript que carga un iframe apuntando a un servidor estático (React/Vite/Tailwind) que sirva la UI de chat y, tras cada mensaje del usuario, el frontend envía la petición al Orquestador en Cloud Run, que invoca los Assistants de OpenAI y retorna la respuesta al cliente.

1. interacción del usuario
El usuario escribe en el chat widget incrustado en tu web o app móvil. El componente front-end simplemente envía un POST JSON al endpoint HTTPS de Cloud Run. Comunidad OpenAIGoogle Cloud
2. orquestador en Cloud Run
El contenedor serverless recibe la petición y ejecuta la lógica del Agents SDK:
decide si delega en el Auditor o en el Asistente


pasa el contexto acumulado en el hilo


recibe la respuesta estructurada de la Responses API. GitHubopenai.github.io


Cloud Run se factura sólo por CPU-segundos y memoria usados, con free tier mensual para cargas bajas, por lo que el coste fijo es casi nulo. Google Cloud
3. ejecución de agentes en OpenAI
La API de Assistants (usada por el orquestador para invocar a los sub-agentes) enruta la solicitud al assistant adecuado:
Assistant Sostenibilidad – RAG nativo para contestar dudas técnicas (asumido, la implementación depende de la configuración del Assistant `ASISTENTE_ID`). MediumComunidad OpenAI


Assistant Auditoría – recorre la lista de preguntas y mantiene el estado del cuestionario (asumido, la implementación depende de la configuración del Assistant `AUDITOR_ID`).


Los dos assistants viven “hosted” en OpenAI.
4. persistencia y trazabilidad
Al cerrar cada iteración (o al terminar el workflow) el orquestador:
compone la entrada “pregunta + respuesta” en un objeto JSON/Markdown,


la guarda en Cloud Storage o Firestore para consulta y auditoría (Nota: esta funcionalidad no está implementada en el `main.py` actual pero está descrita como parte de la arquitectura). Google CloudGoogle Cloud


5. respuesta al front-end
La respuesta estructurada vuelve al front-end, que la muestra en la ventana de chat. Para integraciones de terceros, el mismo endpoint de Cloud Run (`/orchestrate`) funciona como API REST autenticada mediante IAM o IAP. Google CloudStack Overflow

El endpoint `/health` también está disponible para comprobaciones de estado del servicio.

## Sistema de créditos

Los usuarios deben autenticarse con Firebase y disponer de créditos en Firestore.
Al llamar a `/chat_auditor` o `/chat_assistant` se verifica el token enviado en
`Authorization` y se descuenta un crédito del documento `users/{uid}`. Si el
saldo es insuficiente se devuelve un error 402. Para adquirir nuevos créditos el
endpoint `/create-checkout-session` genera una sesión de pago de Stripe
asociada al usuario.

## Variables de entorno necesarias

Para ejecutar el orquestador se requieren las siguientes variables de entorno:

- `OPENAI_API_KEY` – clave de API para invocar los asistentes de OpenAI.
- `ORCHESTRATOR_ASSISTANT_ID` – identificador del assistant principal.
- `ASISTENTE_ID` – identificador del assistant de sostenibilidad.
- `STRIPE_API_KEY` – clave secreta utilizada por la integración de Stripe para
  crear sesiones de pago.
- `BIGQUERY_DATASET_ID` – dataset de BigQuery donde se almacenan los datos.
- `BIGQUERY_TABLE_ID` – tabla de BigQuery de auditoría.
