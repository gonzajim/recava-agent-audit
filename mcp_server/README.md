# MCP Server (On-Prem)

Microservicio MCP alojado on-premise en Windows 11 Pro. Expone herramientas de la red de agentes mediante el SDK oficial (FastMCP) sobre HTTP streamable para consumo desde el orquestador en Cloud Run.

## Componentes

- `app.py`: inicializa el servidor FastMCP, registra las tools y expone endpoints de salud (`/healthz`, `/info`).
- `settings.py`: configuración basada en `pydantic-settings` para host, puertos, timeouts y credenciales.
- `tools/`: colección de herramientas MCP (puente a LM Studio, verificadores de política, formateadores).
- `adapters/lmstudio_client.py`: cliente `httpx` para hablar con LM Studio usando la API OpenAI-compatible.
- `requirements.txt`: dependencias exactas para crear el entorno virtual en Windows.

## Variables de Entorno (prefijo `MCP_`)

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `MCP_HOST` | Dirección de enlace del servidor HTTP | `0.0.0.0` |
| `MCP_PORT` | Puerto para el MCP server | `8088` |
| `MCP_LMSTUDIO_BASE_URL` | URL base del servidor LM Studio | `http://192.168.1.50:1234` |
| `MCP_LMSTUDIO_API_KEY` | (Opcional) API key si LM Studio la requiere | `super-secret` |
| `MCP_LMSTUDIO_MODEL` | Modelo por defecto servido por LM Studio | `qwen2.5-7b` |
| `MCP_REQUEST_TIMEOUT_SECS` | Timeout de lectura para LM Studio | `30` |
| `MCP_MAX_COMPLETION_TOKENS` | Límite de tokens por respuesta | `1024` |

## Ejecución Local (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m mcp_server.app  # o: uvicorn mcp_server.app:app --host 0.0.0.0 --port 8088
```

Con el servidor listo, verifica la salud:

```powershell
Invoke-RestMethod http://localhost:8088/healthz
```

## Servicio en Windows (NSSM)

1. Instala dependencias con `ops/windows/install.ps1`.
2. Registra el servicio con `nssm-mcp-service.bat` para que arranque con el sistema y reinicie en caso de fallo.

## Flujo Típico

1. El orquestador en Cloud Run invoca la Responses API con `file_search` sobre OpenAI Vector Stores.
2. El agente decide llamar a herramientas MCP (este servidor) para razonamiento local con LM Studio o utilidades.
3. Este servicio envía las peticiones a LM Studio (`lmstudio_chat`) o ejecuta validaciones locales y devuelve los resultados.

## Próximos Pasos

- Reemplaza la lógica de `policy_check` y `format_answer` con tus implementaciones reales.
- Añade autenticación (p. ej., API key o mTLS) si el servicio va a exponerse fuera de VPN.
- Configura supervisión del servicio (`/healthz`) desde tu monitor en la red on-premise.
