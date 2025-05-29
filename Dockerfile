# ---- Builder Stage ----
FROM python:3.10-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Instalar dependencias del sistema necesarias para construir algunos paquetes de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app-build

# Copiar solo requirements.txt primero para aprovechar el cache de Docker
COPY requirements.txt requirements.txt

# Crear y activar un entorno virtual, luego instalar dependencias
RUN echo "--- Creating venv ---" && \
    python3 -m venv /opt/venv && \
    echo "--- Installing requirements into venv using /opt/venv/bin/pip ---" && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    echo "--- Builder stage diagnostic checks complete ---"

# ---- Final Stage ----
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # PORT se inyecta por Cloud Run, por defecto es 8080
    PORT=8080

ARG APP_USER_UID=1000
ARG APP_USER_GID=1000

# Instalar curl para el healthcheck y otras dependencias mínimas de runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    # libgomp1 # Solo si es estrictamente necesario por alguna dependencia
    && rm -rf /var/lib/apt/lists/*

# Crear un usuario y grupo no root
RUN groupadd --gid ${APP_USER_GID} appgroup && \
    useradd --uid ${APP_USER_UID} --gid ${APP_USER_GID} --create-home --shell /sbin/nologin appuser

# Copiar el entorno virtual del builder stage
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

WORKDIR /app

# Copiar el código de la aplicación. Asumimos que tu archivo principal es app.py
# Si se llama diferente (ej. main.py), ajusta el COPY y el CMD.
COPY --chown=appuser:appgroup app.py .
# Si tienes otros archivos/directorios que tu app necesita (ej. plantillas, estáticos), cópialos también.
# COPY --chown=appuser:appgroup templates/ templates/
# COPY --chown=appuser:appgroup static/ static/

USER appuser

# Exponer el puerto en el que Gunicorn escuchará (coincide con $PORT)
EXPOSE 8080

# Healthcheck para Cloud Run
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Comando para ejecutar la aplicación Flask con Gunicorn
# Asegúrate de que "app:app" coincida con tu_nombre_de_archivo:nombre_de_instancia_flask
# Ejemplo: si tu archivo es mi_app.py y la instancia es flask_app = Flask(__name__), usa "mi_app:flask_app"
CMD ["/opt/venv/bin/gunicorn", "app:app", \
     "--bind", "0.0.0.0:${PORT}", \
     "--workers", "4", \
     # "--worker-class", "sync", # Gunicorn usa 'sync' por defecto para WSGI
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
