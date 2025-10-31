# Conectividad y Red

Guía de configuración de red para integrar Cloud Run con el MCP server y LM Studio on-premise.

## Componentes

- **Cloud Run (orquestador)**: despliegue en `europe-west1` utilizando conector Serverless VPC Access.
- **VPC híbrida**: VPC de GCP extendida a la red corporativa mediante Cloud VPN o Cloud Interconnect.
- **MCP server (Windows 11 Pro)**: expone `http://<host>:8088`.
- **LM Studio server**: expone API OpenAI-compatible en `http://<host>:1234`.

## Pasos en GCP

1. **Serverless VPC Access Connector**
   ```bash
   gcloud compute networks vpc-access connectors create recava-advisor-conn \
     --region=europe-west1 \
     --network=default \
     --range=10.8.0.0/28
   ```
2. **Conectividad on-prem**
   - Configura Cloud VPN (Dynamic Routing) o Cloud Interconnect.
   - Propaga rutas hacia la subred on-prem (por ejemplo `10.10.0.0/24`).
3. **Firewall**
   - Permite tráfico TCP desde el rango del conector (`10.8.0.0/28`) hacia:
     - `10.10.0.5:8088` (MCP server)
     - `10.10.0.6:1234` (LM Studio) si se accede directamente
4. **Cloud Run**
   - Despliega con:
     ```
     --vpc-connector=projects/$PROJECT_ID/locations/${_REGION}/connectors/recava-advisor-conn
     --egress-settings=all
     ```
   - Define `MCP_SERVER_URL=http://10.10.0.5:8088` y `CHAT_GENERATOR=mcp`
   - Usa Secret Manager para `MCP_API_KEY`.

## Host On-Prem (Windows 11)

- Asigna IP estática (ej. `10.10.0.5`) y habilita los puertos 8088 y 1234 en Windows Defender Firewall (solo para la subred del túnel).
- Asegura que LM Studio está en modo “Serve on Network”.
- Ejecuta `ops/windows/install.ps1` para instalar dependencias del MCP server.
- Registra el servicio con `ops/windows/nssm-mcp-service.bat`.

## Observabilidad

- Endpoint `GET http://10.10.0.5:8088/healthz` controlado por Cloud Run (usa `requests.get` desde un job de monitor).
- Recolecta logs desde `%REPO_ROOT%\logs\mcp-server.*.log`.
- Configura alertas en Cloud Monitoring basadas en errores 5xx en Cloud Run y latencia del MCP adapter.

## Seguridad adicional

- Ejecuta el MCP server solo detrás de VPN; opcionalmente usa TLS/mTLS (recomendado si se expone fuera).
- Rota la API key almacenada en Secret Manager (`mcp-api-key`) periódicamente.
